"""Real PostgreSQL OAuth persistence, including independent-connection races."""
import asyncio
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text, update

from backend.http.errors import APIError
from backend.http.security import token_hash
from backend.models import AuthIdentity, User


@pytest_asyncio.fixture
async def oauth_db(db):
    from backend.models import OAuthLoginRequest
    # users CASCADE does not include this deliberately independent table.
    async with db() as session, session.begin():
        await session.execute(delete(OAuthLoginRequest))
    yield db
    async with db() as session, session.begin():
        await session.execute(delete(OAuthLoginRequest))


async def begin(factory, *, expires=None, return_to='/albums'):
    from backend.auth.oauth_repository import begin_login
    async with factory() as session, session.begin():
        return await begin_login(session, 'google', token_hash('state'), token_hash('binding'),
                                 return_to, expires or datetime.now(timezone.utc) + timedelta(minutes=10))


async def consume(factory, *, provider='google', state='state', binding='binding', now=None):
    from backend.auth.oauth_repository import consume_login
    async with factory() as session, session.begin():
        return await consume_login(session, provider, token_hash(state), token_hash(binding),
                                   now or datetime.now(timezone.utc))


@pytest.mark.parametrize('provider,subject', [('other', 'id'), ('google', ''), ('kakao', 'x' * 256), ('google', None)])
def test_identity_rejects_invalid_provider_or_subject(provider, subject):
    from backend.auth.oauth_types import OAuthIdentity
    with pytest.raises(ValueError):
        OAuthIdentity(provider, subject, 'name')


def test_identity_is_frozen_and_bounds_display_name():
    from backend.auth.oauth_types import OAuthIdentity
    identity = OAuthIdentity('google', 'x' * 255, 'n' * 101)
    assert identity.display_name == 'n' * 100
    assert OAuthIdentity('kakao', '1', '').display_name == '사용자'
    with pytest.raises(FrozenInstanceError):
        identity.subject = 'changed'


@pytest.mark.asyncio
async def test_login_stores_hashes_and_consumes_once(oauth_db):
    from backend.models import OAuthLoginRequest
    request_id = await begin(oauth_db)
    assert isinstance(request_id, UUID)
    async with oauth_db() as session:
        row = await session.get(OAuthLoginRequest, request_id)
        assert row.state_hash == token_hash('state')
        assert row.binding_hash == token_hash('binding')
        assert row.consumed_at is None
    assert await consume(oauth_db) == '/albums'
    assert await consume(oauth_db) is None
    async with oauth_db() as session:
        assert (await session.get(OAuthLoginRequest, request_id)).consumed_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [{'provider': 'kakao'}, {'binding': 'wrong'}, {'state': 'wrong'}])
async def test_mismatch_does_not_consume_valid_request(oauth_db, changes):
    await begin(oauth_db)
    assert await consume(oauth_db, **changes) is None
    assert await consume(oauth_db) == '/albums'


@pytest.mark.asyncio
async def test_expired_request_rejected_even_with_stale_caller_clock(oauth_db):
    now = datetime.now(timezone.utc)
    await begin(oauth_db, expires=now - timedelta(seconds=1))
    assert await consume(oauth_db, now=now - timedelta(days=1)) is None


@pytest.mark.asyncio
async def test_expiry_boundary_is_exclusive(oauth_db):
    boundary = datetime.now(timezone.utc) + timedelta(minutes=10)
    await begin(oauth_db, expires=boundary)
    assert await consume(oauth_db, now=boundary) is None


@pytest.mark.asyncio
async def test_simultaneous_consumers_on_different_connections_have_one_winner(oauth_db):
    from backend.auth.oauth_repository import consume_login
    await begin(oauth_db)
    async with oauth_db() as first, oauth_db() as second:
        # Force distinct checked-out connections before racing the UPDATE.
        assert await first.scalar(text('SELECT pg_backend_pid()')) != await second.scalar(text('SELECT pg_backend_pid()'))
        async def attempt(session):
            result = await consume_login(session, 'google', token_hash('state'), token_hash('binding'), datetime.now(timezone.utc))
            await session.commit()
            return result
        results = await asyncio.wait_for(asyncio.gather(attempt(first), attempt(second)), timeout=10)
    assert results.count('/albums') == 1
    assert results.count(None) == 1


