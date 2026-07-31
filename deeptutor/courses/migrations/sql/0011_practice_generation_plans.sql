ALTER TABLE practice_generation_operations
    ADD COLUMN focus TEXT NOT NULL DEFAULT 'Course review';
ALTER TABLE practice_generation_operations
    ADD COLUMN difficulty TEXT NOT NULL DEFAULT 'mixed'
    CHECK (difficulty IN ('foundation', 'mixed', 'challenge'));
ALTER TABLE practice_generation_operations
    ADD COLUMN timing_mode TEXT NOT NULL DEFAULT 'untimed'
    CHECK (timing_mode IN ('untimed', 'practice_timer'));
ALTER TABLE practice_generation_operations
    ADD COLUMN cancel_requested_at REAL;
ALTER TABLE practice_generation_operations
    ADD COLUMN cancelled_at REAL;
ALTER TABLE quiz_attempts
    ADD COLUMN timing_mode TEXT NOT NULL DEFAULT 'untimed'
    CHECK (timing_mode IN ('untimed', 'practice_timer'));

CREATE TRIGGER practice_generation_operation_plan_fields_immutable
BEFORE UPDATE OF focus, difficulty, timing_mode
ON practice_generation_operations
BEGIN
    SELECT RAISE(ABORT, 'Practice generation operation plan fields are immutable');
END;

CREATE TRIGGER practice_generation_operation_cancel_valid
BEFORE UPDATE OF cancel_requested_at, cancelled_at
ON practice_generation_operations
WHEN (
    OLD.cancel_requested_at IS NOT NULL
    AND NEW.cancel_requested_at IS NOT OLD.cancel_requested_at
 )
 OR (
    OLD.cancelled_at IS NOT NULL
    AND NEW.cancelled_at IS NOT OLD.cancelled_at
 )
 OR (
    NEW.cancel_requested_at IS NOT NULL
    AND OLD.cancel_requested_at IS NULL
    AND OLD.state NOT IN ('queued', 'running')
 )
 OR (
    NEW.cancel_requested_at IS NOT NULL
    AND NOT (
        (NEW.state = 'running' AND NEW.cancelled_at IS NULL)
        OR (
            NEW.state = 'failed'
            AND NEW.error_code = 'interrupted'
            AND NEW.cancelled_at IS NOT NULL
        )
    )
 )
 OR (
    NEW.cancelled_at IS NOT NULL
    AND (
        NEW.cancel_requested_at IS NULL
        OR NEW.cancelled_at < NEW.cancel_requested_at
        OR NEW.state != 'failed'
        OR NEW.error_code != 'interrupted'
    )
 )
 OR (
    (NEW.cancel_requested_at IS NOT OLD.cancel_requested_at
     OR NEW.cancelled_at IS NOT OLD.cancelled_at)
    AND NEW.updated_at <= OLD.updated_at
 )
BEGIN
    SELECT RAISE(ABORT, 'invalid Practice generation cancellation');
END;

CREATE TRIGGER quiz_attempts_timing_mode_immutable
BEFORE UPDATE OF timing_mode ON quiz_attempts
BEGIN
    SELECT RAISE(ABORT, 'Quiz attempt timing mode is immutable');
END;

