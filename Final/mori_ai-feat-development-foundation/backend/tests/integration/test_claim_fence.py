import asyncio
from datetime import timedelta
import pytest
from sqlalchemy import select, text
from backend.models import Album, Task, Page, Run

pytestmark = pytest.mark.asyncio


async def test_only_one_claim_wins(db, seeded):
    from backend.generation.repository import claim_task
    async with db() as a, db() as b:
        assert await a.scalar(text('SELECT pg_backend_pid()')) != await b.scalar(text('SELECT pg_backend_pid()'))
        await a.rollback(); await b.rollback()
        claims = await asyncio.gather(claim_task(a, seeded['now'], 90), claim_task(b, seeded['now'], 90))
    assert sum(c is not None for c in claims) == 1
    assert next(c for c in claims if c).fence_version == 1


async def test_stale_fence_cannot_settle(db, seeded):
    from backend.generation.repository import claim_task, settle_task
    async with db() as s:
        claim = await claim_task(s, seeded['now'], 90)
    async with db() as s, s.begin():
        task = await s.get(Task, claim.task_id); task.fence_version += 1; task.output_caption = '오래된 worker 결과.'
    async with db() as s:
        assert not await settle_task(s, claim.task_id, claim.fence_version, 'succeeded', seeded['now'])
        assert (await s.get(Task, claim.task_id)).status == 'running'


async def test_deleted_album_rejects_late_result(db, seeded):
    from backend.generation.repository import claim_task, settle_task
    async with db() as s:
        claim = await claim_task(s, seeded['now'], 90)
    async with db() as s, s.begin():
        album = await s.get(Album, seeded['album']); album.deleted_at = seeded['now']; album.status = 'deleted'
        (await s.get(Task, seeded['task'])).output_caption = '삭제 후 도착한 결과.'
    async with db() as s:
        assert not await settle_task(s, claim.task_id, claim.fence_version, 'succeeded', seeded['now'])
        assert (await s.get(Page, seeded['page'])).caption_text is None


async def test_expired_lease_cannot_settle(db, seeded):
    from backend.generation.repository import claim_task, settle_task
    async with db() as s:
        claim = await claim_task(s, seeded['now'], 1)
        async with s.begin():
            (await s.get(Task, claim.task_id)).output_caption = '만료 뒤 도착한 결과.'
        assert not await settle_task(s, claim.task_id, claim.fence_version, 'succeeded', seeded['now']+timedelta(seconds=1))


async def test_optimize_waits_for_image_success(db, seeded):
    from backend.generation.repository import claim_task
    async with db() as s, s.begin():
        t = await s.get(Task, seeded['task']); t.stage = 'optimize'; t.requires_ai_call = False; t.has_persisted_input = True
    async with db() as s:
        assert await claim_task(s, seeded['now'], 90) is None


async def test_action_required_blocks_new_ai_claim(db, seeded):
    from backend.generation.repository import claim_task
    async with db() as s, s.begin():
        (await s.get(Run, seeded['run'])).status = 'action_required'
    async with db() as s:
        assert await claim_task(s, seeded['now'], 90) is None


async def test_success_requires_persisted_output_and_is_terminal(db, seeded):
    from backend.generation.repository import claim_task, settle_task
    async with db() as s:
        claim = await claim_task(s, seeded['now'], 90)
        assert not await settle_task(s, claim.task_id, claim.fence_version, 'succeeded', seeded['now'])
    async with db() as s, s.begin():
        task = await s.get(Task, seeded['task']); task.output_caption = '원래 결과.'
    async with db() as s:
        assert await settle_task(s, claim.task_id, claim.fence_version, 'succeeded', seeded['now'])
        assert not await settle_task(s, claim.task_id, claim.fence_version, 'failed', seeded['now'])
        assert (await s.get(Page, seeded['page'])).caption_text == '원래 결과.'


async def test_claim_skips_locked_task_without_waiting(db, seeded):
    from backend.generation.repository import claim_task
    async with db() as locked, db() as competitor:
        async with locked.begin():
            await locked.scalar(select(Task).where(Task.id == seeded['task']).with_for_update())
            async with asyncio.timeout(1):
                assert await claim_task(competitor, seeded['now'], 90) is None
        claim = await claim_task(competitor, seeded['now'], 90)
        assert claim.task_id == seeded['task']
