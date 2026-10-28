from fastapi import APIRouter, Request, Depends, Response
from fastapi.responses import JSONResponse
from backend.auth import service
from backend.http.errors import APIError, envelope
from backend.http.schemas import DevLogin, ConsentBody, EmptyBody, CLIENT_CONFIG
from backend.http.security import COOKIE_NAME, AuthContext, require_user, require_csrf, require_origin, csrf_token

router = APIRouter()


async def require_dev(request: Request):
    settings = request.app.state.settings
    if settings.app_env != 'local' or not settings.dev_auth_enabled:
        raise APIError(404, 'RESOURCE_NOT_FOUND')
    require_origin(request)


@router.get('/api/dev/config')
async def dev_config(request: Request):
    settings = request.app.state.settings
    return envelope(request, {'dev_auth_enabled': settings.app_env == 'local' and settings.dev_auth_enabled,
                              'dev_ai_enabled': settings.app_env == 'local' and settings.dev_ai_enabled,
                              'generation_enabled': settings.generation_enabled,
                              'generation_mode': 'openai' if settings.ai_real_calls_enabled else 'local_fake' if settings.dev_ai_enabled else None})


@router.post('/api/dev/login', dependencies=[Depends(require_dev)])
async def login(request: Request, body: DevLogin):
    settings = request.app.state.settings
    raw = await service.login(request.app.state.session_factory, settings, body.account)
    response = Response(status_code=204)
    response.set_cookie(COOKIE_NAME, raw, max_age=settings.session_ttl_seconds, path='/',
                        httponly=True, secure=settings.session_cookie_secure, samesite='lax')
    return response


@router.get('/api/v1/client-config')
async def client_config(request: Request):
    return envelope(request, {**CLIENT_CONFIG, 'auth_providers': request.app.state.settings.auth_providers})


@router.get('/api/v1/me')
async def me(request: Request, context: AuthContext = Depends(require_user)):
    data = await service.me(request.app.state.session_factory, request.app.state.settings, context)
    data['csrf_token'] = csrf_token(request.cookies[COOKIE_NAME])
    return envelope(request, data)


@router.post('/api/v1/consents')
async def consent(request: Request, body: ConsentBody, context: AuthContext = Depends(require_user)):
    require_csrf(request, context)
    data, created = await service.consent(request.app.state.session_factory, request.app.state.settings, context, body)
    return JSONResponse(envelope(request, data), status_code=201 if created else 200)


@router.post('/api/v1/auth/logout')
async def logout(request: Request, body: EmptyBody, context: AuthContext = Depends(require_user)):
    require_csrf(request, context)
    await service.logout(request.app.state.session_factory, context)
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path='/', secure=request.app.state.settings.session_cookie_secure,
                           httponly=True, samesite='lax')
    return response
