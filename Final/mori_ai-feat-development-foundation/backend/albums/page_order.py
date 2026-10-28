"""Album-locked collision-free active page ordering and EXIF date policy."""
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select
from backend.models import Page, Upload


def sort_date(raw,last_modified,reserved):
    if raw:
        try:
            value=datetime.strptime(raw,'%Y:%m:%d %H:%M:%S')
            return value.isoformat(timespec='seconds'),'exif'
        except (ValueError,TypeError):
            pass
    return (last_modified or reserved).astimezone(ZoneInfo('Asia/Seoul')).replace(tzinfo=None).isoformat(timespec='seconds'), 'file_modified' if last_modified else 'reserved_at'


async def active_pages(session,album_id):
    return list((await session.scalars(select(Page).where(Page.album_id==album_id,Page.removed_at.is_(None)).order_by(Page.position))).all())


def bump_version(session, row):
    """One public revision per changed row in the caller's transaction, across flushes."""
    transaction = session.get_transaction()
    state = session.info.get('public_versions')
    if state is None or state[0] is not transaction:
        state = (transaction, set())
        session.info['public_versions'] = state
    identity = (type(row), row.id)
    if identity not in state[1]:
        row.version += 1
        state[1].add(identity)


async def reorder(session,album,pages):
    changed = [page for index, page in enumerate(pages, 1) if page.position != index]
    cover = pages[0].id if pages else None
    cover_changed = album.cover_page_id != cover
    if not changed:
        album.cover_page_id = cover
        return cover_changed
    # All rows temporarily negative in one flush before final positive positions.
    for index,page in enumerate(pages,1): page.position=-index
    await session.flush()
    for index,page in enumerate(pages,1): page.position=index
    album.cover_page_id=cover
    for page in changed:
        bump_version(session, page)
    await session.flush()
    return True


async def finish_batch(session,album,batch_id):
    uploads=list((await session.scalars(select(Upload).join(Page,Page.id==Upload.page_id).where(Upload.batch_id==batch_id,Page.removed_at.is_(None)))).all())
    if album.order_mode!='date' or any(u.status not in {'ready','rejected','expired'} for u in uploads): return False
    pages=await active_pages(session,album.id)
    states={u.page_id:u.status for u in (await session.scalars(select(Upload).where(Upload.album_id==album.id))).all()}
    pages.sort(key=lambda p:(0,p.sort_date or '',p.selection_index) if states.get(p.id)=='ready' else (1,'',p.selection_index))
    return await reorder(session,album,pages)
