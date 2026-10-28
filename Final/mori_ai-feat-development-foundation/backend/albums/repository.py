"""Album persistence. Callers own transactions; locks follow album → run → task."""
from sqlalchemy import select, tuple_
from backend.models import Album, User, Page, Run, Task, Upload, MediaAsset, IdempotencyRecord, Outbox


async def lock_owner(session, owner_id):
    # A real parent row serializes competing draft inserts before their key lookup.
    # No speculative album is committed and no unique-violation escapes PostgreSQL.
    return await session.scalar(select(User).where(User.id == owner_id, User.deleted_at.is_(None)).with_for_update())


async def find_record(session, owner_id, operation, key):
    return await session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.owner_id == owner_id,
        IdempotencyRecord.operation == operation, IdempotencyRecord.key == key))


async def find_album(session, owner_id, album_id, *, lock=False):
    query = select(Album).where(Album.id == album_id, Album.owner_id == owner_id,
                               Album.deleted_at.is_(None), Album.status != 'deleted')
    return await session.scalar(query.with_for_update() if lock else query)


async def insert_album(session, owner_id):
    album = Album(owner_id=owner_id, title='나의 사진첩', status='draft', version=1)
    session.add(album)
    await session.flush()
    return album


async def save_record(session, owner_id, operation, key, hashed, album_id, status, data):
    session.add(IdempotencyRecord(owner_id=owner_id, operation=operation, key=key,
        request_hash=hashed, resource_id=album_id, http_status=status, response_body=data))
    await session.flush()


async def list_albums(session, owner_id, cursor, limit):
    query = select(Album).where(Album.owner_id == owner_id, Album.deleted_at.is_(None), Album.status != 'deleted')
    if cursor:
        query = query.where(tuple_(Album.created_at, Album.id) < tuple_(*cursor))
    return (await session.scalars(query.order_by(Album.created_at.desc(), Album.id.desc()).limit(limit + 1))).all()


async def album_pages(session, album_id):
    return (await session.scalars(select(Page).where(Page.album_id == album_id, Page.removed_at.is_(None)).order_by(Page.position, Page.id))).all()


async def page_uploads(session, album_id):
    return (await session.scalars(select(Upload).where(Upload.album_id == album_id))).all()


async def ready_assets(session, album_id):
    return (await session.scalars(select(MediaAsset).join(Album, Album.id == MediaAsset.album_id)
        .join(Page, Page.id == MediaAsset.page_id).where(MediaAsset.album_id == album_id,
        MediaAsset.owner_id == Album.owner_id, Page.album_id == Album.id, Page.removed_at.is_(None),
        Album.deleted_at.is_(None), Album.status != 'deleted',
        MediaAsset.status == 'ready', MediaAsset.deleted_at.is_(None)))).all()


async def lock_runs_and_tasks(session, album_id):
    runs = (await session.scalars(select(Run).where(Run.album_id == album_id).order_by(Run.id).with_for_update())).all()
    tasks = (await session.scalars(select(Task).join(Run, Run.id == Task.run_id).where(Run.album_id == album_id)
                                 .order_by(Task.id).with_for_update(of=Task))).all()
    return runs, tasks


def cleanup_event(session, album_id):
    session.add(Outbox(event_type='album_cleanup', entity_id=album_id, payload={'album_id': str(album_id)}))
