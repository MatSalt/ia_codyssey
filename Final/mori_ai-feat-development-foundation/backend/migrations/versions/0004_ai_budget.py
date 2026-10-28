"""Persistent validation spending, independent of deletable product records."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0004_ai_budget'
down_revision = '0003_real_oauth'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ai_budget_accounts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('blocked', sa.Boolean(), nullable=False, server_default='false'),
        sa.CheckConstraint('id = 1'))
    op.create_table('ai_budget_entries',
        sa.Column('attempt_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('reserved_usd', sa.Numeric(), nullable=False),
        sa.Column('actual_usd', sa.Numeric(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('usage', JSONB(), nullable=True),
        sa.Column('provider_request_id', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint('reserved_usd > 0'),
        sa.CheckConstraint('actual_usd IS NULL OR actual_usd >= 0'),
        sa.CheckConstraint("status IN ('reserved','unknown','settled','released')"))


def downgrade():
    op.drop_table('ai_budget_entries')
    op.drop_table('ai_budget_accounts')
