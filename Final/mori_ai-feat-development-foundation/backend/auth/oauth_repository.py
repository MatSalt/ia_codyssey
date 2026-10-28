"""OAuth persistence; callers own the transaction and its commit/rollback."""
import hashlib
import re
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, text, update

from backend.auth.oauth_types import OAuthIdentity
from backend.http.errors import APIError
from backend.models import AuthIdentity, OAuthLoginRequest, User

_HASH = re.compile(r'[0-9a-f]{64}')
_RETURN_TO = re.compile(
    r'(?:/goods|/designs(?:/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})?|/albums(?:/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
    r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/(?:edit|progress|review|view))?)')


async def begin_login(session, provider: str, state_hash: str, binding_hash: str,
                      return_to: str, expires_at: datetime) -> UUID:
    if provider not in ('google', 'kakao'):
        raise ValueError('Unsupported OAuth provider')
    if not all(isinstance(value, str) and _HASH.fullmatch(value)
               for value in (state_hash, binding_hash)):
        raise ValueError('OAuth tokens must be SHA-256 hashes')
    if not isinstance(return_to, str) or not _RETURN_TO.fullmatch(return_to):
        raise ValueError('Invalid OAuth return path')
    row = OAuthLoginRequest(provider=provider, state_hash=state_hash,
                            binding_hash=binding_hash, return_to=return_to,
                            expires_at=expires_at)
    session.add(row)
    await session.flush()
    return row.id


async def consume_login(session, provider: str, state_hash: str, binding_hash: str,
                        now: datetime) -> str | None:
    # clock_timestamp() keeps a stale application/transaction clock from extending
    # validity. PostgreSQL rechecks the predicates after concurrent UPDATE waits.
    return await session.scalar(update(OAuthLoginRequest).where(
        OAuthLoginRequest.provider == provider,
        OAuthLoginRequest.state_hash == state_hash,
        OAuthLoginRequest.binding_hash == binding_hash,
        OAuthLoginRequest.consumed_at.is_(None),
        OAuthLoginRequest.expires_at > func.greatest(now, func.clock_timestamp()),
    ).values(consumed_at=func.clock_timestamp()).returning(OAuthLoginRequest.return_to))


async def resolve_identity(session, identity: OAuthIdentity) -> User:
    # A stable signed 64-bit key serializes only this provider+subject. The lock
    # lasts until the caller commits/rolls back, so a losing first login never
    # inserts an orphan User. Hash collisions merely serialize unrelated users.
    lock_key = int.from_bytes(hashlib.sha256(
        f'oauth-identity:{identity.provider}:{identity.subject}'.encode('utf-8')
    ).digest()[:8], byteorder='big', signed=True)
    await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock_key})
    user = await session.scalar(select(User).join(
        AuthIdentity, AuthIdentity.user_id == User.id
    ).where(AuthIdentity.provider == identity.provider,
            AuthIdentity.provider_subject == identity.subject).with_for_update(of=User))
    if user is not None:
        if user.deleted_at is not None:
            raise APIError(401, 'AUTH_REQUIRED')
        user.display_name = identity.display_name
    else:
        user = User(display_name=identity.display_name)
        session.add(user)
        await session.flush()
        session.add(AuthIdentity(provider=identity.provider,
                                 provider_subject=identity.subject, user_id=user.id))
    await session.flush()
    return user


async def prune_login_requests(session, now: datetime) -> int:
    result = await session.execute(delete(OAuthLoginRequest).where(
        OAuthLoginRequest.expires_at <= now))
    return result.rowcount