@pytest.mark.asyncio
async def test_prune_removes_expired_consumed_and_failed_requests(oauth_db):
    from backend.auth.oauth_repository import begin_login, consume_login, prune_login_requests
    from backend.models import OAuthLoginRequest
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    async with oauth_db() as session, session.begin():
        for state in ['used', 'failed', 'live']:
            await begin_login(session, 'google', token_hash(state), token_hash('binding'), '/albums', future)
        assert await consume_login(session, 'google', token_hash('used'), token_hash('binding'), datetime.now(timezone.utc)) == '/albums'
        await session.execute(update(OAuthLoginRequest).where(OAuthLoginRequest.state_hash != token_hash('live')).values(expires_at=future - timedelta(seconds=1)))
        assert await prune_login_requests(session, future - timedelta(seconds=1)) == 2
        assert await prune_login_requests(session, future - timedelta(seconds=1)) == 0
        assert await session.scalar(select(func.count()).select_from(OAuthLoginRequest)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('return_to', ['https://evil.test', '//evil.test', '/albums?x=1', '/albums#x', '/albums\\evil', '/%61lbums', '/albums/../login', '/albums\n'])
async def test_begin_rejects_unsafe_return_to(oauth_db, return_to):
    with pytest.raises(ValueError):
        await begin(oauth_db, return_to=return_to)


@pytest.mark.asyncio
@pytest.mark.parametrize('suffix', ['edit', 'progress', 'review', 'view'])
async def test_internal_album_return_to_roundtrips(oauth_db, suffix):
    target = f'/albums/12345678-1234-1234-1234-123456789abc/{suffix}'
    await begin(oauth_db, return_to=target)
    assert await consume(oauth_db) == target


@pytest.mark.asyncio
async def test_same_identity_race_creates_one_user_without_orphans(oauth_db):
    from backend.auth.oauth_repository import resolve_identity
    from backend.auth.oauth_types import OAuthIdentity
    async with oauth_db() as first, oauth_db() as second:
        assert await first.scalar(text('SELECT pg_backend_pid()')) != await second.scalar(text('SELECT pg_backend_pid()'))
        async def resolve(session):
            user = await resolve_identity(session, OAuthIdentity('google', 'same-subject', 'name'))
            user_id = user.id
            await session.commit()
            return user_id
        results = await asyncio.wait_for(asyncio.gather(resolve(first), resolve(second)), timeout=10)
    assert results[0] == results[1]
    async with oauth_db() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 1
        assert await session.scalar(select(func.count()).select_from(AuthIdentity)) == 1


@pytest.mark.asyncio
async def test_relogin_updates_name_but_other_provider_remains_separate(oauth_db):
    from backend.auth.oauth_repository import resolve_identity
    from backend.auth.oauth_types import OAuthIdentity
    async with oauth_db() as session, session.begin():
        first = await resolve_identity(session, OAuthIdentity('google', '123', 'before'))
        same = await resolve_identity(session, OAuthIdentity('google', '123', 'after'))
        other = await resolve_identity(session, OAuthIdentity('kakao', '123', 'after'))
        assert first.id == same.id
        assert same.display_name == 'after'
        assert other.id != first.id
        assert await session.scalar(select(func.count()).select_from(User)) == 2


@pytest.mark.asyncio
async def test_deleted_identity_cannot_reactivate_or_create_replacement(oauth_db):
    from backend.auth.oauth_repository import resolve_identity
    from backend.auth.oauth_types import OAuthIdentity
    identity = OAuthIdentity('google', 'deleted', 'before')
    async with oauth_db() as session, session.begin():
        user = await resolve_identity(session, identity)
        user.deleted_at = datetime.now(timezone.utc)
        user_id = user.id
    with pytest.raises(APIError) as error:
        async with oauth_db() as session, session.begin():
            await resolve_identity(session, OAuthIdentity('google', 'deleted', 'after'))
    assert (error.value.status, error.value.code) == (401, 'AUTH_REQUIRED')
    async with oauth_db() as session:
        user = await session.get(User, user_id)
        assert user.deleted_at is not None
        assert user.display_name == 'before'
        assert await session.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.asyncio
async def test_consumption_rolls_back_with_owning_transaction(oauth_db):
    from backend.auth.oauth_repository import consume_login
    await begin(oauth_db)
    async with oauth_db() as session:
        assert await consume_login(session, 'google', token_hash('state'), token_hash('binding'), datetime.now(timezone.utc)) == '/albums'
        await session.rollback()
    assert await consume(oauth_db) == '/albums'


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,state_hash,binding_hash', [
    ('other', 'a' * 64, 'b' * 64), ('google', 'raw-state', 'b' * 64),
    ('kakao', 'a' * 64, 'raw-binding'),
])
async def test_begin_rejects_provider_and_non_hash_tokens(oauth_db, provider, state_hash, binding_hash):
    from backend.auth.oauth_repository import begin_login
    with pytest.raises(ValueError):
        async with oauth_db() as session, session.begin():
            await begin_login(session, provider, state_hash, binding_hash, '/albums', datetime.now(timezone.utc) + timedelta(minutes=10))
