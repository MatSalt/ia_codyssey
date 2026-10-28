"""Upload DB boundaries. Callers hold album lock before mutable child rows."""
from sqlalchemy import select
from backend.models import Album, Page, Upload, MediaAsset, Consent
from backend.albums.repository import find_album
from backend.http.errors import APIError


async def album(session,owner,album_id,*,lock=True):
    row=await find_album(session,owner,album_id,lock=lock)
    if row is None: raise APIError(404,'RESOURCE_NOT_FOUND')
    return row


def draft(row,expected=None):
    if expected is not None and row.version!=expected:
        raise APIError(409,'VERSION_CONFLICT',details={'resource_type':'album','resource_id':str(row.id),'current_version':row.version})
    if row.status!='draft': raise APIError(409,'STATE_CONFLICT')


async def upload(session,owner,album_id,upload_id,*,lock=True):
    parent=await album(session,owner,album_id,lock=lock)
    row=await session.scalar(select(Upload).where(Upload.id==upload_id,Upload.album_id==album_id))
    page=await session.get(Page,row.page_id) if row else None
    asset=await session.get(MediaAsset,row.asset_id) if row else None
    if (page is None or page.album_id!=album_id or page.removed_at is not None or asset is None
        or page.source_asset_id!=asset.id or asset.page_id!=page.id or asset.role!='source'
        or asset.owner_id!=owner or asset.album_id!=album_id
        or (asset.deleted_at is not None and row.status not in {'expired','rejected'}
            and not (row.status=='ready' and (row.validation_config or {}).get('source_lifetime')=='temporary'))):
        raise APIError(404,'RESOURCE_NOT_FOUND')
    return parent,row,page,asset


async def consent(session,owner,policy):
    return await session.scalar(select(Consent.id).where(Consent.user_id==owner,Consent.policy_version==policy,Consent.purpose=='photo_upload_and_ai_processing'))


async def visible_asset(session,owner,album_id,asset_id):
    parent=await album(session,owner,album_id,lock=False)
    asset=await session.get(MediaAsset,asset_id)
    page=await session.get(Page,asset.page_id) if asset else None
    if (asset is None or asset.owner_id!=owner or asset.album_id!=album_id or asset.status!='ready' or asset.deleted_at is not None
        or page is None or page.album_id!=album_id or page.removed_at is not None
        or asset.role not in {'normalized','thumbnail','result'}
        or asset.id!=getattr(page,asset.role+'_asset_id')
        or (asset.role=='normalized' and parent.status not in {'draft','processing','action_required'})):
        raise APIError(404,'RESOURCE_NOT_FOUND')
    return asset


async def upload_album_id(session,upload_id):
    return await session.scalar(select(Upload.album_id).where(Upload.id==upload_id))
