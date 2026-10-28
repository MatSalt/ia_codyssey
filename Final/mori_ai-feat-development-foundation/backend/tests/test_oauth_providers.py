"""Provider boundary checks; every HTTP exchange uses an in-memory transport."""
import importlib
import json
import traceback
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr


@pytest.fixture
def adapter():
    return importlib.import_module('backend.auth.oauth_providers')


@pytest.fixture
def settings():
    return SimpleNamespace(
        google_client_id='google-client', google_client_secret=SecretStr('secret-marker'),
        google_redirect_uri='https://app.example/api/v1/auth/google/callback',
        kakao_client_id='kakao-client', kakao_client_secret=SecretStr(''),
        kakao_redirect_uri='https://app.example/api/v1/auth/kakao/callback',
    )


@pytest.fixture
def client_factory():
    def make(handler):
        # Deliberately enable redirects on the injected client: adapter must override it.
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    return make


@pytest.mark.parametrize('provider,host,path,scope', [
    ('google', 'accounts.google.com', '/o/oauth2/v2/auth', ['openid profile']),
    ('kakao', 'kauth.kakao.com', '/oauth/authorize', None),
])
def test_authorization_parameters(adapter, settings, provider, host, path, scope):
    url = urlsplit(adapter.authorization_url(settings, provider, 'state & +'))
    query = parse_qs(url.query)
    assert (url.scheme, url.netloc, url.path) == ('https', host, path)
    assert query == dict(client_id=[f'{provider}-client'],
                         redirect_uri=[f'https://app.example/api/v1/auth/{provider}/callback'],
                         response_type=['code'], state=['state & +'],
                         **({'scope': scope} if scope else {}))
    assert 'secret-marker' not in url.geturl()


@pytest.mark.parametrize('provider', ['google', 'kakao'])
@pytest.mark.asyncio
async def test_exchange_uses_fixed_form_and_bearer(adapter, settings, client_factory, provider):
    requests = []
    async def handler(request):
        requests.append(request)
        assert request.extensions['timeout'] == dict(connect=10, read=10, write=10, pool=10)
        assert not request.url.query
        if len(requests) == 1:
            assert request.method == 'POST'
            assert str(request.url) == ('https://oauth2.googleapis.com/token' if provider == 'google'
                                        else 'https://kauth.kakao.com/oauth/token')
            assert request.headers['content-type'].startswith('application/x-www-form-urlencoded')
            form = parse_qs(request.content.decode())
            assert form == dict(client_id=[f'{provider}-client'], code=['code & +'],
                                redirect_uri=[getattr(settings, f'{provider}_redirect_uri')],
                                grant_type=['authorization_code'],
                                **({'client_secret': ['secret-marker']} if provider == 'google' else {}))
            return httpx.Response(200, json={'access_token': 'token-marker', 'token_type': 'bearer'})
        assert request.method == 'GET'
        assert str(request.url) == ('https://openidconnect.googleapis.com/v1/userinfo' if provider == 'google'
                                    else 'https://kapi.kakao.com/v2/user/me')
        assert request.headers['authorization'] == 'Bearer token-marker'
        return httpx.Response(200, json=({'sub': 'g-user', 'name': '이름'} if provider == 'google'
                                        else {'id': 123, 'properties': {'nickname': '이름'}}))
    async with client_factory(handler) as client:
        identity = await adapter.exchange_identity(client, settings, provider, 'code & +')
    assert (identity.provider, identity.subject, identity.display_name) == (
        provider, 'g-user' if provider == 'google' else '123', '이름')
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_kakao_configured_secret(adapter, settings, client_factory):
    settings.kakao_client_secret = SecretStr('secret-marker')
    async def handler(request):
        if request.method == 'POST':
            assert parse_qs(request.content.decode())['client_secret'] == ['secret-marker']
            return httpx.Response(200, json={'access_token': 'token-marker'})
        return httpx.Response(200, json={'id': 1})
    async with client_factory(handler) as client:
        identity = await adapter.exchange_identity(client, settings, 'kakao', 'code')
    assert identity.display_name == '사용자'


@pytest.mark.parametrize('provider,profile,expected', [
    ('google', {'sub': 's'}, '사용자'),
    ('google', {'sub': 's', 'name': None}, '사용자'),
    ('google', {'sub': 's', 'name': ''}, '사용자'),
    ('google', {'sub': 's', 'name': 12}, '사용자'),
    ('google', {'sub': 's', 'name': '가' * 101}, '가' * 100),
    ('kakao', {'id': 1, 'properties': {'nickname': '가' * 101}}, '가' * 100),
    ('kakao', {'id': 1, 'properties': None}, '사용자'),
    ('kakao', {'id': 1, 'kakao_account': {'profile': {'nickname': '프로필'}}}, '프로필'),
])
@pytest.mark.asyncio
async def test_display_name_normalization(adapter, settings, client_factory, provider, profile, expected):
    async def handler(request):
        return httpx.Response(200, json={'access_token': 't'} if request.method == 'POST' else profile)
    async with client_factory(handler) as client:
        result = await adapter.exchange_identity(client, settings, provider, 'c')
    assert result.display_name == expected


