"""Read-only aggregate spending report: python -m backend.generation.budget_report.

Run inside the configured service container so the report uses its persistent DB.
No keys, user IDs, request IDs, prompts or media locations are printed.
"""
import asyncio
import json
from decimal import Decimal
from sqlalchemy import select, func
from backend.database import session_factory
from backend.models import AIBudgetEntry
from backend.settings import Settings


async def main():
    settings = Settings()
    sessions = session_factory(settings.database_url)
    try:
        async with sessions() as session:
            from backend.models import AIBudgetAccount
            blocked = await session.scalar(select(AIBudgetAccount.blocked).where(AIBudgetAccount.id == 1))
            rows = (await session.execute(select(AIBudgetEntry.status, func.count(),
                func.coalesce(func.sum(AIBudgetEntry.actual_usd), 0),
                func.coalesce(func.sum(AIBudgetEntry.reserved_usd), 0))
                .group_by(AIBudgetEntry.status))).all()
            confirmed = sum((actual for status, count, actual, reserved in rows if status == 'settled'), Decimal(0))
            held = sum((reserved for status, count, actual, reserved in rows if status in {'unknown', 'reserved'}), Decimal(0))
            print(json.dumps({'currency': 'USD', 'confirmed_usage_cost_usd': str(confirmed),
                'unconfirmed_reservations_usd': str(held), 'accounted_usd': str(confirmed + held),
                'available_limit_usd': str(settings.ai_validation_initial_budget_usd),
                'authorized_limit_usd': str(settings.ai_validation_budget_usd), 'blocked': bool(blocked),
                'attempt_counts': {status: count for status, count, actual, reserved in rows}}, sort_keys=True))
    finally:
        await sessions.kw['bind'].dispose()


if __name__ == '__main__':
    asyncio.run(main())
