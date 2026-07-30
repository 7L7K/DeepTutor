ALTER TABLE courses ADD COLUMN workspace_kind TEXT NOT NULL
    DEFAULT 'academic_course'
    CHECK (workspace_kind IN ('academic_course', 'general_study'));

CREATE UNIQUE INDEX courses_one_general_study_per_owner
    ON courses(owner_user_id)
    WHERE workspace_kind = 'general_study';

CREATE TRIGGER courses_general_study_valid_insert
BEFORE INSERT ON courses
WHEN NEW.workspace_kind = 'general_study'
 AND (
    NEW.title != 'General Study'
    OR NEW.state != 'active'
    OR NEW.archived_at IS NOT NULL
    OR NEW.managed_kb_ref IS NOT NULL
 )
BEGIN
    SELECT RAISE(ABORT, 'General Study requires its system-managed identity');
END;

CREATE TRIGGER courses_workspace_kind_immutable
BEFORE UPDATE OF workspace_kind ON courses
BEGIN
    SELECT RAISE(ABORT, 'Course workspace kind is immutable');
END;

CREATE TRIGGER courses_general_study_identity_immutable
BEFORE UPDATE OF title, state, archived_at ON courses
WHEN OLD.workspace_kind = 'general_study'
 AND (
    NEW.title != OLD.title
    OR NEW.state != 'active'
    OR NEW.archived_at IS NOT NULL
 )
BEGIN
    SELECT RAISE(ABORT, 'General Study is a permanent private workspace');
END;

CREATE TRIGGER courses_general_study_no_managed_kb
BEFORE UPDATE OF managed_kb_ref ON courses
WHEN OLD.workspace_kind = 'general_study'
 AND NEW.managed_kb_ref IS NOT OLD.managed_kb_ref
BEGIN
    SELECT RAISE(ABORT, 'General Study cannot own Course Knowledge');
END;

CREATE TRIGGER course_sources_require_academic_course_insert
BEFORE INSERT ON course_sources
WHEN NOT EXISTS (
    SELECT 1 FROM courses
    WHERE id = NEW.course_id
      AND workspace_kind = 'academic_course'
)
BEGIN
    SELECT RAISE(ABORT, 'Course sources require an academic Course');
END;

CREATE TRIGGER course_sources_require_academic_course_update
BEFORE UPDATE OF course_id ON course_sources
WHEN NOT EXISTS (
    SELECT 1 FROM courses
    WHERE id = NEW.course_id
      AND workspace_kind = 'academic_course'
)
BEGIN
    SELECT RAISE(ABORT, 'Course sources require an academic Course');
END;

CREATE TRIGGER practice_sets_require_academic_course_insert
BEFORE INSERT ON practice_sets
WHEN NOT EXISTS (
    SELECT 1 FROM courses
    WHERE id = NEW.course_id
      AND workspace_kind = 'academic_course'
)
BEGIN
    SELECT RAISE(ABORT, 'Practice requires an academic Course');
END;

CREATE TRIGGER practice_sets_require_academic_course_update
BEFORE UPDATE OF course_id ON practice_sets
WHEN NOT EXISTS (
    SELECT 1 FROM courses
    WHERE id = NEW.course_id
      AND workspace_kind = 'academic_course'
)
BEGIN
    SELECT RAISE(ABORT, 'Practice requires an academic Course');
END;

CREATE TRIGGER blueway_course_maps_require_academic_course_insert
BEFORE INSERT ON blueway_course_maps
WHEN NOT EXISTS (
    SELECT 1 FROM courses
    WHERE id = NEW.course_id
      AND workspace_kind = 'academic_course'
)
BEGIN
    SELECT RAISE(ABORT, 'BlueWay mappings require an academic Course');
END;

CREATE TRIGGER blueway_course_maps_require_academic_course_update
BEFORE UPDATE OF course_id ON blueway_course_maps
WHEN NOT EXISTS (
    SELECT 1 FROM courses
    WHERE id = NEW.course_id
      AND workspace_kind = 'academic_course'
)
BEGIN
    SELECT RAISE(ABORT, 'BlueWay mappings require an academic Course');
END;

DROP TRIGGER flashcard_generation_operation_owned_insert;

