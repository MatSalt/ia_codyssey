import asyncio
from datetime import timedelta
import pytest
from sqlalchemy import select, func, text
from backend.models import Upload, Job
pytestmark = pytest.mark.asyncio


async def test_complete_and_validation_job_are_atomic(db, seeded):
    from backend.worker.jobs import reserve_upload_validation
    async with db() as observer, db() as writer:
        # A database fault between state update and job write must roll back both.
        async with observer.begin():
            await observer.execute(text("ALTER TABLE background_jobs ADD CONSTRAINT reject_validate CHECK (kind != 'validate_upload')"))
        with pytest.raises(Exception):
            await reserve_upload_validation(writer, seeded['upload'], seeded['now'])
        await writer.rollback()
        assert (await observer.get(Upload, seeded['upload'])).status == 'reserved'
        assert await observer.scalar(select(func.count()).select_from(Job)) == 0
        await observer.rollback()
        async with observer.begin():
            await observer.execute(text('ALTER TABLE background_jobs DROP CONSTRAINT reject_validate'))
        assert await reserve_upload_validation(writer, seeded['upload'], seeded['now']) == 'validating'
        assert await observer.scalar(select(func.count()).select_from(Job)) == 1
        assert (await observer.get(Upload, seeded['upload'], populate_existing=True)).status == 'validating'


async def test_duplicate_complete_has_one_job(db, seeded):
    from backend.worker.jobs import reserve_upload_validation
    async with db() as a, db() as b:
        assert await asyncio.gather(reserve_upload_validation(a, seeded['upload'], seeded['now']), reserve_upload_validation(b, seeded['upload'], seeded['now'])) == ['validating', 'validating']
    async with db() as s:
        jobs = (await s.scalars(select(Job))).all()
        assert len(jobs) == 1
        job_id = jobs[0].id
        jobs[0].status = 'succeeded'; await s.commit()
        await reserve_upload_validation(s, seeded['upload'], seeded['now'])
        assert (await s.get(Job, job_id)).status == 'succeeded'


async def test_complete_at_deadline_expires(db, seeded):
    from backend.worker.jobs import reserve_upload_validation
    async with db() as s:
        assert await reserve_upload_validation(s, seeded['upload'], seeded['now']+timedelta(seconds=30)) == 'expired'
        assert await s.scalar(select(func.count()).select_from(Job)) == 0


async def test_validating_survives_put_expiry(db, seeded):
    from backend.worker.jobs import reserve_upload_validation
    async with db() as s:
        assert await reserve_upload_validation(s, seeded['upload'], seeded['now']) == 'validating'
        assert await reserve_upload_validation(s, seeded['upload'], seeded['now']+timedelta(days=2)) == 'validating'
        assert await s.scalar(select(func.count()).select_from(Job)) == 1
