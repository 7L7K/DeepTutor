-- BlueWay course identity is connection + external course id, optionally
-- qualified by the provider term.  Rebuild the two identity tables because
-- SQLite cannot alter an existing composite primary key in place.
DROP TRIGGER IF EXISTS blueway_course_maps_require_academic_course_insert;
DROP TRIGGER IF EXISTS blueway_course_maps_require_academic_course_update;

CREATE TABLE blueway_course_maps_term_new (
    connection_id TEXT NOT NULL REFERENCES blueway_connections(id) ON DELETE RESTRICT,
    external_course_id TEXT NOT NULL,
    external_term_id TEXT,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    remote_title TEXT NOT NULL,
    remote_state TEXT NOT NULL CHECK (remote_state IN ('active', 'archived')),
    remote_hash TEXT NOT NULL,
    first_seen_snapshot_id TEXT NOT NULL,
    last_seen_snapshot_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (connection_id, external_course_id, external_term_id),
    UNIQUE (connection_id, course_id)
);

INSERT INTO blueway_course_maps_term_new (
    connection_id, external_course_id, external_term_id, course_id, remote_title,
    remote_state, remote_hash, first_seen_snapshot_id, last_seen_snapshot_id,
    created_at, updated_at
)
SELECT connection_id, external_course_id, NULL, course_id, remote_title,
       remote_state, remote_hash, first_seen_snapshot_id, last_seen_snapshot_id,
       created_at, updated_at
FROM blueway_course_maps;

DROP TABLE blueway_course_maps;
ALTER TABLE blueway_course_maps_term_new RENAME TO blueway_course_maps;
CREATE UNIQUE INDEX blueway_course_maps_identity
    ON blueway_course_maps(connection_id, external_course_id, COALESCE(external_term_id, ''));

CREATE TABLE blueway_records_term_new (
    connection_id TEXT NOT NULL REFERENCES blueway_connections(id) ON DELETE RESTRICT,
    record_kind TEXT NOT NULL,
    external_record_id TEXT NOT NULL,
    external_course_id TEXT,
    external_term_id TEXT,
    course_id TEXT REFERENCES courses(id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state IN ('current', 'unlinked', 'archived')),
    remote_revision TEXT,
    content_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    current_source_id TEXT REFERENCES course_sources(id) ON DELETE RESTRICT,
    first_seen_snapshot_id TEXT NOT NULL,
    last_seen_snapshot_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (connection_id, record_kind, external_record_id, external_term_id)
);

INSERT INTO blueway_records_term_new (
    connection_id, record_kind, external_record_id, external_course_id,
    external_term_id, course_id, state, remote_revision, content_sha256,
    payload_json, current_source_id, first_seen_snapshot_id, last_seen_snapshot_id,
    created_at, updated_at
)
SELECT connection_id, record_kind, external_record_id, external_course_id,
       NULL, course_id, state, remote_revision, content_sha256, payload_json,
       current_source_id, first_seen_snapshot_id, last_seen_snapshot_id,
       created_at, updated_at
FROM blueway_records;

DROP TABLE blueway_records;
ALTER TABLE blueway_records_term_new RENAME TO blueway_records;
CREATE UNIQUE INDEX blueway_records_identity
    ON blueway_records(connection_id, record_kind, external_record_id, COALESCE(external_term_id, ''));

CREATE TRIGGER blueway_course_maps_require_academic_course_insert
BEFORE INSERT ON blueway_course_maps
WHEN NOT EXISTS (
    SELECT 1 FROM courses
    WHERE id = NEW.course_id AND workspace_kind = 'academic_course'
)
BEGIN
    SELECT RAISE(ABORT, 'BlueWay mappings require an academic Course');
END;

CREATE TRIGGER blueway_course_maps_require_academic_course_update
BEFORE UPDATE OF course_id ON blueway_course_maps
WHEN NOT EXISTS (
    SELECT 1 FROM courses
    WHERE id = NEW.course_id AND workspace_kind = 'academic_course'
)
BEGIN
    SELECT RAISE(ABORT, 'BlueWay mappings require an academic Course');
END;
