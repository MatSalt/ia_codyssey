"""Strict browser-facing OAuth redirects; provider details are never reflected."""
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from backend.auth import oauth_service as service
from backend.http.errors import APIError
from backend.http.security import COOKIE_NAME

router = APIRouter()
BINDING_COOKIE = 'mori_oauth_binding'
_COMMON_FIELDS = {'state', 'code', 'error', 'error_description', 'error_uri', 'iss'}
_GOOGLE_FIELDS = {'scope', 'authuser', 'prompt', 'hd'}
_ISSUERS = {'google': 'https://accounts.google.com', 'kakao': 'https://kauth.kakao.com'}


def _query(request, allowed, limits):
    if len(request.scope.get('query_string', b'')) > 8192:
        raise ValueError('Invalid OAuth parameters')
    pairs = request.query_params.multi_items()
    if len(pairs) != len({key for key, _ in pairs}):
        raise ValueError('Invalid OAuth parameters')
    result = {}
    for key, value in pairs:
        if key not in allowed or len(value) > limits.get(key, 256):
            raise ValueError('Invalid OAuth parameters')
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError('Invalid OAuth parameters')
        result[key] = value
    return result


def _one_cookie(request, name):
    # Duplicate names can arise from conflicting cookie paths/domains. Fail closed
    # for binding and ignore ambiguous previous-session cookies during rotation.
    names = [part.split('=', 1)[0].strip() for header in request.headers.getlist('cookie')
             for part in header.split(';') if '=' in part]
    return request.cookies.get(name) if names.count(name) == 1 else None


def _redirect(request, location):
    response = RedirectResponse(location, status_code=302, headers={
        'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
    response.delete_cookie(BINDING_COOKIE, path='/', httponly=True,
                           secure=request.app.state.settings.session_cookie_secure, samesite='lax')
    return response


@router.get('/api/v1/auth/{provider}/start')
async def start(request: Request, provider: str):
    settings = request.app.state.settings
    # Disabled providers are hidden even when their query is malformed.
    if provider not in settings.auth_providers:
        raise APIError(404, 'RESOURCE_NOT_FOUND')
    try:
        query = _query(request, {'return_to'}, {'return_to': 255})
    except ValueError:
        raise APIError(422, 'VALIDATION_ERROR') from None
    url, _, binding = await service.start_login(request.app.state.session_factory, settings,
                                               provider, query.get('return_to', '/goods'))
    response = RedirectResponse(url, status_code=302, headers={
        'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
    response.set_cookie(BINDING_COOKIE, binding, max_age=service.LOGIN_TTL_SECONDS, path='/',
                        httponly=True, secure=settings.session_cookie_secure, samesite='lax')
    return response


@router.get('/api/v1/auth/{provider}/callback')
async def callback(request: Request, provider: str):
    settings = request.app.state.settings
    try:
        allowed = _COMMON_FIELDS | (_GOOGLE_FIELDS if provider == 'google' else set())
        query = _query(request, allowed, {'state': 128, 'code': 2048, 'error': 256,
                                        'scope': 2048, 'error_description': 2048, 'error_uri': 2048})
        if ('code' in query) == ('error' in query):
            raise service.OAuthLoginError()
        if 'iss' in query and query['iss'] != _ISSUERS.get(provider):
            raise service.OAuthLoginError()
        binding = _one_cookie(request, BINDING_COOKIE)
        factory = request.app.state.session_factory
        if 'error' in query:
            if not query['error']:
                raise service.OAuthLoginError()
            await service.reject_login(factory, settings, provider, query.get('state'), binding,
                                       cancelled=query['error'] == 'access_denied')
        raw_session, return_to = await service.complete_login(
            factory, settings, provider, query['code'], query.get('state'), binding,
            _one_cookie(request, COOKIE_NAME))
    except service.OAuthLoginCancelled:
        return _redirect(request, '/login?auth_error=cancelled')
    except (service.OAuthLoginError, ValueError):
        return _redirect(request, '/login?auth_error=failed')
    response = _redirect(request, return_to)
    response.set_cookie(COOKIE_NAME, raw_session, max_age=settings.session_ttl_seconds, path='/',
                        httponly=True, secure=settings.session_cookie_secure, samesite='lax')
    return response