@pytest.mark.parametrize('provider,profile', [
    *[('google', {'sub': value}) for value in [None, '', ' ', 1, True, [], 'a' * 256]],
    *[('kakao', {'id': value}) for value in [None, 0, -1, True, 1.0, '123', [], 10 ** 255]],
    ('google', {}), ('kakao', {}), ('google', {'sub': 's', 'error': 'secret-marker'}),
    ('kakao', {'id': 1, 'error': 'secret-marker'}),
])
@pytest.mark.asyncio
async def test_invalid_identity_rejected(adapter, settings, client_factory, provider, profile):
    async def handler(request):
        return httpx.Response(200, json={'access_token': 'token-marker'} if request.method == 'POST' else profile)
    async with client_factory(handler) as client:
        with pytest.raises(adapter.OAuthProviderError):
            await adapter.exchange_identity(client, settings, provider, 'code-marker')


@pytest.mark.parametrize('provider', ['google', 'kakao'])
@pytest.mark.parametrize('stage', ['token', 'profile'])
@pytest.mark.parametrize('failure', ['5xx', '4xx', 'redirect', 'timeout', 'json', 'array', 'null', 'oversized', 'error'])
@pytest.mark.asyncio
async def test_provider_failure_generic_no_retry_or_redirect(adapter, settings, client_factory, provider, stage, failure):
    requests = []
    async def handler(request):
        requests.append(request)
        if stage == 'profile' and len(requests) == 1:
            return httpx.Response(200, json={'access_token': 'token-marker'})
        if failure == 'timeout':
            raise httpx.ReadTimeout('secret-marker token-marker code-marker', request=request)
        if failure in ('5xx', '4xx', 'redirect'):
            return httpx.Response({'5xx': 500, '4xx': 400, 'redirect': 302}[failure],
                                  headers={'location': 'https://evil.example/secret-marker'},
                                  content=b'secret-marker')
        if failure == 'json':
            return httpx.Response(200, content=b'secret-marker{')
        if failure == 'oversized':
            return httpx.Response(200, content=b' ' * (1048576 + 1))
        return httpx.Response(200, json={'array': [], 'null': None,
                                        'error': {'error': 'secret-marker', 'access_token': 'token-marker', 'sub': 's'}}[failure])
    code = 'code-marker'
    async with client_factory(handler) as client:
        with pytest.raises(adapter.OAuthProviderError) as caught:
            await adapter.exchange_identity(client, settings, provider, code)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    rendered = ''.join(traceback.format_exception(caught.value))
    assert all(marker not in rendered for marker in ['secret-marker', 'token-marker', 'code-marker', 'https://'])
    assert len(requests) == (1 if stage == 'token' else 2)


@pytest.mark.parametrize('value', [None, '', ' ', 123, True, [], 'a' * 16385, 'bad\r\ntoken'],
                         ids=['missing', 'empty', 'blank', 'number', 'bool', 'array', 'too-long', 'control'])
@pytest.mark.asyncio
async def test_invalid_token_rejected_before_profile(adapter, settings, client_factory, value):
    requests = []
    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'access_token': value})
    async with client_factory(handler) as client:
        with pytest.raises(adapter.OAuthProviderError):
            await adapter.exchange_identity(client, settings, 'google', 'c')
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_supported_maximum_boundaries(adapter, settings, client_factory):
    async def handler(request):
        if request.method == 'POST':
            return httpx.Response(200, json={'access_token': 't' * 16384})
        body = json.dumps({'sub': 's' * 255, 'name': 'n' * 100}).encode()
        return httpx.Response(200, content=body + b' ' * (1048576 - len(body)))
    async with client_factory(handler) as client:
        identity = await adapter.exchange_identity(client, settings, 'google', 'c')
    assert identity.subject == 's' * 255
    assert identity.display_name == 'n' * 100


@pytest.mark.asyncio
async def test_unsupported_provider_never_requests(adapter, settings, client_factory):
    async def handler(request):
        pytest.fail('unsupported provider must not make requests')
    with pytest.raises(adapter.OAuthProviderError):
        adapter.authorization_url(settings, 'other', 's')
    async with client_factory(handler) as client:
        with pytest.raises(adapter.OAuthProviderError):
            await adapter.exchange_identity(client, settings, 'other', 'c')


@pytest.mark.parametrize('stage', ['token', 'profile'])
@pytest.mark.asyncio
async def test_stream_limit_stops_reading_and_closes(adapter, settings, client_factory, stage):
    class OversizedStream(httpx.AsyncByteStream):
        def __init__(self):
            self.reads = 0
            self.closed = False

        async def __aiter__(self):
            for _ in range(100):
                self.reads += 1
                yield b' ' * 65536

        async def aclose(self):
            self.closed = True

    stream = OversizedStream()
    async def handler(request):
        if stage == 'profile' and request.method == 'POST':
            return httpx.Response(200, json={'access_token': 't'})
        # No Content-Length: the actual streamed bytes must enforce the limit.
        return httpx.Response(200, stream=stream)
    async with client_factory(handler) as client:
        with pytest.raises(adapter.OAuthProviderError):
            await adapter.exchange_identity(client, settings, 'google', 'c')
    assert stream.closed
    assert stream.reads == 17
