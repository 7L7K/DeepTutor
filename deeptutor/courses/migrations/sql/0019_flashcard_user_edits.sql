-- Ready generated decks remain source-immutable, but learners may correct or
-- extend the deck through the same card-editing API used by manual decks.
ALTER TABLE flashcards ADD COLUMN edited_by_user INTEGER NOT NULL DEFAULT 0
    CHECK (edited_by_user IN (0, 1));

DROP TRIGGER flashcard_generated_card_insert_fence;
DROP TRIGGER flashcards_generated_ready_immutable;
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
    json_extract(NEW.origin_json,'$.kind') = 'topic'
    AND (
        json_array_length(NEW.source_snapshot_json) != 0
        OR json_type(NEW.origin_json,'$.session_id') != 'null'
        OR json_type(NEW.origin_json,'$.message_id') != 'null'
        OR json_type(NEW.origin_json,'$.practice_attempt_id') != 'null'
        OR json_type(NEW.origin_json,'$.selected_message_ids') != 'array'
        OR json_array_length(json_extract(NEW.origin_json,'$.selected_message_ids')) != 0
        OR json_type(NEW.origin_json,'$.context_sha256') != 'null'
        OR json_type(NEW.origin_json,'$.context_summary') != 'null'
        OR NOT EXISTS (
            SELECT 1 FROM courses
            WHERE id=NEW.course_id AND owner_user_id=NEW.owner_user_id
              AND workspace_kind='academic_course'
        )
    )
 )
 OR (
    json_extract(NEW.origin_json,'$.kind') NOT IN ('general_chat', 'topic')
    AND (
        json_type(NEW.origin_json,'$.selected_message_ids') != 'array'
        OR json_array_length(json_extract(NEW.origin_json,'$.selected_message_ids')) != 0
        OR json_type(NEW.origin_json,'$.context_sha256') != 'null'
        OR json_type(NEW.origin_json,'$.context_summary') != 'null'
        OR json_array_length(NEW.source_snapshot_json) NOT BETWEEN 1 AND 64
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

CREATE TRIGGER flashcard_generated_card_insert_fence
BEFORE INSERT ON flashcards
WHEN EXISTS (
    SELECT 1 FROM flashcard_decks
    WHERE id=NEW.deck_id AND mode='generated' AND state!='ready'
)
 AND NOT EXISTS (
    SELECT 1 FROM flashcard_generation_operations
    WHERE deck_id=NEW.deck_id AND state='awaiting_review'
 )
BEGIN
    SELECT RAISE(ABORT, 'generated flashcards require reviewed candidates');
END;

CREATE TRIGGER flashcards_generated_ready_provenance_immutable
BEFORE UPDATE OF hint,card_type,citation_json,ordinal
ON flashcards
WHEN EXISTS (
    SELECT 1 FROM flashcard_decks
    WHERE id=OLD.deck_id AND mode='generated' AND state='ready'
)
BEGIN
    SELECT RAISE(ABORT, 'ready generated flashcard provenance is immutable');
END;
