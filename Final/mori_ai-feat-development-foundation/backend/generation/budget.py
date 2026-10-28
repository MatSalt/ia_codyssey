"""Durable USD accounting. Every method commits before returning.

The caller MUST reserve before dispatch and treat False as never dispatch again.
release_unsent is an explicit assertion that no request was sent, not a timeout
recovery mechanism. Unknown calls remain charged until original usage is known.
Configuration changes and application restarts never reset spending or blocking.
"""
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert

from backend.models import AIBudgetAccount, AIBudgetEntry


class BudgetExceeded(Exception):
    """No new paid call is permitted."""


def _money(value, *, positive=False):
    if (not isinstance(value, Decimal) or not value.is_finite()
            or value < 0 or (positive and value == 0)):
        raise ValueError('USD must be a finite nonnegative Decimal (positive for reservations/limits)')
    return value


class BudgetLedger:
    def __init__(self, sessions, limit_usd: Decimal, hard_limit_usd: Decimal):
        self.sessions = sessions
        self.limit_usd = _money(limit_usd, positive=True)
        self.hard_limit_usd = _money(hard_limit_usd, positive=True)
        if limit_usd > hard_limit_usd or hard_limit_usd > Decimal('100'):
            raise ValueError('budget must satisfy operational <= authorized <= USD 100')

    async def _lock(self, session):
        await session.execute(insert(AIBudgetAccount).values(id=1).on_conflict_do_nothing())
        return await session.scalar(select(AIBudgetAccount).where(AIBudgetAccount.id == 1).with_for_update())

    async def _charged(self, session):
        return await session.scalar(select(func.coalesce(func.sum(case(
            (AIBudgetEntry.status == 'released', Decimal('0')),
            else_=func.coalesce(AIBudgetEntry.actual_usd, AIBudgetEntry.reserved_usd),
        )), Decimal('0'))))

    async def reserve(self, attempt_id: UUID, amount_usd: Decimal) -> bool:
        _money(amount_usd, positive=True)
        async with self.sessions() as session, session.begin():
            account = await self._lock(session)
            if await session.get(AIBudgetEntry, attempt_id) is not None:
                return False
            charged = await self._charged(session)
            if account.blocked or charged + amount_usd > min(self.limit_usd, self.hard_limit_usd):
                raise BudgetExceeded('AI validation budget unavailable')
            session.add(AIBudgetEntry(attempt_id=attempt_id, reserved_usd=amount_usd, status='reserved'))
            return True

    async def settle(self, attempt_id, actual_usd: Decimal | None, usage: dict,
                     provider_request_id: str | None):
        if actual_usd is not None:
            _money(actual_usd)
        async with self.sessions() as session, session.begin():
            account = await self._lock(session)
            entry = await session.get(AIBudgetEntry, attempt_id)
            if entry is None:
                raise ValueError('attempt has no budget reservation')
            # Never forget a later-discovered charge, even if caller incorrectly
            # asserted unsent earlier. Replays can increase, never erase actuals.
            if actual_usd is not None:
                entry.actual_usd = max(actual_usd, entry.actual_usd or Decimal('0'))
                entry.status = 'settled'
                if entry.actual_usd > entry.reserved_usd:
                    account.blocked = True
            elif entry.actual_usd is None:
                entry.status = 'unknown'
            if usage:
                entry.usage = usage
            if provider_request_id:
                entry.provider_request_id = provider_request_id

    async def release_unsent(self, attempt_id):
        """Caller certifies definitely unsent; observed/unknown calls never release."""
        async with self.sessions() as session, session.begin():
            await self._lock(session)
            entry = await session.get(AIBudgetEntry, attempt_id)
            if entry is not None and entry.status == 'reserved':
                entry.status = 'released'

    async def summary(self) -> dict:
        """Internal aggregate only: no user IDs, request IDs, or provider payloads."""
        async with self.sessions() as session, session.begin():
            account = await self._lock(session)
            charged = await self._charged(session)
            return {'currency': 'USD', 'charged_usd': charged,
                    'limit_usd': self.limit_usd, 'hard_limit_usd': self.hard_limit_usd,
                    'remaining_usd': max(Decimal('0'), self.limit_usd - charged),
                    'blocked': account.blocked}
