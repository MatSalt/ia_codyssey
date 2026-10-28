"""Goods API: owner checks, CSRF, bounded uploads, no inline paid requests."""
import asyncio
import hashlib
from io import BytesIO
from uuid import UUID
import warnings
from PIL import Image,ImageOps
from fastapi import APIRouter,Depends,Header,Request,Query
from fastapi.responses import Response,JSONResponse
from pydantic import Field,StrictStr
from sqlalchemy import select
from backend.http.schemas import StrictBody,EmptyBody
from backend.http.security import AuthContext,require_user,require_csrf
from backend.http.errors import APIError,envelope
from backend.http.idempotency import require_key
from backend.goods_design import service
from backend.goods_design.models import GoodsWork,GoodsRevision,GoodsDesign
from backend.generation.service import require_consent
from backend.goods_design.prompt_profiles import catalog

router=APIRouter(prefix='/api/v1/goods')

class Generate(StrictBody):
    style:StrictStr
    message:StrictStr=Field(min_length=1,max_length=3000)
    parent_id:UUID|None=None
class Placement(StrictBody):
    holeX:float=Field(ge=0,le=1,allow_inf_nan=False)
    holeY:float=Field(ge=0,le=1,allow_inf_nan=False)
    widthMm:float=Field(ge=20,le=100,allow_inf_nan=False)
class Complete(StrictBody):
    revision_id:UUID
    placement:Placement
class LinkAlbum(StrictBody):
    album_id:UUID
    expected_version:int=Field(ge=1,strict=True)

def normalized(data):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as im:
                if im.format not in ('PNG','JPEG','WEBP') or im.width*im.height>16_000_000 or getattr(im,'n_frames',1)!=1:raise ValueError()
                im.load();im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((2048,2048))
                out=BytesIO();im.save(out,format='WEBP',quality=90)
                return out.getvalue()
    except Exception:raise APIError(422,'VALIDATION_ERROR') from None

@router.get('/catalog')
async def get_catalog(request:Request,context:AuthContext=Depends(require_user)):
    return envelope(request,{'styles':catalog()})

@router.post('/work')
async def create(request:Request,body:EmptyBody,context:AuthContext=Depends(require_user),idempotency_key:str|None=Header(None)):
    require_csrf(request,context)
    async with request.app.state.session_factory() as s,s.begin():
        await require_consent(s,context.user_id,request.app.state.settings)
        data=await service.create_work(s,context.user_id,require_key(idempotency_key))
    return JSONResponse(envelope(request,data),status_code=201)

@router.put('/work/{id}/source')
async def upload(request:Request,id:UUID,context:AuthContext=Depends(require_user)):
    require_csrf(request,context)
    async with request.app.state.session_factory() as s,s.begin():
        await service.work(s,context.user_id,id)
        await require_consent(s,context.user_id,request.app.state.settings)
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>20*1024*1024:raise APIError(413,'VALIDATION_ERROR')
    clean=await asyncio.to_thread(normalized,bytes(data));digest=hashlib.sha256(clean).hexdigest()
    async with request.app.state.session_factory() as s,s.begin():
        w=await service.work(s,context.user_id,id)
        if w.source_hash and w.source_hash!=digest:raise APIError(409,'VERSION_CONFLICT')
        key=f'{context.user_id}/{id}/{id}/source'
        await asyncio.to_thread(request.app.state.media_storage.write,key,clean)
        w.source_key=key;w.source_hash=digest
    return envelope(request,{'ready':True})

@router.get('/work/{id}')
async def work_detail(request:Request,id:UUID,context:AuthContext=Depends(require_user)):
    async with request.app.state.session_factory() as s,s.begin():data=await service.detail(s,context.user_id,id)
    return envelope(request,data)

@router.delete('/work/{id}')
async def abandon(request:Request,id:UUID,context:AuthContext=Depends(require_user)):
    require_csrf(request,context)
    async with request.app.state.session_factory() as s,s.begin():await service.discard(s,context.user_id,id)
    return Response(status_code=204)

@router.post('/work/{id}/revisions',status_code=202)
async def generate(request:Request,id:UUID,body:Generate,context:AuthContext=Depends(require_user),idempotency_key:str|None=Header(None)):
    require_csrf(request,context)
    async with request.app.state.session_factory() as s,s.begin():
        await require_consent(s,context.user_id,request.app.state.settings)
        data=await service.generate(s,context.user_id,id,body.model_dump(mode='json'),require_key(idempotency_key),request.app.state.settings)
    return envelope(request,data)

@router.post('/work/{id}/complete')
async def complete(request:Request,id:UUID,body:Complete,context:AuthContext=Depends(require_user)):
    require_csrf(request,context)
    async with request.app.state.session_factory() as s,s.begin():data=await service.complete(s,context.user_id,id,body.revision_id,body.placement.model_dump())
    return envelope(request,data)

@router.get('/designs')
async def designs(request:Request,offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=50),context:AuthContext=Depends(require_user)):
    async with request.app.state.session_factory() as s:
        rows=(await s.scalars(select(GoodsDesign).where(GoodsDesign.owner_id==context.user_id).order_by(GoodsDesign.created_at.desc(),GoodsDesign.id.desc()).offset(offset).limit(limit+1))).all()
        data={'items':[await service.design_view(s,d) for d in rows[:limit]],'next_offset':offset+limit if len(rows)>limit else None}
    return envelope(request,data)

@router.get('/designs/{id}')
async def design(request:Request,id:UUID,context:AuthContext=Depends(require_user)):
    async with request.app.state.session_factory() as s:data=await service.design_view(s,await service.design(s,context.user_id,id))
    return envelope(request,data)

@router.put('/designs/{id}/album')
async def link(request:Request,id:UUID,body:LinkAlbum,context:AuthContext=Depends(require_user)):
    require_csrf(request,context)
    async with request.app.state.session_factory() as s,s.begin():data=await service.link_album(s,context.user_id,id,body.album_id,body.expected_version)
    return envelope(request,data)

@router.get('/images/{id}')
async def image(request:Request,id:UUID,context:AuthContext=Depends(require_user)):
    async with request.app.state.session_factory() as s:
        row=(await s.execute(select(GoodsRevision,GoodsWork).join(GoodsWork,GoodsRevision.work_id==GoodsWork.id).where(GoodsRevision.id==id,GoodsWork.owner_id==context.user_id))).first()
        if row is None:raise APIError(404,'RESOURCE_NOT_FOUND')
        r,w=row
        saved=await s.scalar(select(GoodsDesign.id).where(GoodsDesign.revision_id==id))
        if r.status!='ready' or not r.result_key or not(saved or w.status=='active' and w.expires_at>service.now()):raise APIError(404,'RESOURCE_NOT_FOUND')
        key=r.result_key
    try:data=await asyncio.to_thread(request.app.state.media_storage.read_bytes,key)
    except FileNotFoundError:raise APIError(404,'RESOURCE_NOT_FOUND') from None
    return Response(data,media_type='image/png',headers={'X-Content-Type-Options':'nosniff'})
