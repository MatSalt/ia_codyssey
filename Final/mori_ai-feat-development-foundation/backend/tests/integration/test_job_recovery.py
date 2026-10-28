import asyncio
from datetime import timedelta
from pathlib import Path
import os
import sys
import pytest
from sqlalchemy import select, func
from backend.models import Task, Attempt, Job, Outbox, Page, Run, Album
pytestmark = pytest.mark.asyncio


async def wait_marker(path, process):
    for _ in range(300):
        if path.exists():
            return
        if process.returncode is not None:
            raise AssertionError(f'worker exited early: {process.returncode}')
        await asyncio.sleep(.02)
    raise AssertionError(f'barrier not reached: {path}')


async def crash_worker(db, seeded, tmp_path, phase):
    process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'backend.tests.integration.crash_worker', phase, str(tmp_path))
    try:
        await wait_marker(tmp_path / 'barrier', process)
        process.kill()
        await process.wait()
        assert process.returncode < 0
    finally:
        if process.returncode is None:
            process.kill(); await process.wait()
    # Expire in the database after true process termination, not a fabricated in-memory task.
    async with db() as s, s.begin():
        task = await s.get(Task, seeded['task']); task.lease_until = seeded['now'] - timedelta(seconds=1)


async def restart_worker(tmp_path):
    process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'backend.tests.integration.crash_worker', 'restart', str(tmp_path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        async with asyncio.timeout(10):
            output, errors = await process.communicate()
        assert process.returncode == 0, errors.decode()
    finally:
        if process.returncode is None:
            process.kill(); await process.wait()


async def test_sent_attempt_lease_expiry_is_unknown_without_second_call(db, seeded, tmp_path):
    from backend.worker.runner import Runner, ResultStore
    await crash_worker(db, seeded, tmp_path, 'sent')
    runner = Runner(db, ResultStore(tmp_path))
    await runner.recover(seeded['now'])
    await runner.recover(seeded['now'])
    async with db() as s:
        assert (await s.get(Task, seeded['task'])).status == 'unknown'
        assert (await s.get(Run, seeded['run'])).status == 'action_required'
        assert (await s.get(Album, seeded['album'])).version == 2
        assert await s.scalar(select(func.count()).select_from(Job).where(Job.kind == 'reconcile_attempt')) == 1
    # Restart production Runner with the same counting fake: unknown must never be dispatched.
    await restart_worker(tmp_path)
    assert (tmp_path / 'calls').read_text() == 'call\n'


async def test_unsent_attempt_can_requeue(db, seeded, tmp_path):
    from backend.worker.runner import Runner, ResultStore
    await crash_worker(db, seeded, tmp_path, 'prepared')
    runner = Runner(db, ResultStore(tmp_path))
    await runner.recover(seeded['now'])
    async with db() as s:
        assert (await s.get(Task, seeded['task'])).status == 'queued'
    assert not (tmp_path / 'calls').exists()
    await restart_worker(tmp_path)
    async with db() as s:
        assert (await s.get(Task, seeded['task'])).status == 'succeeded'
    assert (tmp_path / 'calls').read_text() == 'call\n'


async def test_saved_result_recovers_without_ai(db, seeded, tmp_path):
    from backend.worker.runner import Runner, ResultStore
    await crash_worker(db, seeded, tmp_path, 'saved')
    await restart_worker(tmp_path)
    runner = Runner(db, ResultStore(tmp_path))
    await runner.recover(seeded['now'])
    await runner.recover(seeded['now'])
    async with db() as s:
        assert (await s.get(Task, seeded['task'])).status == 'succeeded'
        assert (await s.get(Page, seeded['page'])).caption_text == '보존된 한 문장.'
    assert (tmp_path / 'calls').read_text() == 'call\n'


async def test_outbox_replay_has_one_cleanup_job(db, seeded):
    from backend.worker.jobs import dispatch_outbox
    async with db() as s, s.begin():
        s.add_all([Outbox(event_type='album_cleanup', entity_id=seeded['album']), Outbox(event_type='album_cleanup', entity_id=seeded['album'])])
    async with db() as a, db() as b:
        await asyncio.gather(dispatch_outbox(a, seeded['now']), dispatch_outbox(b, seeded['now']))
    async with db() as s:
        jobs = (await s.scalars(select(Job))).all()
        assert len(jobs) == 1 and jobs[0].kind == 'cleanup_album'
        events = (await s.scalars(select(Outbox))).all()
        assert all(e.published_at is not None for e in events)
        for event in events:
            event.published_at = None
        await s.commit()
        await dispatch_outbox(s, seeded['now'])
        assert await s.scalar(select(func.count()).select_from(Job)) == 1


async def test_heartbeat_uses_independent_session_while_adapter_waits(db, seeded, tmp_path):
    from backend.worker.runner import Runner, ResultStore
    from backend.tests.integration.crash_worker import CountingAdapter
    runner = Runner(db, ResultStore(tmp_path), CountingAdapter(tmp_path), lease_seconds=2, heartbeat_seconds=.05)
    running = asyncio.create_task(runner.run_once())
    try:
        await wait_marker(tmp_path/'barrier', type('P', (), {'returncode': None})())
        async with db() as s:
            first = (await s.get(Task, seeded['task'])).lease_until
        await asyncio.sleep(.2)
        async with db() as s:
            assert (await s.get(Task, seeded['task'])).lease_until > first
            # Acquiring album lock during adapter wait proves no external-call row lock.
            async with asyncio.timeout(1):
                await s.scalar(select(Album).where(Album.id == seeded['album']).with_for_update())
        (tmp_path/'release').touch()
        assert await running
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)


