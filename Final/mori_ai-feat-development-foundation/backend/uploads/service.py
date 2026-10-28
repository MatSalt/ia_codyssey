"""Atomic reservation, immutable completion, and edit policies."""
import asyncio
import hashlib
import re
from datetime import datetime, timezone, timedelta
from pathlib import PurePath
from uuid import uuid4
from sqlalchemy import select
from backend.models import Upload, Page, MediaAsset
from backend.uploads import repository as repo
from backend.albums import repository as albums
from backend.albums.page_order import active_pages, reorder, finish_batch, sort_date, bump_version
from backend.albums.service import utc, get_album_detail
from backend.http.errors import APIError
from backend.http.idempotency import replay
from backend.worker.jobs import enqueue_job
from backend.storage.local import storage_key, canonical_asset_keys

MIMES={'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.webp':'image/webp','.heic':'image/heic','.heif':'image/heif'}


def now(): return datetime.now(timezone.utc)


def touch(session, album):
    bump_version(session, album)
    album.updated_at=now()


def config(settings):
    return {'NORMALIZATION_VERSION':2, **{key.upper():getattr(settings,key) for key in ('normalized_webp_lossless','normalized_webp_quality','normalized_max_edge','normalized_max_bytes','thumbnail_webp_quality','thumbnail_max_edge','result_webp_quality')}}


async def reserve(session,owner,album_id,body,key,hashed,settings,signer,csrf):
    parent=await repo.album(session,owner,album_id)
    operation=f'POST /api/v1/albums/{album_id}/uploads'
    record=await albums.find_record(session,owner,operation,key)
    if record: return replay(record,hashed)
    if not await repo.consent(session,owner,settings.consent_policy_version): raise APIError(403,'CONSENT_REQUIRED')
    repo.draft(parent,body.expected_version)
    pages=await active_pages(session,album_id)
    if len(pages)+len(body.files)>50: raise APIError(422,'PHOTO_COUNT_EXCEEDED')
    uploads=list((await session.scalars(select(Upload).join(Page,Page.id==Upload.page_id).where(Upload.album_id==album_id,Page.removed_at.is_(None)))).all())
    stamp=now()
    for u in uploads:
        if u.status=='reserved' and stamp>=u.expires_at:
            u.status='expired'
            bump_version(session, await session.get(Page, u.page_id))
    await session.flush()
    for batch in {u.batch_id for u in uploads if u.status=='expired'}:
        await finish_batch(session,parent,batch)
    occupied=sum(u.declared_bytes for u in uploads if u.status in {'reserved','validating','ready'})
    if any(f.bytes>20971520 for f in body.files): raise APIError(413,'FILE_TOO_LARGE')
    if occupied+sum(f.bytes for f in body.files)>314572800: raise APIError(413,'ALBUM_BYTES_EXCEEDED')
    if len({f.client_file_id for f in body.files})!=len(body.files): raise APIError(422,'VALIDATION_ERROR')
    for f in body.files:
        if PurePath(f.filename).suffix.lower() not in MIMES: raise APIError(422,'UNSUPPORTED_MEDIA')
        if f.preprocessing is not None and (PurePath(f.filename).suffix.lower()!='.webp' or f.mime not in {None,'image/webp'}):
            raise APIError(422,'VALIDATION_ERROR')
    batch=uuid4(); expiry=stamp+timedelta(seconds=900); result=[]
    for offset,f in enumerate(body.files,1):
        page=Page(id=uuid4(),album_id=album_id,position=len(pages)+offset,selection_index=parent.next_selection_index)
        parent.next_selection_index+=1
        page.sort_date,page.sort_date_source=sort_date(None,f.file_last_modified_at,stamp)
        session.add(page); await session.flush()
        mime=MIMES[PurePath(f.filename).suffix.lower()]
        asset=MediaAsset(id=uuid4(),owner_id=owner,album_id=album_id,page_id=page.id,role='source',storage_key=storage_key(owner,album_id,page.id,'source'),mime=mime,status='pending')
        session.add(asset); await session.flush(); page.source_asset_id=asset.id
        u=Upload(id=uuid4(),album_id=album_id,page_id=page.id,asset_id=asset.id,batch_id=batch,client_file_id=f.client_file_id,declared_bytes=f.bytes,file_last_modified_at=f.file_last_modified_at,expires_at=expiry,validation_config={'version':1,'media':config(settings),'upload_mime':mime,'storage_mode':signer.mode,'source_lifetime':'temporary',
            **({'preprocessing':f.preprocessing.model_dump()} if f.preprocessing is not None else {})},created_at=stamp)
        session.add(u)
        path=f'/api/v1/private/uploads/{u.id}'
        upload_url,required_headers=signer.upload_url(asset.storage_key,path,u.id,int(expiry.timestamp()),mime,f.bytes)
        result.append({'client_file_id':str(f.client_file_id),'upload_id':str(u.id),'page_id':str(page.id),'asset_id':str(asset.id),'status':'reserved','method':'PUT',
                       'upload_url':upload_url,'required_headers':required_headers,'expires_at':utc(expiry)})
    if not pages: parent.cover_page_id=page.id if len(body.files)==1 else None
    # Cover always follows current first page, including reserved/failed pages.
    await session.flush()
    parent.cover_page_id=(await active_pages(session,album_id))[0].id
    touch(session, parent)
    data={'batch_id':str(batch),'album_version':parent.version,'uploads':result}
    await albums.save_record(session,owner,operation,key,hashed,album_id,201,data)
    return 201,data


