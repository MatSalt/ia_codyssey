"""Fixed-endpoint OAuth REST adapters. Provider credentials never leave this boundary."""
import json
from urllib.parse import urlencode

import httpx

from backend.auth.oauth_types import OAuthIdentity


class OAuthProviderError(Exception):
    """Generic authentication failure without provider response details."""


_ENDPOINTS = {
    'google': (
        'https://accounts.google.com/o/oauth2/v2/auth',
        'https://oauth2.googleapis.com/token',
        'https://openidconnect.googleapis.com/v1/userinfo',
    ),
    'kakao': (
        'https://kauth.kakao.com/oauth/authorize',
        'https://kauth.kakao.com/oauth/token',
        'https://kapi.kakao.com/v2/user/me',
    ),
}
_MAX_RESPONSE_BYTES = 1024 * 1024
_MAX_TOKEN_CHARS = 16 * 1024
_ERROR = 'OAuth provider authentication failed'


def authorization_url(settings, provider: str, state: str) -> str:
    if provider not in _ENDPOINTS:
        raise OAuthProviderError(_ERROR)
    query = {
        'client_id': getattr(settings, f'{provider}_client_id'),
        'redirect_uri': getattr(settings, f'{provider}_redirect_uri'),
        'response_type': 'code',
        'state': state,
    }
    if provider == 'google':
        query['scope'] = 'openid profile'
    return _ENDPOINTS[provider][0] + '?' + urlencode(query)


async def _read_json(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> dict:
    async with client.stream(method, url, timeout=10.0, follow_redirects=False, **kwargs) as response:
        if not 200 <= response.status_code < 300:
            raise OAuthProviderError(_ERROR)
        body = bytearray()
        # Bound the decoded size too, including compressed/chunked responses.
        async for chunk in response.aiter_bytes(chunk_size=65536):
            if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                raise OAuthProviderError(_ERROR)
            body.extend(chunk)
        payload = json.loads(body)
        if not isinstance(payload, dict) or 'error' in payload:
            raise OAuthProviderError(_ERROR)
        return payload


def _display_name(profile: dict, provider: str) -> str:
    if provider == 'google':
        name = profile.get('name')
    else:
        properties = profile.get('properties')
        name = properties.get('nickname') if isinstance(properties, dict) else None
        if not isinstance(name, str) or not name.strip():
            account = profile.get('kakao_account')
            account_profile = account.get('profile') if isinstance(account, dict) else None
            name = account_profile.get('nickname') if isinstance(account_profile, dict) else None
    return name[:100] if isinstance(name, str) and name.strip() else '사용자'


async def _exchange(client: httpx.AsyncClient, settings, provider: str, code: str) -> OAuthIdentity:
    if provider not in _ENDPOINTS:
        raise OAuthProviderError(_ERROR)
    _, token_url, profile_url = _ENDPOINTS[provider]
    form = {
        'client_id': getattr(settings, f'{provider}_client_id'),
        'redirect_uri': getattr(settings, f'{provider}_redirect_uri'),
        'grant_type': 'authorization_code',
        'code': code,
    }
    secret = getattr(settings, f'{provider}_client_secret').get_secret_value()
    if provider == 'google' or secret:
        form['client_secret'] = secret
    token_payload = await _read_json(client, 'POST', token_url, data=form)
    token = token_payload.get('access_token')
    if (not isinstance(token, str) or not token.strip() or len(token) > _MAX_TOKEN_CHARS
            or any(ord(char) <= 32 or ord(char) >= 127 for char in token)):
        raise OAuthProviderError(_ERROR)
    profile = await _read_json(client, 'GET', profile_url,
                               headers={'Authorization': f'Bearer {token}'})
    if provider == 'google':
        subject = profile.get('sub')
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 255:
            raise OAuthProviderError(_ERROR)
    else:
        identifier = profile.get('id')
        if type(identifier) is not int or identifier <= 0:
            raise OAuthProviderError(_ERROR)
        subject = str(identifier)
        if len(subject) > 255:
            raise OAuthProviderError(_ERROR)
    return OAuthIdentity(provider, subject, _display_name(profile, provider))


async def exchange_identity(client: httpx.AsyncClient, settings, provider: str, code: str) -> OAuthIdentity:
    """Exchange once; discard all upstream exception context before reporting failure."""
    try:
        return await _exchange(client, settings, provider, code)
    except Exception:
        # Raising outside the handler also removes __context__, rather than merely
        # hiding a secret-bearing httpx/JSON exception from formatted tracebacks.
        pass
    raise OAuthProviderError(_ERROR)
