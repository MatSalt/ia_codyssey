import hashlib
import secrets
from dataclasses import dataclass
from uuid import UUID
from fastapi import Request
from backend.http.errors import APIError

COOKIE_NAME = 'mori_session'


@dataclass(frozen=True)
class AuthContext:
    user_id: UUID
    session_id: UUID


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def csrf_token(raw: str) -> str:
    return hashlib.sha256(b'mori-ai:csrf:v1\x00' + raw.encode()).hexdigest()


def require_origin(request: Request) -> None:
    if request.headers.get('origin') != request.app.state.settings.app_origin:
        raise APIError(403, 'CSRF_INVALID')


async def require_user(request: Request) -> AuthContext:
    from backend.auth.repository import find_session
    raw = request.cookies.get(COOKIE_NAME)
    if not raw or len(raw) > 512:
        raise APIError(401, 'AUTH_REQUIRED')
    async with request.app.state.session_factory() as session:
        row = await find_session(session, token_hash(raw))
        if row is None:
            raise APIError(401, 'AUTH_REQUIRED')
        return AuthContext(user_id=row.user_id, session_id=row.id)


def require_csrf(request: Request, context: AuthContext) -> None:
    require_origin(request)
    raw = request.cookies.get(COOKIE_NAME, '')
    supplied = request.headers.get('x-csrf-token', '')
    if not supplied or not secrets.compare_digest(supplied.encode(), csrf_token(raw).encode()):
        raise APIError(403, 'CSRF_INVALID')