def view(parent,u):
    return {'upload_id':str(u.id),'page_id':str(u.page_id),'status':u.status,'error_code':u.error_code,'album_version':parent.version}


async def expire(session,parent,u):
    if u.status=='reserved' and now()>=u.expires_at:
        u.status='expired'
        bump_version(session, await session.get(Page, u.page_id))
        touch(session, parent)
        await finish_batch(session,parent,u.batch_id)


async def remove_page(session,owner,album_id,page_id,expected):
    parent=await repo.album(session,owner,album_id)
    repo.draft(parent,expected)
    page=await session.get(Page,page_id)
    if page is None or page.album_id!=album_id or page.removed_at is not None: raise APIError(404,'RESOURCE_NOT_FOUND')
    page.removed_at=now()
    bump_version(session, page)
    assets=(await session.scalars(select(MediaAsset).where(MediaAsset.page_id==page_id,MediaAsset.album_id==album_id,MediaAsset.owner_id==owner))).all()
    for asset in assets:
        await enqueue_job(session,'cleanup_asset',asset.id)
    upload = await session.scalar(select(Upload).where(Upload.page_id == page_id, Upload.album_id == album_id))
    await session.flush()
    # Removal can make the remaining active batch terminal without another worker result.
    if upload is None or not await finish_batch(session, parent, upload.batch_id):
        await reorder(session, parent, await active_pages(session, album_id))
    touch(session, parent)
    return await get_album_detail(session,owner,album_id)


async def order(session,owner,album_id,body):
    parent=await repo.album(session,owner,album_id); repo.draft(parent,body.expected_version)
    pages=await active_pages(session,album_id); by_id={p.id:p for p in pages}
    if len(body.page_ids)!=len(pages) or set(body.page_ids)!=set(by_id): raise APIError(422,'VALIDATION_ERROR')
    changed = await reorder(session,parent,[by_id[p] for p in body.page_ids])
    if parent.order_mode != 'manual':
        parent.order_mode = 'manual'
        changed = True
    if changed:
        touch(session, parent)
    return await get_album_detail(session,owner,album_id)


async def put_metadata(session,owner,upload_id):
    album_id=await repo.upload_album_id(session,upload_id)
    parent,u,page,asset=await repo.upload(session,owner,album_id,upload_id)
    repo.draft(parent)
    if u.status not in {'reserved','validating','ready'} or (u.status=='ready' and (u.validation_config or {}).get('source_lifetime')=='temporary'):
        raise APIError(409,'STATE_CONFLICT')
    upload_mime=(u.validation_config or {}).get('upload_mime',asset.mime)
    return album_id,asset.storage_key,upload_mime,u.declared_bytes,u.expires_at


