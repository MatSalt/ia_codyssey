"""Short PostgreSQL transactions; caller supplies an unused dedicated session.

Lock order for result/deletion-sensitive operations is album -> run -> task.
No adapter or filesystem call belongs inside these transactions.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID
from sqlalchemy import select, exists, and_, or_, func, Integer, cast, text
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession
from backend.models import Album, Page, Run, Task, MediaAsset


@dataclass(frozen=True)
class TaskClaim:
    task_id: UUID
    fence_version: int
    lease_until: datetime


STAGE_LIMITS = {'caption': (4, 'caption_concurrency'),
                'image_transform': (2, 'image_concurrency'), 'optimize': (1, 'media_concurrency')}


async def lock_claims(session):
    """Acquire only before album/run/task locks; release at transaction end."""
    await session.execute(text('SELECT pg_advisory_xact_lock(724091831)'))


async def claim_task(session: AsyncSession, now: datetime, lease_seconds: int, *, execution_mode=None, stage=None) -> TaskClaim | None:
    if lease_seconds <= 0:
        raise ValueError('lease_seconds must be positive')
    limits = STAGE_LIMITS
    if stage is not None and stage not in limits:
        raise ValueError('invalid stage')
    image = aliased(Task)
    running = aliased(Task)
    async with session.begin():
        # Only claims take this mutex, always BEFORE row locks. No I/O occurs
        # here. Concurrent claims see committed leases under READ COMMITTED.
        await lock_claims(session)
        counts = dict((await session.execute(select(Task.stage, func.count()).where(
            Task.status == 'running', Task.lease_until > now).group_by(Task.stage))).all())
        from backend.models import GoodsRevision
        goods_count=await session.scalar(select(func.count()).select_from(GoodsRevision).where(GoodsRevision.status=='running',GoodsRevision.lease_until>now))
        counts['image_transform']=counts.get('image_transform',0)+goods_count
        available = []
        for name, (cap, setting) in limits.items():
            if (stage is None or stage == name) and counts.get(name, 0) < cap:
                run_count = select(func.count()).where(
                    running.run_id == Task.run_id, running.stage == name,
                    running.status == 'running', running.lease_until > now).correlate(Task).scalar_subquery()
                available.append(and_(Task.stage == name, run_count < func.coalesce(
                    cast(Run.config_snapshot[setting].astext, Integer), cap)))
        if not available:
            return None
        query = (select(Task).join(Run, Task.run_id == Run.id).join(Album, Run.album_id == Album.id)
                 .join(Page, and_(Task.page_id == Page.id, Page.album_id == Album.id))
                 .where(or_(*available), Task.status.in_(['queued', 'retry_wait']),
                        or_(Task.next_retry_at.is_(None), Task.next_retry_at <= now),
                        Album.deleted_at.is_(None), Album.status != 'deleted', Page.removed_at.is_(None),
                        Run.status.in_(['queued', 'running', 'action_required']),
                        or_(Run.status != 'action_required', and_(Task.requires_ai_call.is_(False), Task.has_persisted_input.is_(True))),
                        or_(Task.stage != 'optimize', exists(select(image.id).where(image.run_id == Task.run_id, image.page_id == Task.page_id, image.stage == 'image_transform', image.status == 'succeeded'))))
                 .order_by(Task.id).with_for_update(of=Album, skip_locked=True).limit(1))
        if execution_mode is not None:
            query = query.where(Run.config_snapshot['execution_mode'].astext == execution_mode)
        # Lock parents explicitly in the same order as settlement/deletion.
        task = await session.scalar(query)
        if task is None:
            return None
        run = await session.scalar(select(Run).where(Run.id == task.run_id).with_for_update(skip_locked=True))
        if run is None:
            return None
        task = await session.scalar(select(Task).where(Task.id == task.id).with_for_update(skip_locked=True))
        if task is None:
            return None
        page = await session.scalar(select(Page).where(Page.id == task.page_id).with_for_update(skip_locked=True))
        if page is None:
            return None
        task.status = 'running'
        task.fence_version += 1
        task.lease_until = now + timedelta(seconds=lease_seconds)
        run = await session.get(Run, task.run_id)
        if run.status == 'queued':
            run.status = 'running'
            run.started_at = run.started_at or now
        return TaskClaim(task.id, task.fence_version, task.lease_until)


async def _locked_task(session, task_id):
    album_id = await session.scalar(select(Run.album_id).join(Task, Task.run_id == Run.id).where(Task.id == task_id))
    if album_id is None:
        return None
    album = await session.scalar(select(Album).where(Album.id == album_id).with_for_update())
    run_id = await session.scalar(select(Task.run_id).where(Task.id == task_id))
    run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
    task = await session.scalar(select(Task).where(Task.id == task_id).with_for_update())
    page = await session.scalar(select(Page).where(Page.id == task.page_id).with_for_update())
    return album, run, task, page


def _active(album, run, task, page, fence, now):
    return (page.album_id == album.id and album.deleted_at is None and album.status != 'deleted' and page.removed_at is None
            and run.status != 'cancelled' and task.status == 'running'
            and task.fence_version == fence and task.lease_until is not None and task.lease_until > now)


def mark_action_required(album, run):
    run.status = 'action_required'
    if album.status != 'action_required':
        album.status = 'action_required'
        album.version += 1


async def result_fields(session, rows, result):
    """Validate before assigning FK/text columns; the durable envelope stays intact."""
    album, run, task, page = rows
    caption = result.get('caption') if isinstance(result, dict) else None
    raw_asset = result.get('asset_id') if isinstance(result, dict) else None
    try:
        asset_id = UUID(str(raw_asset)) if raw_asset else None
    except (ValueError, TypeError, AttributeError):
        asset_id = None
    asset = await session.get(MediaAsset, asset_id) if asset_id else None
    # This ID is also used for cleanup: existence alone grants no authority.
    in_scope = (asset is not None and asset.owner_id == album.owner_id
                and asset.album_id == album.id and asset.page_id == page.id)
    asset_id = asset.id if in_scope else None
    if task.stage == 'caption':
        error = None if isinstance(caption, str) and caption.strip() else 'CAPTION_INVALID'
    else:
        error = None if (in_scope and asset.status == 'ready' and asset.deleted_at is None) else 'MEDIA_SAVE_FAILED'
    if run.config_snapshot.get('execution_mode') in {'local_fake','openai'}:
        import unicodedata
        from backend.storage.local import storage_key
        if task.stage == 'caption':
            if error is None and len(unicodedata.normalize('NFC',caption)) > run.config_snapshot.get('caption_max_chars',80):
                error='CAPTION_INVALID'
        elif error is None:
            role='transform_output' if task.stage=='image_transform' else 'result'
            if asset.role!=role or asset.mime!='image/webp' or not asset.sha256 or not asset.bytes:
                error='MEDIA_SAVE_FAILED'
            elif (asset.width is None or asset.height is None or asset.width<=0 or asset.height<=0
                  or asset.width*4!=asset.height*3):
                error='IMAGE_RATIO_INVALID'
            elif asset.storage_key!=storage_key(album.owner_id,album.id,page.id,role):
                error='MEDIA_SAVE_FAILED'
            if task.stage=='optimize' and error is None:
                from uuid import uuid5,NAMESPACE_URL
                from backend.generation.completion import ready_output
                key=storage_key(album.owner_id,album.id,page.id,'result_thumbnail')
                thumb=await session.get(MediaAsset,uuid5(NAMESPACE_URL,key))
                if not ready_output(thumb,album,page,'thumbnail') or thumb.storage_key!=key:
                    error='MEDIA_SAVE_FAILED'
    return caption if isinstance(caption, str) else None, asset_id, error


def fail_invalid_result(rows, attempt, error):
    album, run, task, page = rows
    task.status = 'failed'; task.lease_until = None
    task.error_code = error
    # Replaying this envelope cannot repair invalid output; no new paid request.
    task.safe_to_retry = False
    attempt.error_code = error
    mark_action_required(album, run)


async def settle_task(session: AsyncSession, task_id: UUID, fence: int, outcome: str, now: datetime) -> bool:
    if outcome not in {'succeeded', 'failed', 'unknown', 'retry_wait'}:
        raise ValueError('invalid settlement outcome')
    async with session.begin():
        rows = await _locked_task(session, task_id)
        if rows is None or not _active(*rows, fence, now):
            return False
        album, run, task, page = rows
        if outcome == 'succeeded':
            _,_,error=await result_fields(session,rows,{'caption':task.output_caption,'asset_id':task.output_asset_id})
            if error:
                return False
            if task.stage == 'caption' and (not isinstance(task.output_caption, str) or not task.output_caption.strip()):
                return False
            if task.stage != 'caption':
                asset = await session.get(MediaAsset, task.output_asset_id) if task.output_asset_id else None
                if (asset is None or asset.owner_id != album.owner_id or asset.album_id != album.id
                        or asset.page_id != page.id or asset.status != 'ready' or asset.deleted_at is not None):
                    return False
            # Link only verified persisted output. Recovery fills these from the attempt.
            if task.output_caption is not None and task.stage == 'caption':
                if page.ai_caption is None:
                    page.ai_caption = task.output_caption
                if page.caption_text is None and page.caption_edited_at is None:
                    page.caption_text = task.output_caption
                    page.version += 1; album.version += 1
            if task.output_asset_id is not None and task.stage == 'optimize':
                asset = await session.get(MediaAsset, task.output_asset_id)
                if (asset is None or asset.owner_id != album.owner_id or asset.album_id != album.id
                        or asset.page_id != page.id or asset.status != 'ready' or asset.deleted_at is not None):
                    return False
                changed=page.result_asset_id != asset.id
                page.result_asset_id = asset.id
                if run.config_snapshot.get('execution_mode') in {'local_fake','openai'}:
                    from uuid import uuid5,NAMESPACE_URL
                    from backend.storage.local import storage_key
                    thumb_id=uuid5(NAMESPACE_URL,storage_key(album.owner_id,album.id,page.id,'result_thumbnail'))
                    changed=changed or page.thumbnail_asset_id != thumb_id
                    page.thumbnail_asset_id=thumb_id
                if changed:
                    page.version += 1; album.version += 1
        task.status = outcome
        task.lease_until = None
        if outcome == 'succeeded':
            task.completion_kind = 'provider' if task.requires_ai_call else 'local'
            task.error_code = None
            from backend.generation.completion import recompute_completion
            await recompute_completion(session,album,run)
        if outcome in {'failed', 'unknown'}:
            mark_action_required(album, run)
        return True


async def reject_invalid_settlement(session, task_id, fence, now):
    """A false settle can be stale/deleted or invalid; only fail the active claim."""
    from backend.models import Attempt
    async with session.begin():
        rows = await _locked_task(session, task_id)
        if rows is None or not _active(*rows, fence, now):
            return
        task = rows[2]
        _, _, error = await result_fields(session, rows, {'caption': task.output_caption, 'asset_id': task.output_asset_id})
        if error:
            attempt = await session.scalar(select(Attempt).where(Attempt.task_id == task.id, Attempt.attempt_no == task.attempt_count))
            if attempt:
                fail_invalid_result(rows, attempt, error)
