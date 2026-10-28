"""One-use OAuth browser login; no provider secrets cross this boundary."""
import re
import secrets
from datetime import datetime, timedelta, timezone

import httpx

from backend.auth import repository, oauth_repository
from backend.auth.oauth_providers import OAuthProviderError, authorization_url, exchange_identity
from backend.auth.oauth_types import OAuthIdentity
from backend.http.errors import APIError
from backend.http.security import token_hash

LOGIN_TTL_SECONDS = 600
_TOKEN = re.compile(r'[A-Za-z0-9_-]{43,128}')


class OAuthLoginError(Exception):
    """Safe, generic failed login; contains no provider error details."""


class OAuthLoginCancelled(OAuthLoginError):
    """A cancellation backed by a consumed state and matching browser binding."""


def _enabled(settings, provider):
    return provider in ('google', 'kakao') and provider in settings.auth_providers


def _valid_token(value):
    return isinstance(value, str) and _TOKEN.fullmatch(value) is not None


def valid_code(code):
    return (isinstance(code, str) and 1 <= len(code) <= 2048
            and not any(ord(char) <= 32 or ord(char) == 127 for char in code))


async def start_login(factory, settings, provider, return_to) -> tuple[str, str, str]:
    if not _enabled(settings, provider):
        raise APIError(404, 'RESOURCE_NOT_FOUND')
    state, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    try:
        async with factory() as session, session.begin():
            await oauth_repository.begin_login(session, provider, token_hash(state), token_hash(binding),
                                               return_to, datetime.now(timezone.utc) + timedelta(seconds=LOGIN_TTL_SECONDS))
    except ValueError:
        raise APIError(422, 'VALIDATION_ERROR') from None
    return authorization_url(settings, provider, state), state, binding


async def _consume(factory, settings, provider, state, binding):
    if not _enabled(settings, provider) or not _valid_token(state) or not _valid_token(binding):
        raise OAuthLoginError() from None
    async with factory() as session, session.begin():
        return_to = await oauth_repository.consume_login(
            session, provider, token_hash(state), token_hash(binding), datetime.now(timezone.utc))
        if return_to is None:
            raise OAuthLoginError() from None
    # Commit before any external provider await: failed exchanges cannot replay.
    return return_to


async def reject_login(factory, settings, provider, state, binding, *, cancelled=False):
    await _consume(factory, settings, provider, state, binding)
    if cancelled:
        raise OAuthLoginCancelled() from None
    raise OAuthLoginError() from None


async def complete_login(factory, settings, provider, code, state, binding,
                         previous_session_token: str | None, *, client: httpx.AsyncClient | None = None) -> tuple[str, str]:
    if not valid_code(code):
        raise OAuthLoginError() from None
    return_to = await _consume(factory, settings, provider, state, binding)
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as owned_client:
                identity = await exchange_identity(owned_client, settings, provider, code)
        else:
            identity = await exchange_identity(client, settings, provider, code)
        if not isinstance(identity, OAuthIdentity) or identity.provider != provider:
            raise OAuthLoginError()
        raw_session = secrets.token_urlsafe(32)
        async with factory() as session, session.begin():
            user = await oauth_repository.resolve_identity(session, identity)
            await repository.save_session(session, user.id, token_hash(raw_session),
                                          datetime.now(timezone.utc) + timedelta(seconds=settings.session_ttl_seconds))
            # Only the session cookie from this successful bound callback is eligible
            # for rotation. Missing, expired, revoked or deleted-user sessions are safe.
            if isinstance(previous_session_token, str) and 1 <= len(previous_session_token) <= 512:
                previous = await repository.find_session(session, token_hash(previous_session_token))
                if previous is not None:
                    await repository.revoke(session, previous.id)
    except (OAuthProviderError, httpx.HTTPError, APIError, ValueError):
        raise OAuthLoginError() from None
    return raw_session, return_to
