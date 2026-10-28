from alembic import op
revision = "0001_workflow_foundation"
down_revision = None
branch_labels = None
depends_on = None

# Frozen DDL: deliberately independent of future ORM model changes.
DDL = [
    """CREATE TABLE users (
	display_name VARCHAR(100) NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id)
)""",
    """CREATE TABLE outbox_events (
	event_type VARCHAR(30) NOT NULL,
	entity_id UUID NOT NULL,
	payload JSONB NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id)
)""",
    """CREATE TABLE background_jobs (
	kind VARCHAR(30) NOT NULL,
	target_id UUID NOT NULL,
	status VARCHAR(30) NOT NULL,
	attempt_count INTEGER NOT NULL,
	next_retry_at TIMESTAMP WITH TIME ZONE,
	lease_until TIMESTAMP WITH TIME ZONE,
	fence_version INTEGER NOT NULL,
	error_code VARCHAR(100),
	finished_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (kind, target_id)
)""",
    """CREATE TABLE albums (
	owner_id UUID NOT NULL,
	title TEXT NOT NULL,
	status VARCHAR(30) NOT NULL,
	version INTEGER NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(owner_id) REFERENCES users (id)
)""",
    """CREATE TABLE album_pages (
	album_id UUID NOT NULL,
	position INTEGER NOT NULL,
	selection_index INTEGER NOT NULL,
	version INTEGER NOT NULL,
	result_asset_id UUID,
	caption_text TEXT,
	removed_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (album_id, selection_index),
	FOREIGN KEY(album_id) REFERENCES albums (id)
)""",
    """CREATE UNIQUE INDEX uq_page_position ON album_pages (album_id, position) WHERE removed_at IS NULL""",
    """CREATE TABLE generation_runs (
	album_id UUID NOT NULL,
	status VARCHAR(30) NOT NULL,
	input_version INTEGER NOT NULL,
	input_snapshot JSONB NOT NULL,
	config_snapshot JSONB NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(album_id) REFERENCES albums (id)
)""",
    """CREATE UNIQUE INDEX uq_active_run ON generation_runs (album_id) WHERE status IN ('queued','running','action_required')""",
    """CREATE TABLE media_assets (
	owner_id UUID NOT NULL,
	album_id UUID NOT NULL,
	page_id UUID NOT NULL,
	role VARCHAR(30) NOT NULL,
	storage_key TEXT NOT NULL,
	mime VARCHAR(100) NOT NULL,
	bytes BIGINT,
	width INTEGER,
	height INTEGER,
	sha256 VARCHAR(64),
	status VARCHAR(30) NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(owner_id) REFERENCES users (id),
	FOREIGN KEY(album_id) REFERENCES albums (id),
	FOREIGN KEY(page_id) REFERENCES album_pages (id),
	UNIQUE (storage_key)
)""",
    """CREATE TABLE upload_sessions (
	album_id UUID NOT NULL,
	page_id UUID NOT NULL,
	asset_id UUID NOT NULL,
	batch_id UUID NOT NULL,
	client_file_id UUID NOT NULL,
	status VARCHAR(30) NOT NULL,
	declared_bytes BIGINT NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	error_code VARCHAR(100),
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (batch_id, client_file_id),
	FOREIGN KEY(album_id) REFERENCES albums (id),
	FOREIGN KEY(page_id) REFERENCES album_pages (id),
	FOREIGN KEY(asset_id) REFERENCES media_assets (id)
)""",
    """CREATE TABLE generation_tasks (
	run_id UUID NOT NULL,
	page_id UUID NOT NULL,
	stage VARCHAR(30) NOT NULL,
	status VARCHAR(30) NOT NULL,
	output_asset_id UUID,
	output_caption TEXT,
	completion_kind VARCHAR(30),
	attempt_count INTEGER NOT NULL,
	next_retry_at TIMESTAMP WITH TIME ZONE,
	lease_until TIMESTAMP WITH TIME ZONE,
	fence_version INTEGER NOT NULL,
	error_code VARCHAR(100),
	safe_to_retry BOOLEAN NOT NULL,
	requires_ai_call BOOLEAN NOT NULL,
	has_persisted_input BOOLEAN NOT NULL,
	id UUID NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (run_id, page_id, stage),
	CHECK (stage IN ('caption','image_transform','optimize')),
	FOREIGN KEY(run_id) REFERENCES generation_runs (id),
	FOREIGN KEY(page_id) REFERENCES album_pages (id),
	FOREIGN KEY(output_asset_id) REFERENCES media_assets (id)
)""",
    """CREATE TABLE task_attempts (
	task_id UUID NOT NULL,
	attempt_no INTEGER NOT NULL,
	fence_version INTEGER NOT NULL,
	provider_request_id TEXT,
	status VARCHAR(30) NOT NULL,
	dispatch_state VARCHAR(30) NOT NULL,
	output_asset_id UUID,
	output_caption TEXT,
	result_key TEXT,
	result_sha256 VARCHAR(64),
	usage JSONB,
	estimated_cost JSONB,
	error_code VARCHAR(100),
	finished_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (task_id, attempt_no),
	FOREIGN KEY(task_id) REFERENCES generation_tasks (id),
	FOREIGN KEY(output_asset_id) REFERENCES media_assets (id)
)""",
    """ALTER TABLE album_pages ADD CONSTRAINT fk_page_result FOREIGN KEY(result_asset_id) REFERENCES media_assets (id)""",
]


def upgrade():
    for sql in DDL:
        op.execute(sql)
def downgrade():
    op.execute("ALTER TABLE album_pages DROP CONSTRAINT fk_page_result")
    op.drop_table('task_attempts')
    op.drop_table('upload_sessions')
    op.drop_table('generation_tasks')
    op.drop_table('media_assets')
    op.drop_table('generation_runs')
    op.drop_table('album_pages')
    op.drop_table('albums')
    op.drop_table('users')
    op.drop_table('outbox_events')
    op.drop_table('background_jobs')
