"""One-use OAuth browser requests; existing auth identities remain unchanged."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0003_real_oauth'
down_revision = '0002_local_upload_flow'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('oauth_login_requests',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('provider', sa.String(20), nullable=False),
        sa.Column('state_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('binding_hash', sa.String(64), nullable=False),
        sa.Column('return_to', sa.String(255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("provider IN ('google','kakao')"))
    op.create_index('ix_oauth_login_requests_expires_at', 'oauth_login_requests', ['expires_at'])


def downgrade():
    op.drop_index('ix_oauth_login_requests_expires_at', table_name='oauth_login_requests')
    op.drop_table('oauth_login_requests')
