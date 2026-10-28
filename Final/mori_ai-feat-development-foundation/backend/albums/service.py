"""Bookshelf policies and public DTOs, independent of the HTTP boundary."""
import base64
import binascii
import json
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from backend.albums import repository as repo
from backend.http.errors import APIError
from backend.http.idempotency import replay

CREATE_OPERATION = 'POST /api/v1/albums'


def utc(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z') if value else None


def not_found():
    raise APIError(404, 'RESOURCE_NOT_FOUND')


def media_ref(asset):
    if asset is None or asset.width is None or asset.height is None:
        return None
    return {'asset_id': str(asset.id), 'mime': asset.mime, 'width': asset.width, 'height': asset.height}


def scoped_asset(assets,page,role,album):
    asset=assets.get(getattr(page,role+'_asset_id'))
    if (asset is None or asset.role!=role or asset.owner_id!=album.owner_id or asset.album_id!=album.id
        or asset.page_id!=page.id or page.removed_at is not None
        or (role=='normalized' and album.status not in {'draft','processing','action_required'})):
        return None
    return asset


async def access_entries(session,refs,owner):
    signing=session.info.get('media_signer')
    if signing is None: return []
    from datetime import timedelta
    expiry=datetime.now(timezone.utc).replace(microsecond=0)+timedelta(seconds=300)
    entries=[]
    for album_id,ref in refs:
        asset_id=ref['asset_id']
        from backend.uploads.repository import visible_asset
        from backend.storage.local import canonical_asset_keys
        asset=await visible_asset(session,owner,album_id,UUID(str(asset_id)))
        if asset.storage_key not in canonical_asset_keys(owner,album_id,asset.page_id,asset.role): not_found()
        path=f'/api/v1/private/albums/{album_id}/media/{asset_id}'
        entries.append({'asset_id':asset_id,'url':signing.read_url(asset.storage_key,path,asset_id,int(expiry.timestamp()),asset.mime),'expires_at':utc(expiry)})
    return entries


async def summary(session, album):
    pages = await repo.album_pages(session, album.id)
    assets = {a.id: a for a in await repo.ready_assets(session, album.id)}
    cover_page = pages[0] if pages else None
    cover = scoped_asset(assets, cover_page, 'thumbnail', album) if cover_page else None
    return {'id': str(album.id), 'title': album.title, 'status': album.status, 'version': album.version,
        'page_count': len(pages), 'cover': media_ref(cover), 'created_at': utc(album.created_at),
        'updated_at': utc(album.updated_at), 'published_at': utc(album.published_at)}


async def create_album(session, user_id, key, hashed):
    if await repo.lock_owner(session, user_id) is None:
        not_found()
    record = await repo.find_record(session, user_id, CREATE_OPERATION, key)
    if record:
        # Access checks precede even a hash conflict, so deleted resources never leak.
        if await repo.find_album(session, user_id, record.resource_id, lock=True) is None:
            not_found()
        return replay(record, hashed)
    album = await repo.insert_album(session, user_id)
    data = {'album': await summary(session, album)}
    await repo.save_record(session, user_id, CREATE_OPERATION, key, hashed, album.id, 201, data)
    return 201, data


def encode_cursor(album):
    raw = json.dumps([utc(album.created_at), str(album.id)], separators=(',', ':')).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def decode_cursor(value):
    if value is None:
        return None
    try:
        if not value or len(value) > 256:
            raise ValueError()
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        values = json.loads(raw)
        if not isinstance(values, list) or len(values) != 2 or not all(isinstance(v, str) for v in values):
            raise ValueError()
        timestamp = datetime.fromisoformat(values[0].replace('Z', '+00:00'))
        if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
            raise ValueError()
        return timestamp, UUID(values[1])
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError, OverflowError):
        raise APIError(422, 'VALIDATION_ERROR') from None


async def get_albums(session, user_id, cursor, limit):
    rows = await repo.list_albums(session, user_id, decode_cursor(cursor), limit)
    more = len(rows) > limit
    rows = rows[:limit]
    items=[await summary(session, album) for album in rows]
    refs=[(album.id,item['cover']) for album,item in zip(rows,items) if item['cover']]
    return {'items': items, 'next_cursor': encode_cursor(rows[-1]) if more else None,
            'media_access': await access_entries(session,refs,user_id)}


def page_dto(page,album,assets,upload=None):
    """The same public Page in detail and PATCH responses; no internal AI text."""
    return {'id':str(page.id),'position':page.position,'version':page.version,
        'upload_status':upload.status if upload else 'reserved',
        'source':media_ref(scoped_asset(assets,page,'normalized',album)),
        'result':media_ref(scoped_asset(assets,page,'result',album)),
        'thumbnail':media_ref(scoped_asset(assets,page,'thumbnail',album)),
        'caption_text':page.caption_text,'sort_date':page.sort_date,'sort_date_source':page.sort_date_source}


async def generation_mode(session, album_id):
    """Persisted provenance, independent of today's enabled executor."""
    from backend.models import Run
    run = await session.scalar(select(Run).where(Run.album_id == album_id)
        .order_by(Run.created_at.desc(), Run.id.desc()).limit(1))
    mode = run.config_snapshot.get('execution_mode') if run else None
    return mode if mode in {'local_fake', 'openai'} else None


async def get_album_detail(session, user_id, album_id):
    album = await repo.find_album(session, user_id, album_id)
    if album is None:
        not_found()
    assets = {a.id: a for a in await repo.ready_assets(session, album_id)}
    uploads = {u.page_id: u for u in await repo.page_uploads(session, album_id)}
    pages = []
    for p in await repo.album_pages(session, album_id):
        upload = uploads.get(p.id)
        pages.append(page_dto(p,album,assets,upload))
    refs=[(album_id,p['thumbnail'] or p['source']) for p in pages if p['thumbnail'] or p['source']]
    return {'detail': {'album': await summary(session, album), 'order_mode': album.order_mode,
        'pages': pages, 'generation_mode': await generation_mode(session, album_id), 'active_run_id': str(album.active_run_id) if album.active_run_id else None}, 'media_access': await access_entries(session,refs,user_id)}


async def delete_album(session, user_id, album_id, expected_version):
    album = await repo.find_album(session, user_id, album_id, lock=True)
    if album is None:
        not_found()
    if album.version != expected_version:
        raise APIError(409, 'VERSION_CONFLICT', '다른 변경이 반영되었습니다. 최신 내용을 확인해주세요.',
            details={'resource_type': 'album', 'resource_id': str(album_id), 'current_version': album.version})
    now = datetime.now(timezone.utc)
    runs, tasks = await repo.lock_runs_and_tasks(session, album_id)
    for run in runs:
        if run.status in {'queued', 'running', 'action_required'}:
            run.status = 'cancelled'
            run.finished_at = now
    for task in tasks:
        task.fence_version += 1
        task.lease_until = None
        if task.status not in {'succeeded', 'cancelled'}:
            task.status = 'cancelled'
    album.status = 'deleted'
    album.deleted_at = album.updated_at = now
    album.version += 1
    album.active_run_id = None
    repo.cleanup_event(session, album_id)
    await session.flush()
    return {'album_id': str(album_id), 'status': 'deleted'}
