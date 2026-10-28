"""v1.3: unknown permits persisted local failed work only."""
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID
from sqlalchemy import select
from backend.models import Album, Run, Task, Page, MediaAsset, Attempt


@dataclass(frozen=True)
class ResumeTask:
    id: UUID
    status: str
    safe_to_retry: bool
    requires_ai_call: bool
    has_persisted_input: bool


def eligible_resume_tasks(tasks: Sequence[ResumeTask], has_unknown: bool) -> list[UUID]:
    return [t.id for t in tasks if t.status == 'failed' and t.safe_to_retry
            and (not has_unknown or (not t.requires_ai_call and t.has_persisted_input))]


async def classify_deferred_ai(session, album, run, tasks):
    """Caller holds Album -> Run -> all Task locks in the settlement transaction.

    A resolved unknown must not strand never-sent work, or automatically send it.
    Expose only proven-unsent, persisted inputs through the existing failed resume.
    Attempts, fences, outputs and immutable run snapshots remain untouched.
    """
    if (album.deleted_at is not None or album.status != 'action_required'
            or run.album_id != album.id or album.active_run_id != run.id
            or run.status != 'action_required' or any(t.status == 'unknown' for t in tasks)):
        return
    inputs = {item['page_id']: item for item in run.input_snapshot}
    for task in tasks:
        if (task.run_id != run.id or task.status not in {'queued', 'retry_wait'}
                or not task.requires_ai_call or not task.has_persisted_input
                or task.output_asset_id is not None or task.output_caption is not None):
            continue
        page = await session.get(Page, task.page_id)
        item = inputs.get(str(task.page_id))
        if page is None or page.album_id != album.id or page.removed_at is not None or item is None:
            continue
        asset = await session.get(MediaAsset, page.normalized_asset_id) if page.normalized_asset_id else None
        if (asset is None or str(asset.id) != item['normalized_asset_id']
                or asset.owner_id != album.owner_id or asset.album_id != album.id or asset.page_id != page.id
                or asset.role != 'normalized' or asset.status != 'ready' or asset.deleted_at is not None
                or asset.mime != 'image/webp' or not asset.sha256 or asset.sha256 != item['sha256']):
            continue
        latest = await session.scalar(select(Attempt).where(Attempt.task_id == task.id)
            .order_by(Attempt.attempt_no.desc()).limit(1).with_for_update())
        if latest is None:
            if task.attempt_count != 0:
                continue
        elif (latest.attempt_no != task.attempt_count or latest.dispatch_state not in {'not_sent', 'rejected'}
                or latest.status in {'unknown', 'received'}
                or latest.output_asset_id is not None or latest.output_caption is not None):
            continue
        task.status = 'failed'
        task.safe_to_retry = True
        task.error_code = 'AI_TEMPORARY_FAILURE'


async def resume_failed_tasks(session, run_id):
    # HTTP layer must check ownership/consent/version/idempotency/budget before this call.
    async with session.begin():
        album_id = await session.scalar(select(Run.album_id).where(Run.id == run_id))
        if album_id is None:
            return []
        album = await session.scalar(select(Album).where(Album.id == album_id).with_for_update())
        run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if album.deleted_at is not None or album.status == 'deleted' or run.status != 'action_required':
            return []
        tasks = (await session.scalars(select(Task).where(Task.run_id == run_id).order_by(Task.id).with_for_update())).all()
        return resume_locked_tasks(album, run, tasks)


def resume_locked_tasks(album, run, tasks):
    """Caller already holds Album -> Run -> Task locks and owns its transaction."""
    if album.deleted_at is not None or album.status == 'deleted' or run.status != 'action_required':
        return []
    unknown = any(t.status == 'unknown' for t in tasks)
    eligible = eligible_resume_tasks(tasks, unknown)
    for task in tasks:
        if task.id in eligible:
            task.status = 'queued'
            task.next_retry_at = None
            task.error_code = None
    if eligible and not unknown:
        run.status = 'queued'
        album.status = 'processing'
        album.version += 1
    return eligible
