"""Authentication persistence. Insert conflicts converge without losing history."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select, update, func
from sqlalchemy.dialects.postgresql import insert
from backend.models import User, Session, Consent


async def synthetic_user(session, account):
    await session.execute(insert(User).values(id=uuid4(), dev_account=account, display_name=f'개발 {account}').on_conflict_do_nothing(index_elements=[User.dev_account]))
    return await session.scalar(select(User).where(User.dev_account == account, User.deleted_at.is_(None)))


async def save_session(session, user_id, hashed, expires_at):
    row = Session(user_id=user_id, token_hash=hashed, expires_at=expires_at)
    session.add(row)
    await session.flush()
    return row


async def find_session(session, hashed):
    return await session.scalar(select(Session).join(User, User.id == Session.user_id).where(
        Session.token_hash == hashed, Session.revoked_at.is_(None),
        Session.expires_at > func.now(), User.deleted_at.is_(None)))


async def user_by_id(session, user_id):
    return await session.get(User, user_id)


async def get_consent(session, user_id, policy_version):
    return await session.scalar(select(Consent).where(Consent.user_id == user_id,
        Consent.policy_version == policy_version, Consent.purpose == 'photo_upload_and_ai_processing'))


async def agree(session, user_id, policy_version, purpose):
    inserted = await session.scalar(insert(Consent).values(id=uuid4(), user_id=user_id,
        policy_version=policy_version, purpose=purpose).on_conflict_do_nothing(
        index_elements=[Consent.user_id, Consent.policy_version, Consent.purpose]).returning(Consent.id))
    return await get_consent(session, user_id, policy_version), inserted is not None


async def revoke(session, session_id):
    await session.execute(update(Session).where(Session.id == session_id).values(revoked_at=datetime.now(timezone.utc)))
