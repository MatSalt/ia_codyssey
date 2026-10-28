"""Authenticated generation HTTP boundary; transaction belongs to the route."""
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import Field, StrictInt
from backend.albums.routes import validate_query
from backend.generation import service
from backend.generation.views import generation_view
from backend.http.errors import envelope
from backend.http.idempotency import require_key, request_hash
from backend.http.schemas import StrictBody
from backend.http.security import AuthContext, require_user, require_csrf

router = APIRouter(prefix='/api/v1/albums')


class GenerationBody(StrictBody):
    expected_version: StrictInt = Field(ge=1)


class ResumeBody(GenerationBody):
    run_id: UUID


@router.post('/{album_id}/generation')
async def create(request: Request, album_id: UUID, body: GenerationBody,
                 context: AuthContext = Depends(require_user), idempotency_key: str | None = Header(default=None)):
    require_csrf(request,context); validate_query(request,())
    key=require_key(idempotency_key)
    async with request.app.state.session_factory() as session, session.begin():
        status,data=await service.create_generation(session,context.user_id,album_id,body.expected_version,key,
            request_hash(body.model_dump(mode='json')),request.app.state.settings)
    return JSONResponse(envelope(request,data),status_code=status)


@router.get('/{album_id}/generation')
async def progress(request: Request, album_id: UUID, run_id: UUID | None = None,
                   context: AuthContext = Depends(require_user)):
    validate_query(request,('run_id',))
    async with request.app.state.session_factory() as session, session.begin():
        data=await generation_view(session,context.user_id,album_id,run_id)
    return envelope(request,data)


@router.post('/{album_id}/generation/resume')
async def resume(request: Request, album_id: UUID, body: ResumeBody,
                 context: AuthContext = Depends(require_user), idempotency_key: str | None = Header(default=None)):
    require_csrf(request,context); validate_query(request,())
    key=require_key(idempotency_key)
    async with request.app.state.session_factory() as session, session.begin():
        status,data=await service.resume_generation(session,context.user_id,album_id,body.run_id,body.expected_version,key,
            request_hash(body.model_dump(mode='json')),request.app.state.settings)
    return JSONResponse(envelope(request,data),status_code=status)