async def test_job_lease_recovery_rejects_old_fence(db, seeded):
    from backend.worker.jobs import claim_job, recover_jobs, finish_job, reserve_upload_validation
    async with db() as s:
        await reserve_upload_validation(s, seeded['upload'], seeded['now'])
    async with db() as a, db() as b:
        claims = await asyncio.gather(claim_job(a, seeded['now'], 1, ['validate_upload']), claim_job(b, seeded['now'], 1, ['validate_upload']))
        assert sum(c is not None for c in claims) == 1
    old = next(c for c in claims if c)
    async with db() as s:
        assert await recover_jobs(s, seeded['now']+timedelta(seconds=1)) == 1
        newer = await claim_job(s, seeded['now']+timedelta(seconds=2), 90, ['validate_upload'])
        assert newer.fence_version > old.fence_version
        assert not await finish_job(s, old, seeded['now']+timedelta(seconds=2))
        assert await finish_job(s, newer, seeded['now']+timedelta(seconds=2))


async def test_saved_result_checksum_mismatch_stays_unknown(db, seeded, tmp_path):
    from backend.worker.runner import Runner, ResultStore
    await crash_worker(db, seeded, tmp_path, 'saved')
    path = next((tmp_path/'attempts').glob('*.json'))
    path.write_text(path.read_text().replace('sha256', 'broken'))
    await Runner(db, ResultStore(tmp_path)).recover(seeded['now'])
    async with db() as s:
        assert (await s.get(Task, seeded['task'])).status == 'unknown'
        assert (await s.get(Page, seeded['page'])).caption_text is None
    assert (tmp_path/'calls').read_text() == 'call\n'


async def test_worker_entrypoint_sigterm(db, seeded, tmp_path):
    process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'backend.worker', env={**os.environ, 'STORAGE_ROOT': str(tmp_path), 'WORKER_POLL_SECONDS': '.05'}, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        async with asyncio.timeout(5):
            while b'Worker DB recovery ready' not in await process.stderr.readline():
                assert process.returncode is None
        process.terminate()
        async with asyncio.timeout(5):
            output, errors = await process.communicate()
        assert process.returncode == 0
        assert b'Worker stopped safely' in errors
    finally:
        if process.returncode is None:
            process.kill(); await process.wait()