CREATE TRIGGER flashcard_generation_operation_owned_insert
BEFORE INSERT ON flashcard_generation_operations
WHEN NEW.id NOT LIKE 'ofg_%' OR length(NEW.id) < 5 OR length(NEW.id) > 80
 OR length(NEW.idempotency_key) < 1 OR length(NEW.idempotency_key) > 160
 OR length(NEW.request_fingerprint) != 64
 OR NEW.state != 'queued' OR NEW.error_code IS NOT NULL
 OR NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL
 OR NEW.candidate_output_json IS NOT NULL OR NEW.candidate_revision != 0
 OR NEW.provider_receipt_json IS NOT NULL OR NEW.cancel_requested_at IS NOT NULL
 OR NEW.review_expires_at IS NOT NULL
 OR json_valid(NEW.source_snapshot_json) != 1
 OR json_type(NEW.source_snapshot_json) != 'array'
 OR json_valid(NEW.origin_json) != 1
 OR json_type(NEW.origin_json) != 'object'
 OR json_type(NEW.origin_json,'$.kind') != 'text'
 OR (
    json_extract(NEW.origin_json,'$.kind') = 'general_chat'
    AND (
        json_array_length(NEW.source_snapshot_json) != 0
        OR json_type(NEW.origin_json,'$.session_id') != 'text'
        OR length(json_extract(NEW.origin_json,'$.session_id')) < 1
        OR json_type(NEW.origin_json,'$.message_id') != 'integer'
        OR json_extract(NEW.origin_json,'$.message_id') < 1
        OR json_type(NEW.origin_json,'$.selected_message_ids') != 'array'
        OR json_array_length(json_extract(NEW.origin_json,'$.selected_message_ids'))
           NOT BETWEEN 2 AND 32
        OR json_type(NEW.origin_json,'$.context_sha256') != 'text'
        OR length(json_extract(NEW.origin_json,'$.context_sha256')) != 64
        OR json_extract(NEW.origin_json,'$.context_sha256') GLOB '*[^0-9a-f]*'
        OR json_type(NEW.origin_json,'$.context_summary') != 'text'
        OR length(trim(json_extract(NEW.origin_json,'$.context_summary'))) < 1
        OR json_type(NEW.origin_json,'$.practice_attempt_id') != 'null'
        OR NOT EXISTS (
            SELECT 1 FROM courses
            WHERE id=NEW.course_id AND owner_user_id=NEW.owner_user_id
              AND workspace_kind IN ('general_study', 'academic_course')
        )
    )
 )
 OR (
    json_extract(NEW.origin_json,'$.kind') != 'general_chat'
    AND (
        json_type(NEW.origin_json,'$.selected_message_ids') != 'array'
        OR json_array_length(json_extract(NEW.origin_json,'$.selected_message_ids')) != 0
        OR json_type(NEW.origin_json,'$.context_sha256') != 'null'
        OR json_type(NEW.origin_json,'$.context_summary') != 'null'
        OR
        json_array_length(NEW.source_snapshot_json) NOT BETWEEN 1 AND 64
        OR NOT EXISTS (
            SELECT 1 FROM courses
            WHERE id=NEW.course_id AND owner_user_id=NEW.owner_user_id
              AND workspace_kind='academic_course'
        )
    )
 )
 OR EXISTS (
    SELECT 1 FROM json_each(NEW.source_snapshot_json) AS receipt
    WHERE json_type(receipt.value) != 'object'
       OR (SELECT count(*) FROM json_each(receipt.value)) != 3
       OR json_type(receipt.value,'$.source_id') != 'text'
       OR json_extract(receipt.value,'$.source_id') NOT LIKE 'src_%'
       OR length(json_extract(receipt.value,'$.source_id')) > 80
       OR json_type(receipt.value,'$.source_revision') != 'integer'
       OR json_extract(receipt.value,'$.source_revision') < 1
       OR json_type(receipt.value,'$.content_sha256') != 'text'
       OR length(json_extract(receipt.value,'$.content_sha256')) != 64
       OR json_extract(receipt.value,'$.content_sha256') GLOB '*[^0-9a-f]*'
 )
 OR json_valid(NEW.objective_ids_json) != 1
 OR json_type(NEW.objective_ids_json) != 'array'
 OR json_array_length(NEW.objective_ids_json) > 64
 OR json_valid(NEW.generation_brief_json) != 1
 OR json_type(NEW.generation_brief_json) != 'object'
 OR NOT EXISTS (
    SELECT 1 FROM courses
    WHERE id=NEW.course_id AND owner_user_id=NEW.owner_user_id
      AND state='active' AND write_epoch=NEW.course_write_epoch
 )
 OR NOT EXISTS (
    SELECT 1 FROM flashcard_decks
    WHERE id=NEW.deck_id AND owner_user_id=NEW.owner_user_id
      AND course_id=NEW.course_id AND mode='generated' AND state='draft'
      AND write_epoch=NEW.deck_write_epoch
      AND source_snapshot_json=NEW.source_snapshot_json
 )
 OR (
    NEW.supersedes_deck_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM flashcard_decks
        WHERE id=NEW.supersedes_deck_id AND owner_user_id=NEW.owner_user_id
          AND course_id=NEW.course_id AND mode='generated' AND state='ready'
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'flashcard generation requires an owned private workspace');
END;
