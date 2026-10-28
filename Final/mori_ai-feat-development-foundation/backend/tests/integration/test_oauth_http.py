"""OAuth HTTP/service checks against real PG; provider calls are deterministic fakes."""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.oauth_types import OAuthIdentity
from backend.http.security import token_hash
from backend.main import create_app
from backend.models import AuthIdentity, OAuthLoginRequest, Session, User
from backend.settings import Settings

ORIGIN = 'https://mori.invalid'
BINDING_COOKIE = 'mori_oauth_binding'


def config(**overrides):
    values = dict(database_url=os.environ['DATABASE_URL'], app_env='local', app_origin=ORIGIN,
                  google_client_id='test-google', google_client_secret='test-secret',
                  google_redirect_uri=ORIGIN + '/api/v1/auth/google/callback',
                  kakao_client_id='test-kakao', kakao_redirect_uri=ORIGIN + '/api/v1/auth/kakao/callback')
    return Settings(**(values | overrides))


@pytest_asyncio.fixture
async def oauth_db(db):
    async with db() as session, session.begin():
        await session.execute(delete(OAuthLoginRequest))
    yield db
    async with db() as session, session.begin():
        await session.execute(delete(OAuthLoginRequest))


@pytest.fixture
def fake_provider(monkeypatch):
    from backend.auth import oauth_service
    calls = []

    async def exchange(client, settings, provider, code):
        calls.append((provider, code))
        return OAuthIdentity(provider, 'subject-' + provider, 'OAuth user')

    monkeypatch.setattr(oauth_service, 'exchange_identity', exchange)
    return calls


@pytest_asyncio.fixture
async def client(oauth_db, fake_provider):
    app = create_app(settings=config(), session_factory=oauth_db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as c:
            yield c


async def start(client, provider='google', return_to='/albums'):
    response = await client.get(f'/api/v1/auth/{provider}/start', params={'return_to': return_to})
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers['location']).query)
    return query['state'][0], client.cookies.get(BINDING_COOKIE), response


async def callback(client, state, provider='google', **params):
    return await client.get(f'/api/v1/auth/{provider}/callback', params={'state': state, 'code': 'test-code'} | params)


def assert_callback_headers(response):
    assert response.status_code == 302
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['referrer-policy'] == 'no-referrer'
    cleared = [value for value in response.headers.get_list('set-cookie') if value.startswith(BINDING_COOKIE + '=')]
    assert len(cleared) == 1 and 'Max-Age=0' in cleared[0]


async def count_sessions(factory):
    async with factory() as session:
        return await session.scalar(select(func.count()).select_from(Session))


