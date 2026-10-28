"""Owner-only caption edits and publish. Caller owns the transaction."""
from datetime import datetime,timezone
import unicodedata
from sqlalchemy import select
from backend.models import Page
from backend.albums import repository as repo
from backend.albums.service import not_found,summary,page_dto
from backend.http.errors import APIError
from backend.http.schemas import CLIENT_CONFIG


async def owned_album(session,owner_id,album_id):
    album=await repo.find_album(session,owner_id,album_id,lock=True)
    if album is None:not_found()
    return album


def require_version(resource,expected_version,kind):
    if resource.version!=expected_version:
        raise APIError(409,'VERSION_CONFLICT',details={'resource_type':kind,'resource_id':str(resource.id),'current_version':resource.version})


async def save_caption(session,owner_id,album_id,page_id,expected_version,caption_text):
    album=await owned_album(session,owner_id,album_id)
    page=await session.scalar(select(Page).where(Page.id==page_id,Page.album_id==album_id,Page.removed_at.is_(None)).with_for_update())
    if page is None:not_found()
    if album.status not in {'review_ready','published'}:raise APIError(409,'STATE_CONFLICT')
    require_version(page,expected_version,'page')
    if not isinstance(caption_text,str):raise APIError(422,'VALIDATION_ERROR')
    normalized=unicodedata.normalize('NFC',caption_text)
    if '\x00' in normalized or any(0xD800<=ord(char)<=0xDFFF for char in normalized):
        raise APIError(422,'VALIDATION_ERROR')
    if len(normalized)>CLIENT_CONFIG['caption_max_chars']:
        raise APIError(422,'CAPTION_TOO_LONG')
    if page.caption_text!=normalized:
        stamp=datetime.now(timezone.utc)
        page.caption_text=normalized;page.caption_edited_at=stamp;page.version+=1
        album.version+=1;album.updated_at=stamp
    assets={a.id:a for a in await repo.ready_assets(session,album_id)}
    uploads={u.page_id:u for u in await repo.page_uploads(session,album_id)}
    return {'page':page_dto(page,album,assets,uploads.get(page.id)),'album_version':album.version}


async def publish_album(session,owner_id,album_id,expected_version):
    album=await owned_album(session,owner_id,album_id)
    require_version(album,expected_version,'album')
    if album.status not in {'review_ready','published'}:raise APIError(409,'STATE_CONFLICT')
    from backend.albums.viewer import ready_pages
    await ready_pages(session,album)
    if album.status=='review_ready':
        stamp=datetime.now(timezone.utc)
        album.status='published';album.published_at=album.updated_at=stamp;album.version+=1
    return {'album':await summary(session,album)}
