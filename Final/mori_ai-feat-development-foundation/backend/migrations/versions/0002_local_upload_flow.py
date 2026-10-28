"""Local authentication and upload HTTP persistence; 0001 remains frozen."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0002_local_upload_flow'
down_revision = '0001_workflow_foundation'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('dev_account', sa.String(20), nullable=True))
    op.create_unique_constraint('uq_users_dev_account', 'users', ['dev_account'])
    op.create_table('auth_identities',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('user_id', UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('provider', sa.String(20), nullable=False),
        sa.Column('provider_subject', sa.Text(), nullable=False),
        sa.UniqueConstraint('provider', 'provider_subject'),
        sa.CheckConstraint("provider IN ('google','kakao')"))
    op.create_index('ix_auth_identities_user_id', 'auth_identities', ['user_id'])
    op.create_table('sessions',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('user_id', UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True)))
    op.create_index('ix_sessions_user_id', 'sessions', ['user_id'])
    op.create_index('ix_sessions_expires_at', 'sessions', ['expires_at'])
    op.create_table('consents',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('user_id', UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('policy_version', sa.String(100), nullable=False),
        sa.Column('purpose', sa.String(50), nullable=False),
        sa.Column('agreed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('user_id', 'policy_version', 'purpose'),
        sa.CheckConstraint("purpose = 'photo_upload_and_ai_processing'"))
    op.create_table('idempotency_records',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('owner_id', UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('operation', sa.Text(), nullable=False),
        sa.Column('resource_id', UUID()),
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('http_status', sa.Integer(), nullable=False),
        sa.Column('response_body', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('owner_id', 'operation', 'key'))
    for column in [
        sa.Column('order_mode', sa.String(10), nullable=False, server_default='date'),
        sa.Column('next_selection_index', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('cover_page_id', UUID()), sa.Column('active_run_id', UUID()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('published_at', sa.DateTime(timezone=True)),
    ]:
        op.add_column('albums', column)
    op.create_foreign_key('fk_album_cover', 'albums', 'album_pages', ['cover_page_id'], ['id'])
    op.create_foreign_key('fk_album_active_run', 'albums', 'generation_runs', ['active_run_id'], ['id'])
    for name in ['source', 'normalized', 'thumbnail']:
        op.add_column('album_pages', sa.Column(f'{name}_asset_id', UUID()))
        op.create_foreign_key(f'fk_page_{name}', 'album_pages', 'media_assets', [f'{name}_asset_id'], ['id'])
    for column in [
        sa.Column('input_is_3_4', sa.Boolean()), sa.Column('ai_caption', sa.Text()),
        sa.Column('caption_edited_at', sa.DateTime(timezone=True)),
        sa.Column('captured_at_raw', sa.Text()), sa.Column('captured_timezone', sa.String(100)),
        sa.Column('sort_date', sa.String(19)), sa.Column('sort_date_source', sa.String(30)),
    ]:
        op.add_column('album_pages', column)
    op.add_column('upload_sessions', sa.Column('file_last_modified_at', sa.DateTime(timezone=True)))
    op.add_column('upload_sessions', sa.Column('validation_config', JSONB()))
    op.add_column('generation_runs', sa.Column('started_at', sa.DateTime(timezone=True)))
    op.add_column('generation_runs', sa.Column('finished_at', sa.DateTime(timezone=True)))


def downgrade():
    for name in ['started_at', 'finished_at']:
        op.drop_column('generation_runs', name)
    op.drop_column('upload_sessions', 'file_last_modified_at')
    op.drop_column('upload_sessions', 'validation_config')
    for name in ['input_is_3_4', 'ai_caption', 'caption_edited_at', 'captured_at_raw', 'captured_timezone', 'sort_date', 'sort_date_source']:
        op.drop_column('album_pages', name)
    for name in ['source', 'normalized', 'thumbnail']:
        op.drop_constraint(f'fk_page_{name}', 'album_pages', type_='foreignkey')
        op.drop_column('album_pages', f'{name}_asset_id')
    op.drop_constraint('fk_album_cover', 'albums', type_='foreignkey')
    op.drop_constraint('fk_album_active_run', 'albums', type_='foreignkey')
    for name in ['order_mode', 'next_selection_index', 'cover_page_id', 'active_run_id', 'updated_at', 'published_at']:
        op.drop_column('albums', name)
    for name in ['idempotency_records', 'consents', 'sessions', 'auth_identities']:
        op.drop_table(name)
    op.drop_constraint('uq_users_dev_account', 'users', type_='unique')
    op.drop_column('users', 'dev_account')
