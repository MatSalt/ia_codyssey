import asyncio
from datetime import timedelta
import pytest
from sqlalchemy import select
from backend.models import Task, Page, Run
from backend.generation.repository import claim_task


async def add_tasks(db, seeded, stage, count, config=None):
    async with db() as s, s.begin():
        original = await s.get(Task, seeded['task'])
        original.stage = stage
        run = await s.get(Run, seeded['run'])
        if config is not None: run.config_snapshot = config
        for index in range(2, count+1):
            page = Page(album_id=seeded['album'], position=index, selection_index=index); s.add(page); await s.flush()
            s.add(Task(run_id=run.id, page_id=page.id, stage=stage))


@pytest.mark.asyncio
@pytest.mark.parametrize('stage,cap', [('caption',4), ('image_transform',2)])
async def test_simultaneous_claims_respect_global_stage_cap(db, seeded, stage, cap):
    await add_tasks(db, seeded, stage, 12)
    async def claim():
        async with db() as s:
            return await claim_task(s, seeded['now'], 90, stage=stage)
    claims = await asyncio.wait_for(asyncio.gather(*(claim() for _ in range(12))), 5)
    assert sum(x is not None for x in claims) == cap
    assert len({x.task_id for x in claims if x}) == cap


@pytest.mark.asyncio
async def test_snapshot_cap_stage_filter_and_expired_slot(db, seeded):
    await add_tasks(db, seeded, 'caption', 5, {'caption_concurrency':1})
    async with db() as s:
        assert await claim_task(s, seeded['now'], 90, stage='image_transform') is None
        first = await claim_task(s, seeded['now'], 90, stage='caption')
        assert first
        assert await claim_task(s, seeded['now'], 90, stage='caption') is None
    async with db() as s, s.begin():
        (await s.get(Task, first.task_id)).lease_until = seeded['now']-timedelta(seconds=1)
    async with db() as s:
        assert await claim_task(s, seeded['now'], 90, stage='caption')


@pytest.mark.asyncio
async def test_optimize_dependency_and_global_limit(db, seeded):
    await add_tasks(db, seeded, 'optimize', 3)
    async with db() as s:
        assert await claim_task(s, seeded['now'], 90, stage='optimize') is None
    async with db() as s, s.begin():
        tasks = list(await s.scalars(select(Task)))
        for task in tasks:
            s.add(Task(run_id=task.run_id, page_id=task.page_id, stage='image_transform', status='succeeded'))
    async def claim():
        async with db() as s:
            return await claim_task(s, seeded['now'], 90, stage='optimize')
    claims = await asyncio.gather(*(claim() for _ in range(3)))
    assert sum(x is not None for x in claims) == 1


@pytest.mark.asyncio
async def test_caps_are_global_across_runs_and_execution_modes(db, seeded):
    from backend.models import Album
    await add_tasks(db, seeded, 'caption', 5, {'caption_concurrency':2, 'execution_mode':'first'})
    async with db() as s, s.begin():
        album = await s.get(Album, seeded['album'])
        other = Album(owner_id=album.owner_id, status='processing'); s.add(other); await s.flush()
        run = Run(album_id=other.id, config_snapshot={'caption_concurrency':4, 'execution_mode':'second'})
        s.add(run); await s.flush()
        for index in range(1,6):
            page = Page(album_id=other.id, position=index, selection_index=index)
            s.add(page); await s.flush()
            s.add(Task(run_id=run.id, page_id=page.id, stage='caption'))
    async def claim(mode):
        async with db() as s:
            return await claim_task(s, seeded['now'], 90, stage='caption', execution_mode=mode)
    first = await asyncio.gather(*(claim('first') for _ in range(5)))
    second = await asyncio.gather(*(claim('second') for _ in range(5)))
    assert sum(c is not None for c in first) == 2
    assert sum(c is not None for c in second) == 2


@pytest.mark.asyncio
async def test_runner_shutdown_preserves_unknown_boundary_and_recovery(db, seeded, tmp_path):
    from backend.worker.runner import Runner, ResultStore, utcnow
    from backend.models import Attempt
    await add_tasks(db, seeded, 'caption', 5)
    entered = asyncio.Event()
    active = 0
    class Adapter:
        async def execute(self, attempt_id, stage):
            nonlocal active
            active += 1
            if active == 4: entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1
    runner = Runner(db, ResultStore(tmp_path), Adapter(), heartbeat_seconds=.02)
    async def lane():
        while not await runner.run_once(stage='caption'):
            await asyncio.sleep(.005)
    work = [asyncio.create_task(lane()) for _ in range(4)]
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert active == 4
    finally:
        for task in work: task.cancel()
        await asyncio.gather(*work, return_exceptions=True)
    assert active == 0
    async with db() as s, s.begin():
        tasks = list(await s.scalars(select(Task).where(Task.status == 'running')))
        assert len(tasks) == 4
        for task in tasks: task.lease_until = utcnow()-timedelta(seconds=1)
    await runner.recover()
    async with db() as s:
        tasks = list(await s.scalars(select(Task).where(Task.status == 'unknown')))
        assert len(tasks) == 4
        assert all(not task.safe_to_retry for task in tasks)
        assert len(list(await s.scalars(select(Attempt)))) == 4
    assert not await runner.run_once(stage='caption')


@pytest.mark.asyncio
async def test_recovery_settles_saved_result_without_waiting_for_execution_slot(db, seeded, tmp_path):
    from backend.worker.runner import Runner, ResultStore, utcnow
    await add_tasks(db, seeded, 'caption', 5)
    runner = Runner(db, ResultStore(tmp_path))
    async with db() as s:
        first = await claim_task(s, utcnow(), 90, stage='caption')
    attempt_id, _, _ = await runner.prepare(first)
    await runner.store.save(str(attempt_id), {'caption':'보존된 문장'})
    async with db() as s, s.begin():
        (await s.get(Task, first.task_id)).lease_until = utcnow()-timedelta(seconds=1)
    claims = []
    for _ in range(4):
        async with db() as s:
            claims.append(await claim_task(s, utcnow(), 90, stage='caption'))
    assert all(claims)
    assert await runner.recover() == 1
    async with db() as s:
        assert (await s.get(Task, first.task_id)).status == 'succeeded'
        assert len(list(await s.scalars(select(Task).where(Task.status == 'running')))) == 4