async def test_received_caption_in_db_recovers_without_file_or_ai(db, seeded, tmp_path):
    from backend.worker.runner import Runner, ResultStore
    from backend.generation.repository import claim_task
    runner = Runner(db, ResultStore(tmp_path))
    async with db() as s:
        claim = await claim_task(s, seeded['now'], 90)
    attempt_id, _, _ = await runner.prepare(claim)
    async with db() as s, s.begin():
        task = await s.get(Task, seeded['task']); task.lease_until = seeded['now']-timedelta(seconds=1)
        attempt = await s.get(Attempt, attempt_id); attempt.status = 'received'; attempt.dispatch_state = 'accepted_or_unknown'; attempt.output_caption = 'DB에 보존한 응답.'
    assert await runner.recover(seeded['now']) == 1
    async with db() as s:
        assert (await s.get(Page, seeded['page'])).caption_text == 'DB에 보존한 응답.'
        assert (await s.get(Task, seeded['task'])).status == 'succeeded'


async def test_unsent_recovery_stops_at_attempt_budget(db, seeded, tmp_path):
    from backend.worker.runner import Runner, ResultStore
    from backend.generation.repository import claim_task
    runner = Runner(db, ResultStore(tmp_path))
    async with db() as s:
        claim = await claim_task(s, seeded['now'], 90)
    attempt_id, _, _ = await runner.prepare(claim)
    async with db() as s, s.begin():
        task = await s.get(Task, seeded['task']); task.lease_until = seeded['now']-timedelta(seconds=1)
        task.attempt_count = 3
        (await s.get(Attempt, attempt_id)).attempt_no = 3
    await runner.recover(seeded['now'])
    async with db() as s:
        assert (await s.get(Task, seeded['task'])).status == 'failed'
        assert (await s.get(Run, seeded['run'])).status == 'action_required'
        assert (await s.get(Album, seeded['album'])).status == 'action_required'


@pytest.mark.parametrize('mode', ['live', 'recover'])
@pytest.mark.parametrize('case', ['missing', 'null', 'empty', 'space', 'uuid', 'absent', 'pending', 'owner', 'deleted'])
async def test_invalid_preserved_result_converges(db, seeded, tmp_path, mode, case):
    from uuid import uuid4
    from backend.models import MediaAsset, User
    from backend.worker.runner import Runner, ResultStore
    from backend.generation.repository import claim_task
    result = {'caption': None} if case == 'null' else {'caption': '' if case == 'empty' else '   ' if case == 'space' else 'valid'}
    if case == 'missing':
        result = {}
    if case in {'uuid', 'absent', 'pending', 'owner', 'deleted'}:
        async with db() as s, s.begin():
            (await s.get(Task, seeded['task'])).stage = 'image_transform'
            asset = MediaAsset(owner_id=(await s.get(Album, seeded['album'])).owner_id, album_id=seeded['album'], page_id=seeded['page'], role='result', storage_key=str(uuid4()), mime='image/webp', status='ready')
            if case == 'pending': asset.status = 'pending'
            if case == 'deleted': asset.deleted_at = seeded['now']
            if case == 'owner':
                user = User(); s.add(user); await s.flush(); asset.owner_id = user.id
            s.add(asset); await s.flush()
            result = {'asset_id': 'broken' if case == 'uuid' else str(uuid4()) if case == 'absent' else str(asset.id)}
    class Adapter:
        calls = 0
        async def execute(self, *args):
            self.calls += 1
            return result
    adapter = Adapter(); store = ResultStore(tmp_path); runner = Runner(db, store, adapter)
    if mode == 'live':
        assert await runner.run_once()
    else:
        async with db() as s:
            claim = await claim_task(s, seeded['now'], 90)
        attempt_id, _, _ = await runner.prepare(claim)
        await store.save(str(attempt_id), result)
        async with db() as s, s.begin():
            (await s.get(Task, seeded['task'])).lease_until = seeded['now']-timedelta(seconds=1)
            (await s.get(Attempt, attempt_id)).dispatch_state = 'accepted_or_unknown'
        await runner.recover(seeded['now'])
    async with db() as s:
        task = await s.get(Task, seeded['task'])
        assert task.status == 'failed'
        assert task.error_code == ('CAPTION_INVALID' if task.stage == 'caption' else 'MEDIA_SAVE_FAILED')
        assert task.safe_to_retry is False
        fence = task.fence_version
        attempt = await s.scalar(select(Attempt).where(Attempt.task_id == task.id))
        key = attempt.result_key
        assert await store.load(key) == result
        assert (await s.get(Run, seeded['run'])).status == 'action_required'
        page = await s.get(Page, seeded['page'])
        assert page.caption_text is None and page.result_asset_id is None
    for _ in range(3):
        await runner.recover(seeded['now']+timedelta(days=1))
        assert not await runner.run_once()
    async with db() as s:
        task = await s.get(Task, seeded['task'])
        assert task.status == 'failed' and task.fence_version == fence
    assert adapter.calls == (1 if mode == 'live' else 0)


