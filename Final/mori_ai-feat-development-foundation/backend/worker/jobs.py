"""Non-generation jobs and idempotent DB outbox dispatch."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID
from sqlalchemy import select, or_
from sqlalchemy.dialects.postgresql import insert
from backend.models import Upload, Job, Outbox, Task, Album, Page


async def enqueue_job(session, kind, target_id):
    statement=insert(Job).values(kind=kind,target_id=target_id)
    if kind in {'cleanup_album','cleanup_asset'}:
        # A previous live-reference no-op must not suppress a later real deletion.
        statement=statement.on_conflict_do_update(index_elements=['kind','target_id'],
            set_={'status':'queued','finished_at':None,'next_retry_at':None},
            where=Job.status.in_(['succeeded','failed','cancelled']))
    else:
        statement=statement.on_conflict_do_nothing(index_elements=['kind','target_id'])
    await session.execute(statement)


async def reserve_upload_validation(session, upload_id: UUID, now: datetime) -> str:
    async with session.begin():
        # Same parent lock as deletion. No URL/file operation inside this boundary.
        album_id = await session.scalar(select(Upload.album_id).where(Upload.id == upload_id))
        if album_id is None:
            raise LookupError('upload not found')
        album = await session.scalar(select(Album).where(Album.id == album_id).with_for_update())
        upload = await session.scalar(select(Upload).where(Upload.id == upload_id).with_for_update())
        page = await session.get(Page, upload.page_id)
        if album.deleted_at is not None or album.status == 'deleted' or page.removed_at is not None:
            raise LookupError('upload not found')
        if upload.status != 'reserved':
            return upload.status
        if now >= upload.expires_at:
            upload.status = 'expired'
        else:
            upload.status = 'validating'
            await enqueue_job(session, 'validate_upload', upload.id)
        return upload.status


async def dispatch_outbox(session, now: datetime, limit: int = 100) -> int:
    async with session.begin():
        events = (await session.scalars(select(Outbox).where(Outbox.published_at.is_(None)).order_by(Outbox.created_at, Outbox.id).with_for_update(skip_locked=True).limit(limit))).all()
        handled = 0
        for event in events:
            if event.event_type == 'album_cleanup':
                await enqueue_job(session, 'cleanup_album', event.entity_id)
            elif event.event_type == 'task_ready':
                if await session.get(Task, event.entity_id) is None:
                    continue
            else:
                continue
            event.published_at = now
            handled += 1
        return handled


@dataclass(frozen=True)
class JobClaim:
    job_id: UUID
    kind: str
    target_id: UUID
    fence_version: int
    lease_until: datetime


async def claim_job(session, now, lease_seconds=90, kinds=()):
    if not kinds:
        return None
    async with session.begin():
        job = await session.scalar(select(Job).where(Job.kind.in_(kinds), Job.status.in_(['queued', 'retry_wait']), or_(Job.next_retry_at.is_(None), Job.next_retry_at <= now)).order_by(Job.created_at, Job.id).with_for_update(skip_locked=True).limit(1))
        if job is None:
            return None
        job.status = 'running'; job.fence_version += 1; job.attempt_count += 1
        job.lease_until = now + timedelta(seconds=lease_seconds)
        return JobClaim(job.id, job.kind, job.target_id, job.fence_version, job.lease_until)


async def recover_jobs(session, now):
    # Handlers must verify preserved input/checksum/config and use deterministic keys.
    # No handler is installed until integration; this scanner never claims to validate files.
    async with session.begin():
        jobs = (await session.scalars(select(Job).where(Job.status == 'running', Job.lease_until <= now).with_for_update(skip_locked=True))).all()
        for job in jobs:
            job.status = 'queued'; job.fence_version += 1; job.lease_until = None
        return len(jobs)


async def finish_job(session, claim: JobClaim, now: datetime, outcome='succeeded') -> bool:
    if outcome not in {'succeeded', 'failed', 'retry_wait', 'cancelled'}:
        raise ValueError('invalid job outcome')
    async with session.begin():
        # Validation result acceptance serializes with album deletion too.
        upload = None
        if claim.kind == 'validate_upload':
            album_id = await session.scalar(select(Upload.album_id).where(Upload.id == claim.target_id))
            album = await session.scalar(select(Album).where(Album.id == album_id).with_for_update()) if album_id else None
            upload = await session.get(Upload, claim.target_id)
            page = await session.get(Page, upload.page_id) if upload else None
            if album is None or album.deleted_at is not None or album.status == 'deleted' or page is None or page.removed_at is not None:
                return False
        job = await session.scalar(select(Job).where(Job.id == claim.job_id).with_for_update())
        if job is None or job.status != 'running' or job.fence_version != claim.fence_version or job.lease_until is None or job.lease_until <= now:
            return False
        job.status = outcome; job.lease_until = None
        if outcome in {'succeeded', 'failed', 'cancelled'}:
            job.finished_at = now
        return True
