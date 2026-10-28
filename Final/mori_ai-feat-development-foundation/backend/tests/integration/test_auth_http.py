"""Real HTTP/PG coverage: opt-in, secret persistence, CSRF, consent and isolation."""
import hashlib
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import select, text

from backend.main import create_app
from backend.settings import Settings

ORIGIN = 'http://127.0.0.1:8000'


def config(**kwargs):
    return Settings(database_url=os.environ['DATABASE_URL'], app_env='local',
                    dev_auth_enabled=True, session_cookie_allow_insecure_local=True,
                    app_origin=ORIGIN, **kwargs)


@pytest_asyncio.fixture
async def client(db):
    app = create_app(settings=config(), session_factory=db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as c:
            yield c


async def login(client, account='alpha'):
    response = await client.post('/api/dev/login', json={'account': account}, headers={'Origin': ORIGIN})
    assert response.status_code == 204
    me = await client.get('/api/v1/me')
    assert me.status_code == 200
    return me.json()['data']


@pytest.mark.asyncio
async def test_dev_route_default_off(db):
    app = create_app(settings=Settings(database_url=os.environ['DATABASE_URL']), session_factory=db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as c:
            assert (await c.post('/api/dev/login', json={'account': 'alpha'}, headers={'Origin': ORIGIN})).status_code == 404
            assert (await c.get('/api/dev/config')).json()['data'] == {'dev_auth_enabled': False, 'dev_ai_enabled': False, 'generation_enabled': False, 'generation_mode': None}


@pytest.mark.parametrize('values', [
    {'app_env': 'production', 'dev_auth_enabled': True},
    {'app_env': 'production', 'session_cookie_allow_insecure_local': True},
    {'app_origin': '*'}, {'app_origin': 'http://localhost:8000/path'},
])
def test_reject_unsafe_settings(values):
    with pytest.raises(ValidationError):
        Settings(database_url=os.environ['DATABASE_URL'], **values)


@pytest.mark.asyncio
async def test_login_origin_validation_and_unknown_account(client):
    for origin in [None, 'http://evil.invalid', ORIGIN + '/']:
        headers = {} if origin is None else {'Origin': origin}
        assert (await client.post('/api/dev/login', json={'account': 'alpha'}, headers=headers)).status_code == 403
    for body in [{'account': 'google'}, {'account': 'alpha', 'email': 'x'}, {'account': 'alpha', 'csrf_token': 'x'}]:
        assert (await client.post('/api/dev/login', json=body, headers={'Origin': ORIGIN})).status_code == 422


@pytest.mark.asyncio
async def test_cookie_hash_me_no_store_request_ids(client, db):
    response = await client.post('/api/dev/login', json={'account': 'alpha'}, headers={'Origin': ORIGIN})
    assert response.status_code == 204 and not response.content
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie and 'Path=/' in cookie and 'Max-Age=86400' in cookie
    raw = client.cookies.get('mori_session')
    assert raw and len(raw) >= 32
    async with db() as s:
        row = (await s.execute(text('SELECT token_hash, expires_at, revoked_at FROM sessions'))).one()
        assert row.token_hash == hashlib.sha256(raw.encode()).hexdigest() and row.token_hash != raw
        assert row.revoked_at is None
        assert 86390 < (row.expires_at - datetime.now(timezone.utc)).total_seconds() <= 86400
    a, b = await client.get('/api/v1/me'), await client.get('/api/v1/me')
    assert a.headers['cache-control'] == 'no-store'
    assert a.json()['request_id'] != b.json()['request_id']
    assert raw not in a.text
    assert a.json()['data']['consent']['required'] is True
    assert len(a.json()['data']['csrf_token']) == 64


@pytest.mark.asyncio
async def test_consent_csrf_validation_idempotence_and_account_isolation(client, db):
    alpha = await login(client)
    body = {'policy_version': alpha['consent']['policy_version'], 'purpose': 'photo_upload_and_ai_processing', 'agreed': True}
    headers = {'Origin': ORIGIN, 'X-CSRF-Token': alpha['csrf_token']}
    for h in [{}, {'Origin': ORIGIN}, {'X-CSRF-Token': alpha['csrf_token']}, {**headers, 'Origin': 'http://evil.invalid'}, {**headers, 'X-CSRF-Token': 'wrong'}]:
        r = await client.post('/api/v1/consents', json=body, headers=h)
        assert r.status_code == 403 and r.json()['error']['code'] == 'CSRF_INVALID'
    for bad in [{**body, 'policy_version': 'wrong'}, {**body, 'agreed': False}, {**body, 'agreed': 1}, {**body, 'unknown': True}, {**body, 'purpose': 'other'}]:
        r = await client.post('/api/v1/consents', json=bad, headers=headers)
        assert r.status_code == 422 and r.json()['error']['code'] == 'VALIDATION_ERROR'
    first = await client.post('/api/v1/consents', json=body, headers=headers)
    second = await client.post('/api/v1/consents', json=body, headers=headers)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()['data'] == second.json()['data']
    assert first.json()['request_id'] != second.json()['request_id']
    assert (await client.get('/api/v1/me')).json()['data']['consent']['required'] is False
    beta = await login(client, 'beta')
    assert alpha['user']['id'] != beta['user']['id'] and beta['consent']['required'] is True
    assert (await client.post('/api/v1/consents', json=body, headers=headers)).status_code == 403
    async with db() as s:
        assert await s.scalar(text('SELECT count(*) FROM consents')) == 1
        assert await s.scalar(text('SELECT count(*) FROM auth_identities')) == 0


@pytest.mark.asyncio
async def test_expiration_and_logout_revoke(client, db):
    me = await login(client)
    raw = client.cookies.get('mori_session')
    headers = {'Origin': ORIGIN, 'X-CSRF-Token': me['csrf_token']}
    assert (await client.post('/api/v1/auth/logout', json={'extra': 1}, headers=headers)).status_code == 422
    assert (await client.post('/api/v1/auth/logout', json={}, headers={})).status_code == 403
    out = await client.post('/api/v1/auth/logout', json={}, headers=headers)
    assert out.status_code == 204 and out.headers['cache-control'] == 'no-store'
    client.cookies.set('mori_session', raw)
    assert (await client.get('/api/v1/me')).status_code == 401
    client.cookies.clear()
    await login(client)
    async with db() as s, s.begin():
        await s.execute(text("UPDATE sessions SET expires_at=now()-interval '1 second'"))
    r = await client.get('/api/v1/me')
    assert r.status_code == 401 and r.json()['error']['code'] == 'AUTH_REQUIRED'


@pytest.mark.asyncio
async def test_public_config_and_unauthenticated_envelope(client):
    r = await client.get('/api/v1/me')
    assert r.status_code == 401 and r.headers['cache-control'] == 'no-store'
    r = await client.get('/api/v1/client-config')
    assert r.status_code == 200 and r.json()['data']['upload_max_file_bytes'] == 20971520
    assert 'dev_auth_enabled' not in r.json()['data']
    assert (await client.get('/api/dev/config')).json()['data'] == {'dev_auth_enabled': True, 'dev_ai_enabled': False, 'generation_enabled': False, 'generation_mode': None}


@pytest.mark.asyncio
async def test_concurrent_synthetic_login_and_consent_use_two_connections(db):
    """Unique constraints must converge competing independent transactions."""
    import asyncio
    from backend.auth import repository
    from backend.models import User, Consent
    barrier = asyncio.Barrier(2)

    async def contender():
        async with db() as s, s.begin():
            pid = await s.scalar(text('SELECT pg_backend_pid()'))
            await barrier.wait()
            user = await repository.synthetic_user(s, 'alpha')
            consent, created = await repository.agree(s, user.id, 'local-2026-10-16', 'photo_upload_and_ai_processing')
            return pid, user.id, consent.id, created

    a, b = await asyncio.wait_for(asyncio.gather(contender(), contender()), timeout=10)
    assert a[0] != b[0] and a[1:3] == b[1:3]
    assert sorted([a[3], b[3]]) == [False, True]
    async with db() as s:
        assert len((await s.scalars(select(User))).all()) == 1
        assert len((await s.scalars(select(Consent))).all()) == 1


@pytest.mark.asyncio
async def test_secure_cookie_default_and_deleted_user_denied(db):
    from backend.models import User
    settings = Settings(database_url=os.environ['DATABASE_URL'], app_env='local', dev_auth_enabled=True,
                        app_origin='https://mori.invalid')
    app = create_app(settings=settings, session_factory=db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://mori.invalid') as c:
            response = await c.post('/api/dev/login', json={'account': 'alpha'}, headers={'Origin': 'https://mori.invalid'})
            assert response.status_code == 204 and '; Secure' in response.headers['set-cookie']
            assert (await c.get('/api/v1/me')).status_code == 200
            async with db() as s, s.begin():
                from sqlalchemy import update
                await s.execute(update(User).values(deleted_at=datetime.now(timezone.utc)))
            assert (await c.get('/api/v1/me')).status_code == 401


@pytest.mark.asyncio
async def test_production_route_disabled_before_body_validation(db):
    app = create_app(settings=Settings(database_url=os.environ['DATABASE_URL'], app_env='production'), session_factory=db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as c:
            response = await c.post('/api/dev/login', json={'account': 'unknown', 'injected': True})
            assert response.status_code == 404
            assert response.json()['error']['code'] == 'RESOURCE_NOT_FOUND'
            assert response.headers['cache-control'] == 'no-store'
            assert 'set-cookie' not in response.headers


@pytest.mark.asyncio
async def test_media_policy_requires_new_consent(client, db):
    """Old agreement cannot silently authorize the changed media-retention notice."""
    from uuid import UUID
    from backend.auth.repository import agree
    me = await login(client)
    async with db() as session, session.begin():
        await agree(session, UUID(me['user']['id']), 'local-2026-10-16', 'photo_upload_and_ai_processing')
    current = (await client.get('/api/v1/me')).json()['data']
    assert current['consent']['required'] is True
    assert current['consent']['policy_version'] == 'media-2026-10-18'
    assert '원본 파일의 별도 보관은 보장하지 않습니다' in current['consent']['notice']
    headers = {'Origin': ORIGIN, 'X-CSRF-Token': current['csrf_token']}
    body = {'policy_version':'local-2026-10-16', 'purpose':'photo_upload_and_ai_processing', 'agreed':True}
    assert (await client.post('/api/v1/consents', json=body, headers=headers)).status_code == 422
    body['policy_version'] = current['consent']['policy_version']
    assert (await client.post('/api/v1/consents', json=body, headers=headers)).status_code == 201
    assert (await client.get('/api/v1/me')).json()['data']['consent']['required'] is False
    async with db() as session:
        assert await session.scalar(text('SELECT count(*) FROM consents')) == 2
