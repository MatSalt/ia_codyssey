from uuid import uuid4
import pytest
from backend.models import Task, Run, Album


def test_unknown_allows_only_persisted_local_retry():
    from backend.generation.resume_policy import ResumeTask, eligible_resume_tasks
    local, missing, success, unknown = [uuid4() for _ in range(4)]
    tasks = [ResumeTask(local, 'failed', True, False, True), ResumeTask(missing, 'failed', True, False, False), ResumeTask(success, 'succeeded', True, False, True), ResumeTask(unknown, 'unknown', True, False, True)]
    assert eligible_resume_tasks(tasks, True) == [local]


def test_unknown_blocks_ai_retry():
    from backend.generation.resume_policy import ResumeTask, eligible_resume_tasks
    assert eligible_resume_tasks([ResumeTask(uuid4(), 'failed', True, True, True)], True) == []


def test_no_unknown_allows_safe_failed_retry():
    from backend.generation.resume_policy import ResumeTask, eligible_resume_tasks
    safe, unsafe = uuid4(), uuid4()
    assert eligible_resume_tasks([ResumeTask(safe, 'failed', True, True, True), ResumeTask(unsafe, 'failed', False, True, True)], False) == [safe]


@pytest.mark.asyncio
async def test_mixed_resume_keeps_action_required(db, seeded):
    from backend.generation.resume_policy import resume_failed_tasks
    async with db() as s, s.begin():
        run = await s.get(Run, seeded['run']); run.status = 'action_required'
        album = await s.get(Album, seeded['album']); album.status = 'action_required'
        task = await s.get(Task, seeded['task']); task.status = 'unknown'
        local = Task(run_id=run.id, page_id=seeded['page'], stage='image_transform', status='failed', safe_to_retry=True, requires_ai_call=False, has_persisted_input=True)
        ai = Task(run_id=run.id, page_id=seeded['page'], stage='optimize', status='failed', safe_to_retry=True, requires_ai_call=True, has_persisted_input=True)
        s.add_all([local, ai]); await s.flush(); local_id, ai_id = local.id, ai.id
    async with db() as s:
        assert await resume_failed_tasks(s, seeded['run']) == [local_id]
        assert (await s.get(Run, seeded['run'])).status == 'action_required'
        assert (await s.get(Album, seeded['album'])).status == 'action_required'
        assert (await s.get(Task, ai_id)).status == 'failed'


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary',[
    'not_sent','rejected','accepted_or_unknown','received','running','unknown','missing_marker',
    'asset_owner','asset_deleted','page_removed','album_deleted','current_run','snapshot_sha',
    'ledger_mismatch','missing_ledger','existing_failed'])
async def test_deferred_ai_classification_requires_unsent_scoped_input(db,seeded,boundary):
    from sqlalchemy import select
    from backend.models import Page,MediaAsset,Attempt,User
    from backend.generation.completion import recompute_completion
    async with db() as s,s.begin():
        album=await s.get(Album,seeded['album']);album.status='action_required';album.active_run_id=seeded['run']
        run=await s.get(Run,seeded['run']);run.status='action_required'
        page=await s.get(Page,seeded['page'])
        asset=MediaAsset(owner_id=album.owner_id,album_id=album.id,page_id=page.id,role='normalized',
            storage_key=str(uuid4()),mime='image/webp',status='ready',sha256='a'*64,bytes=100,width=30,height=40)
        s.add(asset);await s.flush();page.normalized_asset_id=asset.id
        run.input_snapshot=[{'page_id':str(page.id),'normalized_asset_id':str(asset.id),'sha256':'a'*64,'position':1,'input_is_3_4':True}]
        task=await s.get(Task,seeded['task']);task.has_persisted_input=True;task.fence_version=7
        task.status='retry_wait';task.next_retry_at=seeded['now'];task.error_code=None
        if boundary in {'not_sent','rejected','accepted_or_unknown','received','ledger_mismatch'}:
            task.attempt_count=2 if boundary=='ledger_mismatch' else 1
            s.add(Attempt(task_id=task.id,attempt_no=1,fence_version=7,
                dispatch_state=boundary if boundary in {'not_sent','rejected','accepted_or_unknown'} else 'not_sent',
                status='received' if boundary=='received' else 'dispatching'))
        elif boundary=='running':task.status='running'
        elif boundary=='unknown':task.status='unknown'
        elif boundary=='missing_marker':task.has_persisted_input=False
        elif boundary=='asset_owner':
            other=User();s.add(other);await s.flush();asset.owner_id=other.id
        elif boundary=='asset_deleted':asset.deleted_at=seeded['now']
        elif boundary=='page_removed':page.removed_at=seeded['now']
        elif boundary=='album_deleted':album.deleted_at=seeded['now'];album.status='deleted'
        elif boundary=='current_run':album.active_run_id=None
        elif boundary=='snapshot_sha':asset.sha256='b'*64
        elif boundary=='missing_ledger':task.attempt_count=1
        elif boundary=='existing_failed':task.status='failed';task.safe_to_retry=False;task.error_code='AI_POLICY_BLOCKED'
        counters=(task.attempt_count,task.fence_version)
        original_snapshot=run.input_snapshot
        original_status=task.status
        await recompute_completion(s,album,run)
        await recompute_completion(s,album,run)
        if boundary in {'not_sent','rejected'}:
            assert (task.status,task.safe_to_retry,task.error_code)==('failed',True,'AI_TEMPORARY_FAILURE')
        else:
            assert task.status==original_status and not task.safe_to_retry
        assert (task.attempt_count,task.fence_version)==counters and run.input_snapshot==original_snapshot
        latest=await s.scalar(select(Attempt).where(Attempt.task_id==task.id))
        if latest:
            assert latest.fence_version==7 and latest.output_asset_id is None and latest.output_caption is None