async def accept_put(session,owner,album_id,upload_id):
    parent,u,page,asset=await repo.upload(session,owner,album_id,upload_id)
    if (u.status not in {'reserved','validating','ready'}
        or (u.status=='ready' and (u.validation_config or {}).get('source_lifetime')=='temporary')
        or (u.status=='reserved' and (now()>=u.expires_at or parent.status!='draft'))):
        raise APIError(409,'STATE_CONFLICT')


def check_complete_hash(store,asset,expected_sha256):
    if getattr(store,'mode','local')!='r2': return
    if not isinstance(expected_sha256,str) or re.fullmatch('[0-9a-f]{64}',expected_sha256) is None:
        raise APIError(422,'VALIDATION_ERROR')
    if asset.sha256 is not None and asset.sha256!=expected_sha256:
        raise APIError(409,'STATE_CONFLICT')


async def complete_upload(sessions,store,owner,album_id,upload_id,expected_sha256=None):
    async with sessions() as s,s.begin():
        parent,u,page,asset=await repo.upload(s,owner,album_id,upload_id)
        await expire(s,parent,u)
        if u.status=='expired': return 200,view(parent,u)
        check_complete_hash(store,asset,expected_sha256)
        if u.status!='reserved': return (202 if u.status=='validating' else 200),view(parent,u)
        repo.draft(parent); key=asset.storage_key
        if key not in canonical_asset_keys(owner,album_id,page.id,'source'): raise APIError(404,'RESOURCE_NOT_FOUND')
    # PUT has durably finalized a no-overwrite object. File I/O never holds a DB lock.
    try:
        from backend.telemetry import span
        with span('upload.confirm_input', storage_mode=getattr(store,'mode','local')):
            if getattr(store,'mode','local')=='r2':
                data=await asyncio.to_thread(store.read_bytes,key)
                size=len(data); checksum=hashlib.sha256(data).hexdigest()
                del data
            else:
                size=await asyncio.to_thread(lambda:store.stat(key).st_size)
                checksum=await asyncio.to_thread(store.checksum,key)
    except FileNotFoundError: raise APIError(422,'UPLOAD_NOT_READY') from None
    except ValueError: raise APIError(422,'VALIDATION_ERROR') from None
    except Exception as exc:
        from backend.storage.r2 import StorageUnavailable
        if isinstance(exc,StorageUnavailable):
            raise APIError(503,'TEMPORARILY_UNAVAILABLE',retryable=True) from None
        raise
    async with sessions() as s,s.begin():
        parent,u,page,asset=await repo.upload(s,owner,album_id,upload_id)
        await expire(s,parent,u)
        if u.status=='expired': return 200,view(parent,u)
        check_complete_hash(store,asset,expected_sha256)
        if u.status=='reserved':
            repo.draft(parent)
            if size!=u.declared_bytes or size>20971520: raise APIError(422,'VALIDATION_ERROR')
            if getattr(store,'mode','local')=='r2' and checksum!=expected_sha256: raise APIError(409,'STATE_CONFLICT')
            asset.bytes=size; asset.sha256=checksum
            u.status='validating'; await enqueue_job(s,'validate_upload',u.id)
            bump_version(s, page)
            touch(s, parent)
        return (202 if u.status=='validating' else 200),view(parent,u)


async def upload_status(session,owner,album_id,upload_id):
    parent,u,page,asset=await repo.upload(session,owner,album_id,upload_id)
    await expire(session,parent,u)
    return view(parent,u)


async def media_access(session,owner,album_id,asset_ids,signing):
    expiry=now().replace(microsecond=0)+timedelta(seconds=300)
    entries=[]
    await repo.album(session,owner,album_id,lock=False)
    for asset_id in asset_ids:
        asset=await repo.visible_asset(session,owner,album_id,asset_id)
        if asset.storage_key not in canonical_asset_keys(owner,album_id,asset.page_id,asset.role):
            raise APIError(404,'RESOURCE_NOT_FOUND')
        path=f'/api/v1/private/albums/{album_id}/media/{asset_id}'
        entries.append({'asset_id':str(asset_id),'url':signing.read_url(asset.storage_key,path,asset_id,int(expiry.timestamp()),asset.mime),'expires_at':utc(expiry)})
    return {'media_access':entries}