CREATE TRIGGER practice_generation_operations_source_receipts_owned
BEFORE INSERT ON practice_generation_operations
WHEN (
    SELECT count(*) FROM json_each(NEW.source_snapshot_json)
) != (
    SELECT count(DISTINCT json_extract(receipt.value, '$.source_id'))
    FROM json_each(NEW.source_snapshot_json) AS receipt
)
 OR EXISTS (
    SELECT 1 FROM json_each(NEW.source_snapshot_json) AS receipt
    WHERE NOT EXISTS (
        SELECT 1 FROM course_sources AS source
        JOIN courses ON courses.id = source.course_id
        WHERE source.id = json_extract(receipt.value, '$.source_id')
          AND source.course_id = NEW.course_id
          AND source.state = 'ready'
          AND source.revision = json_extract(receipt.value, '$.source_revision')
          AND source.content_sha256 = json_extract(receipt.value, '$.content_sha256')
          AND courses.owner_user_id = NEW.owner_user_id
          AND courses.state = 'active'
          AND courses.write_epoch = NEW.course_write_epoch
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'Practice generation operation requires current owned source receipts');
END;

CREATE TABLE IF NOT EXISTS practice_generation_plans (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    focus TEXT NOT NULL,
    source_snapshot_json TEXT NOT NULL,
    objective_ids_json TEXT NOT NULL,
    item_limit INTEGER NOT NULL CHECK (item_limit BETWEEN 1 AND 12),
    difficulty TEXT NOT NULL CHECK (difficulty IN ('foundation', 'mixed', 'challenge')),
    timing_mode TEXT NOT NULL CHECK (timing_mode IN ('untimed', 'practice_timer')),
    origin_json TEXT NOT NULL,
    course_write_epoch INTEGER NOT NULL CHECK (course_write_epoch >= 1),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    state TEXT NOT NULL DEFAULT 'draft'
        CHECK (state IN ('draft', 'confirmed', 'expired')),
    confirmed_operation_id TEXT
        REFERENCES practice_generation_operations(id) ON DELETE RESTRICT,
    creation_idempotency_key TEXT,
    creation_request_fingerprint TEXT,
    confirmation_idempotency_key TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    confirmed_at REAL,
    UNIQUE (course_id, creation_idempotency_key),
    UNIQUE (course_id, confirmation_idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_practice_generation_plans_course_updated
    ON practice_generation_plans(course_id, updated_at DESC, id);

CREATE TRIGGER practice_generation_plans_valid_insert
BEFORE INSERT ON practice_generation_plans
WHEN NEW.id NOT LIKE 'pln_%'
 OR length(NEW.id) < 5 OR length(NEW.id) > 80
 OR length(trim(NEW.title)) < 1 OR length(NEW.title) > 160
 OR length(trim(NEW.focus)) < 1 OR length(NEW.focus) > 4000
 OR NEW.state != 'draft'
 OR NEW.revision != 1
 OR NEW.confirmed_operation_id IS NOT NULL
 OR (
    (NEW.creation_idempotency_key IS NULL) !=
    (NEW.creation_request_fingerprint IS NULL)
 )
 OR (
    NEW.creation_idempotency_key IS NOT NULL
    AND (
        length(NEW.creation_idempotency_key) NOT BETWEEN 8 AND 160
        OR length(NEW.creation_request_fingerprint) != 64
        OR NEW.creation_request_fingerprint GLOB '*[^0-9a-f]*'
    )
 )
 OR NEW.confirmation_idempotency_key IS NOT NULL
 OR NEW.confirmed_at IS NOT NULL
 OR json_valid(NEW.source_snapshot_json) != 1
 OR json_type(NEW.source_snapshot_json) != 'array'
 OR json_array_length(NEW.source_snapshot_json) NOT BETWEEN 1 AND 64
 OR json_valid(NEW.objective_ids_json) != 1
 OR json_type(NEW.objective_ids_json) != 'array'
 OR json_array_length(NEW.objective_ids_json) > 64
 OR json_valid(NEW.origin_json) != 1
 OR json_type(NEW.origin_json) != 'object'
 OR json_type(NEW.origin_json, '$.kind') != 'text'
 OR json_extract(NEW.origin_json, '$.kind') NOT IN ('practice', 'course_chat')
 OR (
    json_extract(NEW.origin_json, '$.kind') = 'practice'
    AND (
        json_type(NEW.origin_json, '$.session_id') != 'null'
        OR json_type(NEW.origin_json, '$.assistant_message_id') != 'null'
    )
 )
 OR (
    json_extract(NEW.origin_json, '$.kind') = 'course_chat'
    AND (
        json_type(NEW.origin_json, '$.session_id') != 'text'
        OR length(trim(json_extract(NEW.origin_json, '$.session_id'))) < 1
        OR json_type(NEW.origin_json, '$.assistant_message_id') != 'integer'
        OR json_extract(NEW.origin_json, '$.assistant_message_id') < 1
    )
 )
 OR EXISTS (
    SELECT 1 FROM json_each(NEW.source_snapshot_json) AS receipt
    WHERE json_type(receipt.value) != 'object'
       OR (SELECT count(*) FROM json_each(receipt.value)) != 3
       OR json_type(receipt.value, '$.source_id') != 'text'
       OR json_extract(receipt.value, '$.source_id') NOT LIKE 'src_%'
       OR length(json_extract(receipt.value, '$.source_id')) > 80
       OR json_type(receipt.value, '$.source_revision') != 'integer'
       OR json_extract(receipt.value, '$.source_revision') < 1
       OR json_type(receipt.value, '$.content_sha256') != 'text'
       OR length(json_extract(receipt.value, '$.content_sha256')) != 64
       OR json_extract(receipt.value, '$.content_sha256') GLOB '*[^0-9a-f]*'
 )
 OR (
    SELECT count(*) FROM json_each(NEW.source_snapshot_json)
 ) != (
    SELECT count(DISTINCT json_extract(receipt.value, '$.source_id'))
    FROM json_each(NEW.source_snapshot_json) AS receipt
 )
 OR EXISTS (
    SELECT 1 FROM json_each(NEW.source_snapshot_json) AS receipt
    WHERE NOT EXISTS (
        SELECT 1 FROM course_sources AS source
        WHERE source.id = json_extract(receipt.value, '$.source_id')
          AND source.course_id = NEW.course_id
          AND source.state = 'ready'
          AND source.revision = json_extract(receipt.value, '$.source_revision')
          AND source.content_sha256 = json_extract(receipt.value, '$.content_sha256')
    )
 )
 OR EXISTS (
    SELECT 1 FROM json_each(NEW.objective_ids_json) AS objective
    WHERE objective.type != 'text'
       OR length(trim(objective.value)) NOT BETWEEN 1 AND 160
 )
 OR (
    SELECT count(*) FROM json_each(NEW.objective_ids_json)
 ) != (
    SELECT count(DISTINCT objective.value)
    FROM json_each(NEW.objective_ids_json) AS objective
 )
 OR NOT EXISTS (
    SELECT 1 FROM courses
    WHERE id = NEW.course_id
      AND owner_user_id = NEW.owner_user_id
      AND workspace_kind = 'academic_course'
      AND state = 'active'
      AND write_epoch = NEW.course_write_epoch
 )
BEGIN
    SELECT RAISE(ABORT, 'Practice generation plan requires owned active Course authority');
END;

CREATE TRIGGER practice_generation_plans_binding_immutable
BEFORE UPDATE OF id, owner_user_id, course_id, course_write_epoch, created_at,
                 creation_idempotency_key, creation_request_fingerprint
ON practice_generation_plans
BEGIN
    SELECT RAISE(ABORT, 'Practice generation plan authority is immutable');
END;

CREATE TRIGGER practice_generation_plans_valid_update
BEFORE UPDATE ON practice_generation_plans
WHEN NEW.updated_at < OLD.updated_at
 OR NEW.revision < OLD.revision
 OR (
    OLD.state = 'draft' AND NEW.state = 'draft'
    AND (
        NEW.revision != OLD.revision + 1
        OR NEW.confirmed_operation_id IS NOT NULL
        OR NEW.confirmation_idempotency_key IS NOT NULL
        OR NEW.confirmed_at IS NOT NULL
        OR NOT EXISTS (
            SELECT 1 FROM courses
            WHERE id = NEW.course_id
              AND owner_user_id = NEW.owner_user_id
              AND state = 'active'
              AND write_epoch = NEW.course_write_epoch
        )
    )
 )
 OR (
    OLD.state = 'draft' AND NEW.state = 'confirmed'
    AND (
        NEW.revision != OLD.revision
        OR NEW.confirmed_operation_id IS NULL
        OR NEW.confirmation_idempotency_key IS NULL
        OR length(NEW.confirmation_idempotency_key) NOT BETWEEN 8 AND 160
        OR NEW.confirmed_at IS NULL
    )
 )
 OR (
    OLD.state = 'draft' AND NEW.state = 'expired'
    AND (
        NEW.revision != OLD.revision
        OR NEW.confirmed_operation_id IS NOT NULL
        OR NEW.confirmation_idempotency_key IS NOT NULL
        OR NEW.confirmed_at IS NOT NULL
    )
 )
 OR OLD.state IN ('confirmed', 'expired')
 OR NEW.state NOT IN ('draft', 'confirmed', 'expired')
 OR length(trim(NEW.title)) < 1 OR length(NEW.title) > 160
 OR length(trim(NEW.focus)) < 1 OR length(NEW.focus) > 4000
 OR json_valid(NEW.source_snapshot_json) != 1
 OR json_type(NEW.source_snapshot_json) != 'array'
 OR json_array_length(NEW.source_snapshot_json) NOT BETWEEN 1 AND 64
 OR EXISTS (
    SELECT 1 FROM json_each(NEW.source_snapshot_json) AS receipt
    WHERE json_type(receipt.value) != 'object'
       OR (SELECT count(*) FROM json_each(receipt.value)) != 3
       OR json_type(receipt.value, '$.source_id') != 'text'
       OR json_extract(receipt.value, '$.source_id') NOT LIKE 'src_%'
       OR length(json_extract(receipt.value, '$.source_id')) > 80
       OR json_type(receipt.value, '$.source_revision') != 'integer'
       OR json_extract(receipt.value, '$.source_revision') < 1
       OR json_type(receipt.value, '$.content_sha256') != 'text'
       OR length(json_extract(receipt.value, '$.content_sha256')) != 64
       OR json_extract(receipt.value, '$.content_sha256') GLOB '*[^0-9a-f]*'
 )
 OR (
    SELECT count(*) FROM json_each(NEW.source_snapshot_json)
 ) != (
    SELECT count(DISTINCT json_extract(receipt.value, '$.source_id'))
    FROM json_each(NEW.source_snapshot_json) AS receipt
 )
 OR EXISTS (
    SELECT 1 FROM json_each(NEW.source_snapshot_json) AS receipt
    WHERE NOT EXISTS (
        SELECT 1 FROM course_sources AS source
        WHERE source.id = json_extract(receipt.value, '$.source_id')
          AND source.course_id = NEW.course_id
          AND source.state = 'ready'
          AND source.revision = json_extract(receipt.value, '$.source_revision')
          AND source.content_sha256 = json_extract(receipt.value, '$.content_sha256')
    )
 )
 OR json_valid(NEW.objective_ids_json) != 1
 OR json_type(NEW.objective_ids_json) != 'array'
 OR json_array_length(NEW.objective_ids_json) > 64
 OR EXISTS (
    SELECT 1 FROM json_each(NEW.objective_ids_json) AS objective
    WHERE objective.type != 'text'
       OR length(trim(objective.value)) NOT BETWEEN 1 AND 160
 )
 OR (
    SELECT count(*) FROM json_each(NEW.objective_ids_json)
 ) != (
    SELECT count(DISTINCT objective.value)
    FROM json_each(NEW.objective_ids_json) AS objective
 )
BEGIN
    SELECT RAISE(ABORT, 'invalid Practice generation plan transition');
END;

CREATE TRIGGER practice_generation_plans_confirmation_owned
BEFORE UPDATE OF state ON practice_generation_plans
WHEN NEW.state = 'confirmed'
 AND NOT EXISTS (
    SELECT 1 FROM practice_generation_operations AS operation
    JOIN courses ON courses.id = operation.course_id
    JOIN practice_sets AS practice_set
      ON practice_set.id = operation.practice_set_id
    WHERE operation.id = NEW.confirmed_operation_id
      AND operation.owner_user_id = NEW.owner_user_id
      AND operation.course_id = NEW.course_id
      AND operation.source_snapshot_json = NEW.source_snapshot_json
      AND operation.objective_ids_json = NEW.objective_ids_json
      AND operation.item_limit = NEW.item_limit
      AND operation.focus = NEW.focus
      AND operation.difficulty = NEW.difficulty
      AND operation.timing_mode = NEW.timing_mode
      AND operation.state = 'queued'
      AND operation.course_write_epoch = NEW.course_write_epoch
      AND practice_set.owner_user_id = NEW.owner_user_id
      AND practice_set.course_id = NEW.course_id
      AND practice_set.state = 'draft'
      AND practice_set.write_epoch = operation.practice_set_write_epoch
      AND EXISTS (
          SELECT 1 FROM practice_set_revisions AS revision
          WHERE revision.id = operation.practice_set_revision_id
            AND revision.practice_set_id = operation.practice_set_id
      )
      AND courses.owner_user_id = NEW.owner_user_id
      AND courses.state = 'active'
      AND courses.write_epoch = NEW.course_write_epoch
 )
BEGIN
    SELECT RAISE(ABORT, 'Practice generation plan confirmation requires its owned operation');
END;

CREATE TRIGGER practice_generation_plans_no_delete
BEFORE DELETE ON practice_generation_plans
BEGIN
    SELECT RAISE(ABORT, 'Practice generation plans are retained history');
END;
