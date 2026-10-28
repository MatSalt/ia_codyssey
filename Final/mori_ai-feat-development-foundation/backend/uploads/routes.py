"""Authenticated private local upload and media HTTP boundaries."""
import asyncio
from datetime import datetime, timezone, timedelta
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field, StrictInt, field_validator
from backend.http.schemas import StrictBody
from backend.http.security import AuthContext, require_user, require_csrf, csrf_token, COOKIE_NAME
from backend.http.errors import APIError, envelope
from backend.http.idempotency import require_key, request_hash
from backend.albums.routes import validate_query
from backend.uploads import service, repository as repo
from backend.uploads.preprocessing import PreprocessingBody

router=APIRouter(prefix='/api/v1')


class FileBody(StrictBody):
    client_file_id: UUID
    filename: str=Field(min_length=1,max_length=1024)
    mime: str|None=Field(default=None,max_length=100)
    bytes: StrictInt=Field(ge=1)
    file_last_modified_at: datetime|None=None
    preprocessing: PreprocessingBody|None=None

    @field_validator('file_last_modified_at')
    @classmethod
    def utc_date(cls,v):
        if v is not None and (v.tzinfo is None or v.utcoffset().total_seconds()!=0): raise ValueError('UTC required')
        return v


class ReservationBody(StrictBody):
    expected_version: StrictInt=Field(ge=1)
    files: list[FileBody]=Field(min_length=1,max_length=50)


class OrderBody(StrictBody):
    expected_version: StrictInt=Field(ge=1)
    page_ids: list[UUID]=Field(max_length=50)


class CompleteBody(StrictBody):
    sha256: str|None=Field(default=None,pattern=r'^[0-9a-f]{64}$')


class AccessBody(StrictBody):
    asset_ids: list[UUID]=Field(max_length=150)


def storage(request): return request.app.state.media_storage

def signer(request): return request.app.state.media_signer


async def private_user(request: Request):
    if getattr(storage(request),'mode','local')=='r2': raise APIError(404,'RESOURCE_NOT_FOUND')
    try:
        return await require_user(request)
    except APIError as exc:
        if exc.status == 401:
            raise APIError(404, 'RESOURCE_NOT_FOUND') from None
        raise


@router.post('/albums/{album_id}/uploads')
async def reserve(request:Request,album_id:UUID,body:ReservationBody,context:AuthContext=Depends(require_user),idempotency_key:str|None=Header(default=None)):
    require_csrf(request,context); validate_query(request,())
    identity=body.model_dump(mode='json')
    # Adding an optional field must not invalidate reservations made by older clients.
    for entry in identity['files']:
        if entry['preprocessing'] is None:
            del entry['preprocessing']
    async with request.app.state.session_factory() as s,s.begin():
        status,data=await service.reserve(s,context.user_id,album_id,body,require_key(idempotency_key),request_hash(identity),request.app.state.settings,signer(request),csrf_token(request.cookies[COOKIE_NAME]))
    return JSONResponse(envelope(request,data),status_code=status)


@router.put('/private/uploads/{upload_id}',status_code=204)
async def put(request:Request,upload_id:UUID,expires:int,signature:str,context:AuthContext=Depends(private_user)):
    validate_query(request,('expires','signature'))
    sessions=request.app.state.session_factory
    async with sessions() as s,s.begin():
        album_id,key,mime,declared,deadline=await service.put_metadata(s,context.user_id,upload_id)
        if (not signer(request).verify('PUT',request.url.path,upload_id,expires,mime,signature,service.now().timestamp())
            or expires!=int(deadline.timestamp())): raise APIError(404,'RESOURCE_NOT_FOUND')
        require_csrf(request,context)
        if request.headers.get('content-type')!=mime: raise APIError(422,'VALIDATION_ERROR')
    store=storage(request)
    try:
        created=await store.put_stream(key,request.stream(),declared)
    except FileExistsError: raise APIError(409,'STATE_CONFLICT') from None
    except ValueError: raise APIError(422,'VALIDATION_ERROR') from None
    # A deletion or expiration during streaming cannot resurrect the upload.
    try:
        async with sessions() as s,s.begin():
            await service.accept_put(s,context.user_id,album_id,upload_id)
    except APIError:
        if created: await asyncio.to_thread(store.delete,key)
        raise
    return Response(status_code=204)


@router.post('/albums/{album_id}/uploads/{upload_id}/complete')
async def complete(request:Request,album_id:UUID,upload_id:UUID,body:CompleteBody,context:AuthContext=Depends(require_user)):
    require_csrf(request,context); validate_query(request,())
    from backend.telemetry import span
    with span('upload.complete', request_id=getattr(request.state,'request_id',None)):
        status,data=await service.complete_upload(request.app.state.session_factory,storage(request),context.user_id,album_id,upload_id,expected_sha256=body.sha256)
    return JSONResponse(envelope(request,data),status_code=status)


@router.get('/albums/{album_id}/uploads/{upload_id}')
async def status(request:Request,album_id:UUID,upload_id:UUID,context:AuthContext=Depends(require_user)):
    validate_query(request,())
    async with request.app.state.session_factory() as s,s.begin():
        return envelope(request,await service.upload_status(s,context.user_id,album_id,upload_id))


@router.delete('/albums/{album_id}/pages/{page_id}')
async def remove(request:Request,album_id:UUID,page_id:UUID,expected_version:int=Query(ge=1),context:AuthContext=Depends(require_user)):
    require_csrf(request,context); validate_query(request,('expected_version',))
    async with request.app.state.session_factory() as s,s.begin():
        data=await service.remove_page(s,context.user_id,album_id,page_id,expected_version)
    return envelope(request,data)


@router.put('/albums/{album_id}/page-order')
async def order(request:Request,album_id:UUID,body:OrderBody,context:AuthContext=Depends(require_user)):
    require_csrf(request,context); validate_query(request,())
    async with request.app.state.session_factory() as s,s.begin(): data=await service.order(s,context.user_id,album_id,body)
    return envelope(request,data)


@router.post('/albums/{album_id}/media-access')
async def access(request:Request,album_id:UUID,body:AccessBody,context:AuthContext=Depends(require_user)):
    require_csrf(request,context); validate_query(request,())
    async with request.app.state.session_factory() as s,s.begin():
        data=await service.media_access(s,context.user_id,album_id,body.asset_ids,signer(request))
    return envelope(request,data)


@router.get('/private/albums/{album_id}/media/{asset_id}')
async def media(request:Request,album_id:UUID,asset_id:UUID,expires:int,signature:str,context:AuthContext=Depends(private_user)):
    validate_query(request,('expires','signature'))
    async with request.app.state.session_factory() as s,s.begin():
        asset=await repo.visible_asset(s,context.user_id,album_id,asset_id)
        if not signer(request).verify('GET',request.url.path,asset_id,expires,asset.mime,signature,service.now().timestamp()): raise APIError(404,'RESOURCE_NOT_FOUND')
        path=storage(request).path(asset.storage_key)
        if not path.is_file(): raise APIError(404,'RESOURCE_NOT_FOUND')
    return FileResponse(path,media_type=asset.mime,headers={'Cache-Control':'no-store'})
