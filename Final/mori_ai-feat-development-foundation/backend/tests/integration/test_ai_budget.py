"""Real PostgreSQL financial safety tests; no provider calls."""
import asyncio
from decimal import Decimal as D
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text


@pytest_asyncio.fixture
async def ledger(db):
    from backend.generation.budget import BudgetLedger
    return BudgetLedger(db, D('5'), D('100'))


@pytest.mark.asyncio
async def test_concurrent_reservations_cannot_exceed_cap(ledger):
    from backend.generation.budget import BudgetExceeded
    results = await asyncio.gather(*(ledger.reserve(uuid4(), D('1')) for _ in range(12)), return_exceptions=True)
    assert sum(r is True for r in results) == 5
    assert sum(isinstance(r, BudgetExceeded) for r in results) == 7
    assert (await ledger.summary())['charged_usd'] == D('5')


@pytest.mark.asyncio
async def test_duplicate_reservation_dispatches_once(ledger):
    attempt = uuid4()
    results = await asyncio.gather(*(ledger.reserve(attempt, D('1')) for _ in range(12)))
    assert results.count(True) == 1
    assert results.count(False) == 11
    assert (await ledger.summary())['charged_usd'] == D('1')


@pytest.mark.asyncio
async def test_unknown_retained_and_later_known_settlement_idempotent(ledger):
    attempt = uuid4()
    await ledger.reserve(attempt, D('2'))
    await ledger.settle(attempt, None, {}, None)
    await ledger.release_unsent(attempt)
    assert (await ledger.summary())['charged_usd'] == D('2')
    await ledger.settle(attempt, D('0.25'), {'input_tokens': 10}, 'req_test')
    await ledger.settle(attempt, D('0.25'), {'input_tokens': 10}, 'req_test')
    await ledger.settle(attempt, None, {}, None)
    assert (await ledger.summary())['charged_usd'] == D('0.25')


@pytest.mark.asyncio
async def test_unsent_release_keeps_duplicate_tombstone(ledger):
    attempt = uuid4()
    await ledger.reserve(attempt, D('5'))
    await ledger.release_unsent(attempt)
    await ledger.release_unsent(attempt)
    assert (await ledger.summary())['charged_usd'] == D('0')
    assert await ledger.reserve(attempt, D('5')) is False
    assert await ledger.reserve(uuid4(), D('5')) is True


@pytest.mark.asyncio
async def test_overrun_charges_actual_and_persistently_blocks(ledger, db):
    from backend.generation.budget import BudgetLedger, BudgetExceeded
    attempt = uuid4()
    await ledger.reserve(attempt, D('1'))
    await ledger.settle(attempt, D('1.01'), {}, 'req_test')
    restarted = BudgetLedger(db, D('100'), D('100'))
    assert (await restarted.summary())['charged_usd'] == D('1.01')
    with pytest.raises(BudgetExceeded):
        await restarted.reserve(uuid4(), D('0.01'))


@pytest.mark.asyncio
async def test_spend_survives_product_deletion(ledger, seeded, db):
    await ledger.reserve(uuid4(), D('2'))
    async with db() as s, s.begin():
        await s.execute(text('TRUNCATE users CASCADE'))
    assert (await ledger.summary())['charged_usd'] == D('2')


@pytest.mark.asyncio
async def test_settlement_cannot_reduce_previously_recorded_actual(ledger):
    attempt = uuid4()
    await ledger.reserve(attempt, D('2'))
    await ledger.settle(attempt, D('1'), {}, None)
    await ledger.settle(attempt, D('0.5'), {}, None)
    assert (await ledger.summary())['charged_usd'] == D('1')


@pytest.mark.asyncio
@pytest.mark.parametrize('amount', [D('0'), D('-1'), D('NaN'), D('Infinity'), 0.1])
async def test_invalid_reservation_rejected(ledger, amount):
    with pytest.raises(ValueError):
        await ledger.reserve(uuid4(), amount)
    assert (await ledger.summary())['charged_usd'] == D('0')


@pytest.mark.asyncio
async def test_concurrent_settlements_count_once_and_free_exact_capacity(ledger):
    attempt = uuid4()
    await ledger.reserve(attempt, D('5'))
    await asyncio.gather(*(ledger.settle(attempt, D('0.123456789123'), {'tokens': 1}, 'req_test') for _ in range(8)))
    assert (await ledger.summary())['charged_usd'] == D('0.123456789123')
    assert await ledger.reserve(uuid4(), D('4.876543210877')) is True
    from backend.generation.budget import BudgetExceeded
    with pytest.raises(BudgetExceeded):
        await ledger.reserve(uuid4(), D('0.000000000001'))


@pytest.mark.asyncio
async def test_unknown_and_release_race_never_erases_charge(ledger):
    attempt = uuid4()
    await ledger.reserve(attempt, D('1'))
    await asyncio.gather(ledger.release_unsent(attempt), ledger.settle(attempt, None, {}, None))
    assert (await ledger.summary())['charged_usd'] == D('1')


@pytest.mark.asyncio
async def test_unreserved_settlement_rejected(ledger):
    with pytest.raises(ValueError):
        await ledger.settle(uuid4(), D('1'), {}, None)


@pytest.mark.asyncio
@pytest.mark.parametrize('actual', [D('-1'), D('NaN'), D('Infinity'), 0.1])
async def test_invalid_actual_cannot_erase_reservation(ledger, actual):
    attempt = uuid4()
    await ledger.reserve(attempt, D('1'))
    with pytest.raises(ValueError):
        await ledger.settle(attempt, actual, {}, None)
    assert (await ledger.summary())['charged_usd'] == D('1')


@pytest.mark.asyncio
@pytest.mark.parametrize('limit,hard', [(D('0'),D('100')), (D('5'),D('4')), (D('101'),D('101')), (D('NaN'),D('100'))])
async def test_invalid_configuration_cannot_raise_authorized_cap(db, limit, hard):
    from backend.generation.budget import BudgetLedger
    with pytest.raises(ValueError):
        BudgetLedger(db, limit, hard)
