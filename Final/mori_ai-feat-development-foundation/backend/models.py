"""Shared workflow and local HTTP persistence models."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Identity:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class Created:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text('now()'))


class User(Identity, Created, Base):
    __tablename__ = 'users'
    dev_account: Mapped[str | None] = mapped_column(String(20), unique=True)
    display_name: Mapped[str] = mapped_column(String(100), default='test')
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Album(Identity, Created, Base):
    __tablename__ = 'albums'
    owner_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'))
    order_mode: Mapped[str] = mapped_column(String(10), server_default='date')
    next_selection_index: Mapped[int] = mapped_column(server_default='1')
    cover_page_id: Mapped[UUID | None] = mapped_column(ForeignKey('album_pages.id', use_alter=True, name='fk_album_cover'))
    active_run_id: Mapped[UUID | None] = mapped_column(ForeignKey('generation_runs.id', use_alter=True, name='fk_album_active_run'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text('now()'))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title: Mapped[str] = mapped_column(Text, default='나의 사진첩')
    status: Mapped[str] = mapped_column(String(30), default='draft')
    version: Mapped[int] = mapped_column(default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Page(Identity, Base):
    __tablename__ = 'album_pages'
    album_id: Mapped[UUID] = mapped_column(ForeignKey('albums.id'))
    source_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey('media_assets.id', use_alter=True, name='fk_page_source'))
    normalized_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey('media_assets.id', use_alter=True, name='fk_page_normalized'))
    thumbnail_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey('media_assets.id', use_alter=True, name='fk_page_thumbnail'))
    input_is_3_4: Mapped[bool | None] = mapped_column(Boolean)
    ai_caption: Mapped[str | None] = mapped_column(Text)
    caption_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at_raw: Mapped[str | None] = mapped_column(Text)
    captured_timezone: Mapped[str | None] = mapped_column(String(100))
    sort_date: Mapped[str | None] = mapped_column(String(19))
    sort_date_source: Mapped[str | None] = mapped_column(String(30))
    position: Mapped[int] = mapped_column(default=1)
    selection_index: Mapped[int] = mapped_column(default=1)
    version: Mapped[int] = mapped_column(default=1)
    result_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey('media_assets.id', use_alter=True, name='fk_page_result'))
    caption_text: Mapped[str | None] = mapped_column(Text)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index('uq_page_position', 'album_id', 'position', unique=True, postgresql_where=text('removed_at IS NULL')), UniqueConstraint('album_id', 'selection_index'))


class MediaAsset(Identity, Created, Base):
    __tablename__ = 'media_assets'
    owner_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'))
    album_id: Mapped[UUID] = mapped_column(ForeignKey('albums.id'))
    page_id: Mapped[UUID] = mapped_column(ForeignKey('album_pages.id'))
    role: Mapped[str] = mapped_column(String(30))
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    mime: Mapped[str] = mapped_column(String(100))
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default='pending')
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Upload(Identity, Created, Base):
    __tablename__ = 'upload_sessions'
    album_id: Mapped[UUID] = mapped_column(ForeignKey('albums.id'))
    page_id: Mapped[UUID] = mapped_column(ForeignKey('album_pages.id'))
    asset_id: Mapped[UUID] = mapped_column(ForeignKey('media_assets.id'))
    batch_id: Mapped[UUID]
    client_file_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(30), default='reserved')
    file_last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declared_bytes: Mapped[int] = mapped_column(BigInteger)
    validation_config: Mapped[dict | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (UniqueConstraint('batch_id', 'client_file_id'),)


class Run(Identity, Created, Base):
    __tablename__ = 'generation_runs'
    album_id: Mapped[UUID] = mapped_column(ForeignKey('albums.id'))
    status: Mapped[str] = mapped_column(String(30), default='queued')
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_version: Mapped[int] = mapped_column(default=1)
    input_snapshot: Mapped[list] = mapped_column(JSONB, default=list)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (Index('uq_active_run', 'album_id', unique=True, postgresql_where=text("status IN ('queued','running','action_required')")),)


class Task(Identity, Base):
    __tablename__ = 'generation_tasks'
    run_id: Mapped[UUID] = mapped_column(ForeignKey('generation_runs.id'))
    page_id: Mapped[UUID] = mapped_column(ForeignKey('album_pages.id'))
    stage: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default='queued')
    output_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey('media_assets.id'))
    output_caption: Mapped[str | None] = mapped_column(Text)
    completion_kind: Mapped[str | None] = mapped_column(String(30))
    attempt_count: Mapped[int] = mapped_column(default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fence_version: Mapped[int] = mapped_column(default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    safe_to_retry: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_ai_call: Mapped[bool] = mapped_column(Boolean, default=True)
    has_persisted_input: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint('run_id', 'page_id', 'stage'), CheckConstraint("stage IN ('caption','image_transform','optimize')"))


class Attempt(Identity, Created, Base):
    __tablename__ = 'task_attempts'
    task_id: Mapped[UUID] = mapped_column(ForeignKey('generation_tasks.id'))
    attempt_no: Mapped[int]
    fence_version: Mapped[int]
    provider_request_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default='prepared')
    dispatch_state: Mapped[str] = mapped_column(String(30), default='not_sent')
    output_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey('media_assets.id'))
    output_caption: Mapped[str | None] = mapped_column(Text)
    result_key: Mapped[str | None] = mapped_column(Text)
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    usage: Mapped[dict | None] = mapped_column(JSONB)
    estimated_cost: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(100))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('task_id', 'attempt_no'),)


class Outbox(Identity, Created, Base):
    __tablename__ = 'outbox_events'
    event_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[UUID]
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Identity, Created, Base):
    __tablename__ = 'background_jobs'
    kind: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(30), default='queued')
    attempt_count: Mapped[int] = mapped_column(default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fence_version: Mapped[int] = mapped_column(default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('kind', 'target_id'),)


class AuthIdentity(Identity, Base):
    __tablename__ = 'auth_identities'
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    provider_subject: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint('provider', 'provider_subject'), CheckConstraint("provider IN ('google','kakao')"))


class OAuthLoginRequest(Identity, Base):
    __tablename__ = 'oauth_login_requests'
    provider: Mapped[str] = mapped_column(String(20))
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    binding_hash: Mapped[str] = mapped_column(String(64))
    return_to: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("provider IN ('google','kakao')"),)


class Session(Identity, Base):
    __tablename__ = 'sessions'
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Consent(Identity, Base):
    __tablename__ = 'consents'
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'))
    policy_version: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(50))
    agreed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text('now()'))
    __table_args__ = (UniqueConstraint('user_id', 'policy_version', 'purpose'), CheckConstraint("purpose = 'photo_upload_and_ai_processing'"))


class IdempotencyRecord(Identity, Created, Base):
    __tablename__ = 'idempotency_records'
    owner_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'))
    operation: Mapped[str] = mapped_column(Text)
    resource_id: Mapped[UUID | None]
    key: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(String(64))
    http_status: Mapped[int]
    response_body: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint('owner_id', 'operation', 'key'),)


class AIBudgetAccount(Base):
    """Singleton serialization point; overruns require explicit operator review."""
    __tablename__ = 'ai_budget_accounts'
    id: Mapped[int] = mapped_column(primary_key=True)
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='false')
    __table_args__ = (CheckConstraint('id = 1'),)


class AIBudgetEntry(Created, Base):
    """Financial records deliberately have no product-data foreign keys."""
    __tablename__ = 'ai_budget_entries'
    attempt_id: Mapped[UUID] = mapped_column(primary_key=True)
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    actual_usd: Mapped[Decimal | None] = mapped_column(Numeric)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    usage: Mapped[dict | None] = mapped_column(JSONB)
    provider_request_id: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint('reserved_usd > 0'),
        CheckConstraint('actual_usd IS NULL OR actual_usd >= 0'),
        CheckConstraint("status IN ('reserved','unknown','settled','released')"),
    )


class GoodsWork(Identity, Created, Base):
    __tablename__='goods_work'
    owner_id: Mapped[UUID]=mapped_column(ForeignKey('users.id'),index=True)
    status: Mapped[str]=mapped_column(String(20),default='active')
    source_key: Mapped[str|None]=mapped_column(Text)
    source_hash: Mapped[str|None]=mapped_column(String(64))
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)

class GoodsRevision(Identity, Created, Base):
    __tablename__='goods_revisions'
    work_id: Mapped[UUID]=mapped_column(ForeignKey('goods_work.id'),index=True)
    parent_id: Mapped[UUID|None]=mapped_column(ForeignKey('goods_revisions.id'))
    request_key: Mapped[str]=mapped_column(Text)
    request_hash: Mapped[str]=mapped_column(String(64))
    style: Mapped[str]=mapped_column(String(30))
    message: Mapped[str]=mapped_column(Text)
    prompt: Mapped[str]=mapped_column(Text)
    config: Mapped[dict]=mapped_column(JSONB,default=dict)
    status: Mapped[str]=mapped_column(String(20),default='queued')
    result_key: Mapped[str|None]=mapped_column(Text)
    error_code: Mapped[str|None]=mapped_column(String(50))
    lease_until: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    __table_args__=(UniqueConstraint('work_id','request_key'),)

class GoodsDesign(Identity, Created, Base):
    __tablename__='goods_designs'
    owner_id: Mapped[UUID]=mapped_column(ForeignKey('users.id'),index=True)
    work_id: Mapped[UUID]=mapped_column(ForeignKey('goods_work.id'),unique=True)
    revision_id: Mapped[UUID]=mapped_column(ForeignKey('goods_revisions.id'))
    placement: Mapped[dict]=mapped_column(JSONB)
    album_id: Mapped[UUID|None]=mapped_column(ForeignKey('albums.id'))
    version: Mapped[int]=mapped_column(Integer,default=1)
    production_started_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