@pytest.mark.asyncio
async def test_start_redirect_secure_binding_hashes_ttl_and_unique_tokens(client, oauth_db):
    state, binding, response = await start(client)
    assert len(state) >= 43 and len(binding) >= 43 and state != binding
    assert response.headers['cache-control'] == 'no-store'
    cookie = response.headers['set-cookie']
    for flag in ['HttpOnly', 'Secure', 'SameSite=lax', 'Path=/', 'Max-Age=600']:
        assert flag in cookie
    async with oauth_db() as session:
        row = await session.scalar(select(OAuthLoginRequest))
        assert row.state_hash == token_hash(state) and row.binding_hash == token_hash(binding)
        assert row.provider == 'google' and row.return_to == '/albums' and row.consumed_at is None
        assert 590 < (row.expires_at - datetime.now(timezone.utc)).total_seconds() <= 600
    another, another_binding, _ = await start(client)
    assert another != state and another_binding != binding


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['unsupported', 'google'])
async def test_unconfigured_or_unsupported_provider_404(oauth_db, provider):
    app = create_app(settings=config(google_client_id='', google_client_secret=''), session_factory=oauth_db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as c:
            response = await c.get(f'/api/v1/auth/{provider}/start')
            assert response.status_code == 404
            assert response.json()['error']['code'] == 'RESOURCE_NOT_FOUND'
            assert BINDING_COOKIE not in response.headers.get('set-cookie', '')
    async with oauth_db() as session:
        assert await session.scalar(select(func.count()).select_from(OAuthLoginRequest)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('target', ['https://evil.invalid', '//evil.invalid', '/albums?x=1', '/albums#x', '/%61lbums', '/albums\\evil', '/albums/../login', '/albums\n'])
async def test_malicious_return_path_422_without_state(client, oauth_db, target):
    response = await client.get('/api/v1/auth/google/start', params={'return_to': target})
    assert response.status_code == 422 and response.json()['error']['code'] == 'VALIDATION_ERROR'
    async with oauth_db() as session:
        assert await session.scalar(select(func.count()).select_from(OAuthLoginRequest)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('query', ['return_to=/albums&return_to=/albums', 'unknown=x'])
async def test_start_rejects_query_pollution(client, query):
    assert (await client.get('/api/v1/auth/google/start?' + query)).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['google', 'kakao'])
async def test_login_success_consent_and_one_time_callback(client, oauth_db, fake_provider, provider):
    target = '/albums/12345678-1234-1234-1234-123456789abc/review'
    state, binding, _ = await start(client, provider, target)
    response = await callback(client, state, provider)
    assert_callback_headers(response)
    assert response.headers['location'] == target
    raw = client.cookies.get('mori_session')
    assert raw and len(raw) >= 43 and raw not in response.headers['location']
    assert state not in response.headers['location'] and binding not in response.headers['location']
    me = (await client.get('/api/v1/me')).json()['data']
    assert me['user']['display_name'] == 'OAuth user' and me['consent']['required'] is True
    async with oauth_db() as session:
        saved = await session.scalar(select(Session))
        assert saved.token_hash == token_hash(raw) and saved.token_hash != raw
    # Restore the consumed binding to prove DB replay rejection, not just cookie deletion.
    client.cookies.set(BINDING_COOKIE, binding, domain='mori.invalid', path='/')
    replay = await callback(client, state, provider)
    assert replay.headers['location'] == '/login?auth_error=failed'
    assert await count_sessions(oauth_db) == 1 and len(fake_provider) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['missing-state', 'wrong-state', 'missing-binding', 'wrong-binding', 'expired', 'wrong-provider'])
async def test_invalid_callback_cannot_exchange_or_issue_session(client, oauth_db, fake_provider, case):
    state, _, _ = await start(client)
    if case == 'missing-state':
        response = await client.get('/api/v1/auth/google/callback?code=test-code')
    else:
        if case == 'wrong-state':
            state = 'x' * 43
        if case == 'missing-binding':
            client.cookies.clear()
        if case == 'wrong-binding':
            client.cookies.clear()
            client.cookies.set(BINDING_COOKIE, 'x' * 43, domain='mori.invalid', path='/')
        if case == 'expired':
            async with oauth_db() as session, session.begin():
                await session.execute(update(OAuthLoginRequest).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        response = await callback(client, state, 'kakao' if case == 'wrong-provider' else 'google')
    assert_callback_headers(response)
    assert response.headers['location'] == '/login?auth_error=failed'
    assert not fake_provider and await count_sessions(oauth_db) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('extra', ['code=test-code&code=other', 'code=test-code&error=access_denied', 'code=test-code&unknown=extra', 'error=access_denied&error=access_denied', 'code=', 'code=' + 'x' * 2049, 'error=' + 'x' * 257])
async def test_duplicate_ambiguous_unknown_or_oversized_query_rejected(client, oauth_db, fake_provider, extra):
    state, _, _ = await start(client)
    response = await client.get('/api/v1/auth/google/callback?state=' + state + '&' + extra)
    assert_callback_headers(response)
    assert response.headers['location'] == '/login?auth_error=failed'
    assert not fake_provider and await count_sessions(oauth_db) == 0


@pytest.mark.asyncio
async def test_duplicate_state_and_oversized_binding_are_rejected(client, oauth_db, fake_provider):
    state, _, _ = await start(client)
    response = await client.get('/api/v1/auth/google/callback?' + urlencode([('state', state), ('state', state), ('code', 'test-code')]))
    assert response.headers['location'] == '/login?auth_error=failed'
    state, _, _ = await start(client)
    client.cookies.clear()
    client.cookies.set(BINDING_COOKIE, 'x' * 513, domain='mori.invalid', path='/')
    assert (await callback(client, state)).headers['location'] == '/login?auth_error=failed'
    assert not fake_provider and await count_sessions(oauth_db) == 0


@pytest.mark.asyncio
async def test_cancel_requires_valid_browser_and_consumes_request(client, oauth_db, fake_provider):
    state, binding, _ = await start(client)
    client.cookies.clear()
    response = await client.get('/api/v1/auth/google/callback', params={'state': state, 'error': 'access_denied'})
    assert response.headers['location'] == '/login?auth_error=failed'
    client.cookies.set(BINDING_COOKIE, binding, domain='mori.invalid', path='/')
    response = await client.get('/api/v1/auth/google/callback', params={'state': state, 'error': 'access_denied'})
    assert_callback_headers(response)
    assert response.headers['location'] == '/login?auth_error=cancelled'
    client.cookies.set(BINDING_COOKIE, binding, domain='mori.invalid', path='/')
    assert (await callback(client, state)).headers['location'] == '/login?auth_error=failed'
    assert not fake_provider and await count_sessions(oauth_db) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['timeout', 'provider-error', 'wrong-provider-identity'])
async def test_provider_failure_is_redacted_and_state_stays_consumed(client, oauth_db, monkeypatch, kind):
    from backend.auth import oauth_service
    from backend.auth.oauth_providers import OAuthProviderError
    state, binding, _ = await start(client)
    async def fail(*args):
        if kind == 'timeout':
            raise httpx.ReadTimeout('sensitive-provider-body')
        if kind == 'provider-error':
            raise OAuthProviderError('sensitive-provider-body')
        return OAuthIdentity('kakao', 'wrong-provider', 'wrong')
    monkeypatch.setattr(oauth_service, 'exchange_identity', fail)
    response = await callback(client, state)
    assert_callback_headers(response)
    assert response.headers['location'] == '/login?auth_error=failed'
    assert 'sensitive' not in response.text + str(response.headers)
    async with oauth_db() as session:
        assert (await session.scalar(select(OAuthLoginRequest))).consumed_at is not None
        assert await session.scalar(select(func.count()).select_from(User)) == 0
    assert await count_sessions(oauth_db) == 0


@pytest.mark.asyncio
async def test_success_rotates_session_failure_does_not_revoke_it(client, oauth_db):
    state, _, _ = await start(client)
    await callback(client, state)
    old = client.cookies.get('mori_session')
    state, _, _ = await start(client, 'kakao')
    # Wrong state on the same browser must leave the existing session usable.
    assert (await callback(client, 'x' * 43, 'kakao')).headers['location'] == '/login?auth_error=failed'
    assert (await client.get('/api/v1/me')).status_code == 200
    state, _, _ = await start(client, 'kakao')
    assert (await callback(client, state, 'kakao')).headers['location'] == '/albums'
    assert client.cookies.get('mori_session') != old
    async with oauth_db() as session:
        assert (await session.scalar(select(Session).where(Session.token_hash == token_hash(old)))).revoked_at is not None
        assert await session.scalar(select(func.count()).select_from(User)) == 2
    current = client.cookies.get('mori_session')
    client.cookies.clear()
    client.cookies.set('mori_session', old, domain='mori.invalid', path='/')
    assert (await client.get('/api/v1/me')).status_code == 401
    client.cookies.clear()
    client.cookies.set('mori_session', current, domain='mori.invalid', path='/')
    assert (await client.get('/api/v1/me')).status_code == 200


@pytest.mark.asyncio
async def test_deleted_identity_does_not_issue_new_session(client, oauth_db):
    state, _, _ = await start(client)
    await callback(client, state)
    async with oauth_db() as session, session.begin():
        await session.execute(update(User).values(deleted_at=datetime.now(timezone.utc)))
    state, _, _ = await start(client)
    assert (await callback(client, state)).headers['location'] == '/login?auth_error=failed'
    assert await count_sessions(oauth_db) == 1
    assert (await client.get('/api/v1/me')).status_code == 401


@pytest.mark.asyncio
async def test_provider_accounts_have_separate_consent(client):
    state, _, _ = await start(client)
    await callback(client, state)
    google = (await client.get('/api/v1/me')).json()['data']
    response = await client.post('/api/v1/consents', json={'agreed': True, 'purpose': 'photo_upload_and_ai_processing', 'policy_version': google['consent']['policy_version']}, headers={'Origin': ORIGIN, 'X-CSRF-Token': google['csrf_token']})
    assert response.status_code == 201
    state, _, _ = await start(client, 'kakao')
    await callback(client, state, 'kakao')
    kakao = (await client.get('/api/v1/me')).json()['data']
    assert google['user']['id'] != kakao['user']['id'] and kakao['consent']['required'] is True


@pytest.mark.asyncio
async def test_state_commit_precedes_external_await_and_two_pg_connections_have_one_callback_winner(oauth_db, fake_provider, monkeypatch):
    from backend.auth import oauth_service
    settings = config()
    _, state, binding = await oauth_service.start_login(oauth_db, settings, 'google', '/albums')
    original = oauth_service.exchange_identity
    inspected = []
    async def check_commit(*args):
        # A second connection can already see consumption during the external call.
        async with oauth_db() as session:
            row = await session.scalar(select(OAuthLoginRequest))
            inspected.append(row.consumed_at is not None)
        return await original(*args)
    monkeypatch.setattr(oauth_service, 'exchange_identity', check_commit)
    barrier = asyncio.Barrier(2)
    pids = []
    entries = 0
    @asynccontextmanager
    async def independent_factory():
        nonlocal entries
        async with oauth_db.kw['bind'].connect() as connection:
            pid = await connection.scalar(text('SELECT pg_backend_pid()'))
            await connection.rollback()
            entries += 1
            if entries <= 2:
                pids.append(pid)
                await barrier.wait()
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                yield session
    async def contender():
        try:
            return await oauth_service.complete_login(independent_factory, settings, 'google', 'test-code', state, binding, None)
        except oauth_service.OAuthLoginError:
            return None
    results = await asyncio.wait_for(asyncio.gather(contender(), contender()), timeout=15)
    assert pids[0] != pids[1]
    assert sum(result is not None for result in results) == 1
    assert inspected == [True] and len(fake_provider) == 1
    assert await count_sessions(oauth_db) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,issuer', [('google', 'https://accounts.google.com'), ('kakao', 'https://kauth.kakao.com')])
async def test_known_provider_fields_are_bounded_ignored_and_issuer_checked(client, provider, issuer):
    state, _, _ = await start(client, provider)
    extras = {'iss': issuer, 'scope': 'openid profile', 'authuser': '0', 'prompt': 'consent', 'hd': 'example.test'} if provider == 'google' else {'iss': issuer}
    response = await callback(client, state, provider, **extras)
    assert response.headers['location'] == '/albums'
    state, _, _ = await start(client, provider)
    response = await callback(client, state, provider, iss='https://evil.invalid')
    assert response.headers['location'] == '/login?auth_error=failed'


@pytest.mark.asyncio
@pytest.mark.parametrize('extra', ['scope=' + 'x' * 2049, 'prompt=a&prompt=b', 'authuser=' + 'x' * 257])
async def test_known_metadata_does_not_bypass_size_or_duplicate_rules(client, fake_provider, extra):
    state, _, _ = await start(client)
    response = await client.get('/api/v1/auth/google/callback?state=' + state + '&code=test-code&' + extra)
    assert response.headers['location'] == '/login?auth_error=failed'
    assert not fake_provider


@pytest.mark.asyncio
async def test_cancel_metadata_not_echoed_and_non_cancel_error_is_generic(client, oauth_db):
    state, _, _ = await start(client)
    response = await client.get('/api/v1/auth/google/callback', params={'state': state, 'error': 'access_denied', 'error_description': 'sensitive-description', 'error_uri': 'https://evil.invalid/secret'})
    assert response.headers['location'] == '/login?auth_error=cancelled'
    assert 'sensitive-description' not in response.text + str(response.headers)
    state, _, _ = await start(client)
    response = await client.get('/api/v1/auth/google/callback', params={'state': state, 'error': 'server_error'})
    assert response.headers['location'] == '/login?auth_error=failed'
    assert await count_sessions(oauth_db) == 0


@pytest.mark.asyncio
async def test_expired_previous_session_does_not_prevent_valid_new_login(client, oauth_db):
    state, _, _ = await start(client)
    await callback(client, state)
    async with oauth_db() as session, session.begin():
        await session.execute(update(Session).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    state, _, _ = await start(client)
    assert (await callback(client, state)).headers['location'] == '/albums'
    assert (await client.get('/api/v1/me')).status_code == 200


@pytest.mark.asyncio
async def test_other_browser_failure_does_not_revoke_owner_session(client, oauth_db):
    state, _, _ = await start(client)
    await callback(client, state)
    state, _, _ = await start(client, 'kakao')
    async with httpx.AsyncClient(transport=client._transport, base_url=ORIGIN) as other:
        assert (await callback(other, state, 'kakao')).headers['location'] == '/login?auth_error=failed'
    assert (await client.get('/api/v1/me')).status_code == 200
    async with oauth_db() as session:
        assert (await session.scalar(select(Session))).revoked_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['google', 'kakao'])
async def test_service_optional_client_uses_real_adapter_with_mock_transport(oauth_db, monkeypatch, provider):
    from backend.auth import oauth_service, oauth_providers
    monkeypatch.setattr(oauth_service, 'exchange_identity', oauth_providers.exchange_identity)
    requests = []
    def transport(request):
        requests.append(request)
        if request.method == 'POST':
            return httpx.Response(200, json={'access_token': 'mock-provider-token'})
        assert request.headers['authorization'] == 'Bearer mock-provider-token'
        assert 'mock-provider-token' not in str(request.url)
        return httpx.Response(200, json={'sub': 'transport-google', 'name': 'Transport user'} if provider == 'google' else {'id': 123, 'properties': {'nickname': 'Transport user'}})
    settings = config()
    _, state, binding = await oauth_service.start_login(oauth_db, settings, provider, '/albums')
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as external:
        raw, target = await oauth_service.complete_login(oauth_db, settings, provider, 'mock-code', state, binding, None, client=external)
        assert not external.is_closed
    assert target == '/albums' and len(raw) >= 43 and len(requests) == 2
    async with oauth_db() as session:
        assert (await session.scalar(select(User))).display_name == 'Transport user'
        assert (await session.scalar(select(Session))).token_hash == token_hash(raw)


@pytest.mark.asyncio
async def test_rotation_transaction_rolls_back_user_session_and_revocation_on_failure(client, oauth_db, monkeypatch):
    from backend.auth import oauth_service
    from backend.http.errors import APIError
    state, _, _ = await start(client)
    await callback(client, state)
    old = client.cookies.get('mori_session')
    state, _, _ = await start(client, 'kakao')
    original_revoke = oauth_service.repository.revoke
    async def fail_after_revoke(session, session_id):
        await original_revoke(session, session_id)
        raise APIError(401, 'AUTH_REQUIRED')
    monkeypatch.setattr(oauth_service.repository, 'revoke', fail_after_revoke)
    response = await callback(client, state, 'kakao')
    assert response.headers['location'] == '/login?auth_error=failed'
    assert client.cookies.get('mori_session') == old
    assert (await client.get('/api/v1/me')).status_code == 200
    async with oauth_db() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 1
        assert await session.scalar(select(func.count()).select_from(AuthIdentity)) == 1
        assert await session.scalar(select(func.count()).select_from(Session)) == 1
        assert (await session.scalar(select(Session))).revoked_at is None
        assert (await session.scalar(select(OAuthLoginRequest).where(OAuthLoginRequest.state_hash == token_hash(state)))).consumed_at is not None


@pytest.mark.asyncio
async def test_insecure_cookie_allowed_only_by_existing_local_settings(oauth_db, fake_provider):
    origin = 'http://127.0.0.1:8000'
    settings = config(app_origin=origin, session_cookie_allow_insecure_local=True,
                      google_redirect_uri=origin + '/api/v1/auth/google/callback',
                      kakao_redirect_uri=origin + '/api/v1/auth/kakao/callback')
    app = create_app(settings=settings, session_factory=oauth_db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as c:
            state, _, response = await start(c)
            assert '; Secure' not in response.headers['set-cookie']
            response = await callback(c, state)
            assert all('; Secure' not in value for value in response.headers.get_list('set-cookie'))
            assert (await c.get('/api/v1/me')).status_code == 200