async def test_invalid_task_does_not_block_other_recovery_and_jobs(db, seeded, tmp_path):
    from backend.worker.runner import Runner, ResultStore
    from backend.models import MediaAsset
    from uuid import uuid4
    store = ResultStore(tmp_path)
    async with db() as s, s.begin():
        bad = await s.get(Task, seeded['task']); bad.stage = 'image_transform'
        good = Task(run_id=seeded['run'], page_id=seeded['page'], stage='caption')
        s.add(good); await s.flush()
        for task, result in [(bad, {'asset_id': 'malformed'}), (good, {'caption': '정상 복구.'})]:
            task.status = 'running'; task.fence_version = 1; task.attempt_count = 1; task.lease_until = seeded['now']-timedelta(seconds=1)
            attempt = Attempt(task_id=task.id, attempt_no=1, fence_version=1, dispatch_state='accepted_or_unknown')
            s.add(attempt); await s.flush(); attempt.result_key = str(attempt.id)
            await store.save(str(attempt.id), result)
        s.add(Outbox(event_type='album_cleanup', entity_id=seeded['album']))
    await Runner(db, store).maintenance()
    async with db() as s:
        assert (await s.get(Task, seeded['task'])).status == 'failed'
        assert (await s.get(Page, seeded['page'])).caption_text == '정상 복구.'
        assert await s.scalar(select(func.count()).select_from(Job).where(Job.kind == 'cleanup_album')) == 1


@pytest.mark.parametrize('deleted', [False, True])
async def test_received_stale_or_deleted_result_preserved_without_link(db, seeded, tmp_path, deleted):
    from backend.worker.runner import Runner, ResultStore
    from backend.generation.repository import claim_task
    runner = Runner(db, ResultStore(tmp_path))
    async with db() as s:
        claim = await claim_task(s, seeded['now'], 90)
    attempt_id, _, _ = await runner.prepare(claim)
    result = {'asset_id': 'invalid', 'caption': None}
    checksum = await runner.store.save(str(attempt_id), result)
    async with db() as s, s.begin():
        if deleted:
            album = await s.get(Album, seeded['album']); album.status = 'deleted'; album.deleted_at = seeded['now']
        else:
            (await s.get(Task, seeded['task'])).fence_version += 1
    assert not await runner._received(claim, attempt_id, result, checksum)
    async with db() as s:
        task = await s.get(Task, seeded['task'])
        assert task.status == 'running' and task.error_code is None
        assert (await s.get(Page, seeded['page'])).caption_text is None
        attempt = await s.get(Attempt, attempt_id)
        assert attempt.result_sha256 == checksum
    assert await runner.store.load(str(attempt_id)) == result


async def test_asset_invalidated_between_receive_and_settle_fails(db, seeded, tmp_path):
    from backend.models import MediaAsset
    from backend.worker.runner import Runner, ResultStore
    from uuid import uuid4
    async with db() as s, s.begin():
        (await s.get(Task, seeded['task'])).stage = 'image_transform'
        asset = MediaAsset(owner_id=(await s.get(Album, seeded['album'])).owner_id, album_id=seeded['album'], page_id=seeded['page'], role='result', storage_key=str(uuid4()), mime='image/webp', status='ready')
        s.add(asset); await s.flush(); asset_id = asset.id
    class Adapter:
        async def execute(self, *args):
            return {'asset_id': str(asset_id)}
    class InvalidatingRunner(Runner):
        async def _received(self, *args):
            accepted = await super()._received(*args)
            async with db() as s, s.begin():
                (await s.get(MediaAsset, asset_id)).deleted_at = seeded['now']
            return accepted
    assert await InvalidatingRunner(db, ResultStore(tmp_path), Adapter()).run_once()
    async with db() as s:
        task = await s.get(Task, seeded['task'])
        assert task.status == 'failed' and task.error_code == 'MEDIA_SAVE_FAILED'
        assert task.safe_to_retry is False


