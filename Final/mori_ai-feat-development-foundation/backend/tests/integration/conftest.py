import os
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy import text

# Report missing integration execution explicitly instead of hiding collection.
@pytest.fixture(autouse=True)
def require_workflow_database():
    if os.environ.get('MORI_WORKFLOW_TEST') != '1':
        pytest.skip('PostgreSQL integration requires make verify-db (MORI_WORKFLOW_TEST=1)')


@pytest_asyncio.fixture
async def db():
    from backend.database import session_factory
    from sqlalchemy.engine import make_url
    assert make_url(os.environ['DATABASE_URL']).database == 'mori_workflow_test', 'destructive tests require the dedicated temporary database'
    factory = session_factory()
    async with factory() as session:
        version = await session.scalar(text('SHOW server_version_num'))
        assert 170000 <= int(version) < 180000
        await session.execute(text('TRUNCATE users CASCADE'))
        await session.execute(text('TRUNCATE outbox_events, background_jobs'))
        # Financial records intentionally do not cascade from product data.
        # Only this guarded disposable test database resets validation spending.
        await session.execute(text('TRUNCATE ai_budget_entries, ai_budget_accounts'))
        await session.commit()
    yield factory
    await factory.kw['bind'].dispose()


@pytest_asyncio.fixture
async def seeded(db):
    from backend.models import User, Album, Page, Run, Task, MediaAsset, Upload
    now = datetime.now(timezone.utc)
    async with db() as s, s.begin():
        user = User(); s.add(user); await s.flush()
        album = Album(owner_id=user.id, status='processing'); s.add(album); await s.flush()
        page = Page(album_id=album.id); s.add(page); await s.flush()
        asset = MediaAsset(owner_id=user.id, album_id=album.id, page_id=page.id, role='source', storage_key=str(uuid4()), mime='image/png'); s.add(asset)
        run = Run(album_id=album.id); s.add(run); await s.flush()
        task = Task(run_id=run.id, page_id=page.id, stage='caption'); s.add(task)
        upload = Upload(album_id=album.id, page_id=page.id, asset_id=asset.id, batch_id=uuid4(), client_file_id=uuid4(), declared_bytes=10, expires_at=now+timedelta(seconds=30)); s.add(upload)
        await s.flush()
        return dict(album=album.id, page=page.id, run=run.id, task=task.id, upload=upload.id, now=now)
