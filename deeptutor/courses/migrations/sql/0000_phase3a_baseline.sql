CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    checksum_sha256 TEXT NOT NULL,
    applied_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active', 'archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    write_epoch INTEGER NOT NULL DEFAULT 1 CHECK (write_epoch >= 1),
    managed_kb_ref TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    archived_at REAL
);
CREATE INDEX IF NOT EXISTS idx_courses_owner_updated
    ON courses(owner_user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS course_sources (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL,
    display_name TEXT NOT NULL,
    state TEXT NOT NULL
        CHECK (state IN ('processing', 'ready', 'failed', 'archived')),
    manifest_json TEXT NOT NULL DEFAULT '[]',
    content_sha256 TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    operation_id TEXT UNIQUE,
    idempotency_key TEXT,
    supersedes_source_id TEXT
        REFERENCES course_sources(id) ON DELETE RESTRICT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_course_sources_course_updated
    ON course_sources(course_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_course_sources_operation
    ON course_sources(operation_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_course_sources_live_supersedes
    ON course_sources(supersedes_source_id)
    WHERE supersedes_source_id IS NOT NULL
      AND state IN ('processing', 'ready');
CREATE UNIQUE INDEX IF NOT EXISTS idx_course_sources_idempotency
    ON course_sources(course_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS blueway_connections (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    external_subject TEXT NOT NULL,
    state TEXT NOT NULL
        CHECK (state IN (
            'pending',
            'active',
            'revocation_pending',
            'disconnected',
            'error'
        )),
    scope_version TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    grant_generation INTEGER NOT NULL DEFAULT 1
        CHECK (grant_generation >= 1),
    credential_ref TEXT,
    credential_status TEXT NOT NULL DEFAULT 'healthy',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    connected_at REAL,
    last_sync_at REAL,
    disconnected_at REAL,
    rotation_request_id TEXT,
    rotation_started_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS blueway_one_live_connection
    ON blueway_connections(owner_user_id)
    WHERE state IN ('active', 'revocation_pending');

CREATE TABLE IF NOT EXISTS blueway_course_maps (
    connection_id TEXT NOT NULL
        REFERENCES blueway_connections(id) ON DELETE RESTRICT,
    external_course_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    remote_title TEXT NOT NULL,
    remote_state TEXT NOT NULL CHECK (remote_state IN ('active', 'archived')),
    remote_hash TEXT NOT NULL,
    first_seen_snapshot_id TEXT NOT NULL,
    last_seen_snapshot_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (connection_id, external_course_id),
    UNIQUE (connection_id, course_id)
);

CREATE TABLE IF NOT EXISTS blueway_records (
    connection_id TEXT NOT NULL
        REFERENCES blueway_connections(id) ON DELETE RESTRICT,
    record_kind TEXT NOT NULL,
    external_record_id TEXT NOT NULL,
    external_course_id TEXT,
    course_id TEXT REFERENCES courses(id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state IN ('current', 'unlinked', 'archived')),
    remote_revision TEXT,
    content_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    current_source_id TEXT
        REFERENCES course_sources(id) ON DELETE RESTRICT,
    first_seen_snapshot_id TEXT NOT NULL,
    last_seen_snapshot_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (connection_id, record_kind, external_record_id)
);

CREATE TABLE IF NOT EXISTS blueway_sync_runs (
    id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL
        REFERENCES blueway_connections(id) ON DELETE RESTRICT,
    expected_generation INTEGER NOT NULL,
    snapshot_id TEXT,
    snapshot_sha256 TEXT,
    state TEXT NOT NULL
        CHECK (state IN (
            'queued',
            'fetching',
            'validating',
            'staging',
            'indexing',
            'completed',
            'failed',
            'cancelled'
        )),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    counts_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL
);
CREATE INDEX IF NOT EXISTS blueway_runs_connection_updated
    ON blueway_sync_runs(connection_id, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS blueway_snapshot_replay
    ON blueway_sync_runs(connection_id, snapshot_id)
    WHERE snapshot_id IS NOT NULL AND state = 'completed';