async def test_deleted_received_asset_enqueues_cleanup_and_preserves_response(db, seeded, tmp_path):
    from backend.models import MediaAsset
    from backend.worker.runner import Runner, ResultStore
    from backend.generation.repository import claim_task
    from uuid import uuid4
    runner = Runner(db, ResultStore(tmp_path))
    async with db() as s:
        claim = await claim_task(s, seeded['now'], 90)
    attempt_id, _, _ = await runner.prepare(claim)
    async with db() as s, s.begin():
        album = await s.get(Album, seeded['album']); album.status = 'deleted'; album.deleted_at = seeded['now']
        asset = MediaAsset(owner_id=album.owner_id, album_id=album.id, page_id=seeded['page'], role='result', storage_key=str(uuid4()), mime='image/webp', status='ready')
        s.add(asset); await s.flush(); asset_id = asset.id
    result = {'asset_id': str(asset_id)}
    checksum = await runner.store.save(str(attempt_id), result)
    assert not await runner._received(claim, attempt_id, result, checksum)
    await runner.recover(seeded['now']+timedelta(days=1))
    await runner.recover(seeded['now']+timedelta(days=2))
    async with db() as s:
        assert (await s.get(Task, seeded['task'])).status == 'cancelled'
        assert (await s.get(Page, seeded['page'])).result_asset_id is None
        assert await s.scalar(select(func.count()).select_from(Job).where(Job.kind == 'cleanup_asset', Job.target_id == asset_id)) == 1
    assert await runner.store.load(str(attempt_id)) == result


@pytest.mark.parametrize('boundary', ['owner', 'album', 'page', 'own'])
@pytest.mark.parametrize('path', ['stale', 'deleted_receive', 'deleted_recover'])
async def test_cleanup_requires_matching_asset_scope(db, seeded, tmp_path, boundary, path):
    from uuid import uuid4
    from backend.models import MediaAsset, User
    from backend.worker.runner import Runner, ResultStore
    from backend.generation.repository import claim_task
    runner = Runner(db, ResultStore(tmp_path))
    async with db() as s:
        claim = await claim_task(s, seeded['now'], 90)
    attempt_id, _, _ = await runner.prepare(claim)
    async with db() as s, s.begin():
        album = await s.get(Album, seeded['album'])
        owner_id, album_id, page_id = album.owner_id, album.id, seeded['page']
        if boundary == 'owner':
            user = User(); s.add(user); await s.flush(); owner_id = user.id
        if boundary == 'album':
            other = Album(owner_id=owner_id); s.add(other); await s.flush(); album_id = other.id
        if boundary == 'page':
            other = Page(album_id=album.id, position=2, selection_index=2); s.add(other); await s.flush(); page_id = other.id
        asset = MediaAsset(owner_id=owner_id, album_id=album_id, page_id=page_id, role='result', storage_key=str(uuid4()), mime='image/webp', status='ready')
        s.add(asset); await s.flush(); asset_id = asset.id
        task = await s.get(Task, seeded['task'])
        if path == 'stale':
            task.attempt_count += 1; task.fence_version += 1
            s.add(Attempt(task_id=task.id, attempt_no=task.attempt_count, fence_version=task.fence_version))
        else:
            album.status = 'deleted'; album.deleted_at = seeded['now']
        task.lease_until = seeded['now']-timedelta(seconds=1)
    result = {'asset_id': str(asset_id)}
    checksum = await runner.store.save(str(attempt_id), result)
    if path == 'deleted_recover':
        await runner.recover(seeded['now'])
        await runner.recover(seeded['now']+timedelta(days=1))
    else:
        for _ in range(2):
            assert not await runner._received(claim, attempt_id, result, checksum)
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(Job).where(Job.kind == 'cleanup_asset', Job.target_id == asset_id)) == (1 if boundary == 'own' else 0)
        assert (await s.get(Page, seeded['page'])).result_asset_id is None
        assert (await s.get(MediaAsset, asset_id)).status == 'ready'
    assert await runner.store.load(str(attempt_id)) == result
