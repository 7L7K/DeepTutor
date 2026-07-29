CREATE TABLE IF NOT EXISTS practice_generation_operations (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    practice_set_id TEXT NOT NULL REFERENCES practice_sets(id) ON DELETE RESTRICT,
    practice_set_revision_id TEXT NOT NULL
        REFERENCES practice_set_revisions(id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    source_snapshot_json TEXT NOT NULL,
    objective_ids_json TEXT NOT NULL,
    course_write_epoch INTEGER NOT NULL CHECK (course_write_epoch >= 1),
    practice_set_write_epoch INTEGER NOT NULL CHECK (practice_set_write_epoch >= 1),
    item_limit INTEGER NOT NULL CHECK (item_limit BETWEEN 1 AND 12),
    context_char_limit INTEGER NOT NULL CHECK (context_char_limit BETWEEN 1 AND 48000),
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'completed', 'failed')),
    error_code TEXT CHECK (error_code IN (
        'provider_unavailable', 'provider_failed', 'invalid_output',
        'source_changed', 'authority_changed', 'interrupted', 'provider_timed_out'
    )),
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    updated_at REAL NOT NULL,
    UNIQUE (course_id, idempotency_key),
    UNIQUE (practice_set_revision_id)
);
CREATE INDEX IF NOT EXISTS idx_practice_generation_operations_course_updated
    ON practice_generation_operations(course_id, updated_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_practice_generation_operations_set_updated
    ON practice_generation_operations(practice_set_id, updated_at DESC, id);

CREATE TRIGGER practice_generation_operations_require_owned_draft_insert
BEFORE INSERT ON practice_generation_operations
WHEN NEW.state != 'queued'
 OR NEW.started_at IS NOT NULL
 OR NEW.completed_at IS NOT NULL
 OR NEW.error_code IS NOT NULL
 OR length(NEW.id) < 5
 OR length(NEW.id) > 80
 OR NEW.id NOT LIKE 'opg_%'
 OR length(NEW.idempotency_key) < 1
 OR length(NEW.idempotency_key) > 160
 OR length(NEW.request_fingerprint) != 64
 OR NEW.request_fingerprint GLOB '*[^0-9a-f]*'
 OR json_valid(NEW.source_snapshot_json) != 1
 OR json_type(NEW.source_snapshot_json) != 'array'
 OR json_array_length(NEW.source_snapshot_json) NOT BETWEEN 1 AND 64
 OR json_valid(NEW.objective_ids_json) != 1
 OR json_type(NEW.objective_ids_json) != 'array'
 OR json_array_length(NEW.objective_ids_json) > 64
 OR EXISTS (
    SELECT 1 FROM json_each(NEW.source_snapshot_json) AS snapshot
    WHERE json_type(snapshot.value) != 'object'
       OR json_type(snapshot.value, '$.source_id') != 'text'
       OR json_type(snapshot.value, '$.source_revision') != 'integer'
       OR json_type(snapshot.value, '$.content_sha256') != 'text'
       OR (SELECT COUNT(*) FROM json_each(snapshot.value)) != 3
       OR length(json_extract(snapshot.value, '$.source_id')) > 80
       OR json_extract(snapshot.value, '$.source_id') NOT LIKE 'src_%'
       OR json_extract(snapshot.value, '$.source_revision') < 1
       OR length(json_extract(snapshot.value, '$.content_sha256')) != 64
       OR json_extract(snapshot.value, '$.content_sha256') GLOB '*[^0-9a-f]*'
 )
 OR NOT EXISTS (
    SELECT 1
    FROM courses
    JOIN practice_sets ON practice_sets.course_id = courses.id
    JOIN practice_set_revisions ON practice_set_revisions.practice_set_id = practice_sets.id
    WHERE courses.id = NEW.course_id
      AND courses.owner_user_id = NEW.owner_user_id
      AND courses.state = 'active'
      AND courses.write_epoch = NEW.course_write_epoch
      AND practice_sets.id = NEW.practice_set_id
      AND practice_sets.owner_user_id = NEW.owner_user_id
      AND practice_sets.mode = 'generated'
      AND practice_sets.state = 'draft'
      AND practice_sets.write_epoch = NEW.practice_set_write_epoch
      AND practice_set_revisions.id = NEW.practice_set_revision_id
      AND practice_set_revisions.state = 'draft'
      AND practice_set_revisions.source_snapshot_json = NEW.source_snapshot_json
      AND practice_set_revisions.objective_ids_json = NEW.objective_ids_json
 )
BEGIN
    SELECT RAISE(ABORT, 'generation operation requires owned active generated draft');
END;

CREATE TRIGGER practice_generation_operations_immutable_binding
BEFORE UPDATE OF id, owner_user_id, course_id, practice_set_id,
    practice_set_revision_id, idempotency_key, request_fingerprint,
    source_snapshot_json, objective_ids_json, course_write_epoch,
    practice_set_write_epoch, item_limit, context_char_limit, created_at
ON practice_generation_operations
BEGIN
    SELECT RAISE(ABORT, 'generation operation binding is immutable');
END;

CREATE TRIGGER practice_generation_operations_valid_transition
BEFORE UPDATE OF state, started_at, completed_at, updated_at, error_code
ON practice_generation_operations
WHEN NOT (
    (OLD.state = 'queued' AND NEW.state IN ('running', 'failed'))
    OR (OLD.state = 'running' AND NEW.state IN ('completed', 'failed'))
    OR OLD.state = NEW.state
 )
 OR NEW.updated_at < OLD.updated_at
 OR (NEW.state = 'queued' AND (
        NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL OR NEW.error_code IS NOT NULL
    ))
 OR (NEW.state = 'running' AND (
        NEW.started_at IS NULL OR NEW.completed_at IS NOT NULL OR NEW.error_code IS NOT NULL
    ))
 OR (NEW.state = 'completed' AND (
        NEW.started_at IS NULL OR NEW.completed_at IS NULL OR NEW.error_code IS NOT NULL
    ))
 OR (NEW.state = 'failed' AND (
        NEW.completed_at IS NULL OR NEW.error_code IS NULL
    ))
BEGIN
    SELECT RAISE(ABORT, 'invalid generation operation transition');
END;

CREATE TRIGGER practice_generation_operations_complete_requires_ready_revision
BEFORE UPDATE OF state ON practice_generation_operations
WHEN NEW.state = 'completed'
 AND NOT EXISTS (
    SELECT 1 FROM practice_set_revisions
    WHERE id = NEW.practice_set_revision_id
      AND practice_set_id = NEW.practice_set_id
      AND state = 'ready'
 )
BEGIN
    SELECT RAISE(ABORT, 'completed generation requires ready revision');
END;

CREATE TRIGGER practice_generation_operations_terminal_immutable
BEFORE UPDATE ON practice_generation_operations
WHEN OLD.state IN ('completed', 'failed')
BEGIN
    SELECT RAISE(ABORT, 'terminal generation operations are immutable');
END;

CREATE TRIGGER practice_generation_operations_no_delete
BEFORE DELETE ON practice_generation_operations
BEGIN
    SELECT RAISE(ABORT, 'generation operations are retained history');
END;

CREATE TRIGGER practice_generation_practice_set_mode_immutable
BEFORE UPDATE OF mode ON practice_sets
WHEN NEW.mode != OLD.mode
BEGIN
    SELECT RAISE(ABORT, 'practice set mode is immutable');
END;

CREATE TRIGGER practice_generation_generated_revision_question_fence
BEFORE INSERT ON practice_questions
WHEN EXISTS (
    SELECT 1 FROM practice_set_revisions AS revisions
    JOIN practice_sets AS sets ON sets.id = revisions.practice_set_id
    WHERE revisions.id = NEW.practice_set_revision_id AND sets.mode = 'generated'
)
AND NOT EXISTS (
    SELECT 1 FROM practice_generation_operations
    WHERE practice_set_revision_id = NEW.practice_set_revision_id AND state = 'running'
)
BEGIN
    SELECT RAISE(ABORT, 'generated revision questions require running generation operation');
END;

CREATE TRIGGER practice_generation_generated_revision_ready_fence
BEFORE UPDATE OF state ON practice_set_revisions
WHEN NEW.state = 'ready'
 AND EXISTS (SELECT 1 FROM practice_sets WHERE id = NEW.practice_set_id AND mode = 'generated')
 AND NOT EXISTS (
    SELECT 1 FROM practice_generation_operations
    WHERE practice_set_revision_id = NEW.id
      AND state = 'running'
      AND NEW.generation_receipt_json IS NOT NULL
      AND json_valid(NEW.generation_receipt_json) = 1
      AND json_extract(NEW.generation_receipt_json, '$.operation_id') = id
 )
BEGIN
    SELECT RAISE(ABORT, 'generated revision ready requires bound running operation receipt');
END;
