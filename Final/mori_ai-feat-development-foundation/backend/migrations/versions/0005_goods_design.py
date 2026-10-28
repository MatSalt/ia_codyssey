"""Temporary goods work and completed designs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
revision='0005_goods_design'
down_revision='0004_ai_budget'
branch_labels=None
depends_on=None

def ident():
    return [sa.Column('id',UUID(as_uuid=True),primary_key=True),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('now()'))]

def upgrade():
    op.create_table('goods_work',*ident(),sa.Column('owner_id',UUID(as_uuid=True),sa.ForeignKey('users.id'),nullable=False),sa.Column('status',sa.String(20),nullable=False),sa.Column('source_key',sa.Text()),sa.Column('source_hash',sa.String(64)),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_goods_work_owner_id','goods_work',['owner_id']);op.create_index('ix_goods_work_expires_at','goods_work',['expires_at'])
    op.create_table('goods_revisions',*ident(),sa.Column('work_id',UUID(as_uuid=True),sa.ForeignKey('goods_work.id'),nullable=False),sa.Column('parent_id',UUID(as_uuid=True),sa.ForeignKey('goods_revisions.id')),sa.Column('request_key',sa.Text(),nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),sa.Column('style',sa.String(30),nullable=False),sa.Column('message',sa.Text(),nullable=False),sa.Column('prompt',sa.Text(),nullable=False),sa.Column('config',JSONB(),nullable=False),sa.Column('status',sa.String(20),nullable=False),sa.Column('result_key',sa.Text()),sa.Column('error_code',sa.String(50)),sa.Column('lease_until',sa.DateTime(timezone=True)),sa.UniqueConstraint('work_id','request_key'))
    op.create_index('ix_goods_revisions_work_id','goods_revisions',['work_id'])
    op.create_table('goods_designs',*ident(),sa.Column('owner_id',UUID(as_uuid=True),sa.ForeignKey('users.id'),nullable=False),sa.Column('work_id',UUID(as_uuid=True),sa.ForeignKey('goods_work.id'),nullable=False,unique=True),sa.Column('revision_id',UUID(as_uuid=True),sa.ForeignKey('goods_revisions.id'),nullable=False),sa.Column('placement',JSONB(),nullable=False),sa.Column('album_id',UUID(as_uuid=True),sa.ForeignKey('albums.id')),sa.Column('version',sa.Integer(),nullable=False),sa.Column('production_started_at',sa.DateTime(timezone=True)))
    op.create_index('ix_goods_designs_owner_id','goods_designs',['owner_id'])

def downgrade():
    op.drop_table('goods_designs');op.drop_table('goods_revisions');op.drop_table('goods_work')
