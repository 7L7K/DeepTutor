ALTER TABLE flashcards ADD COLUMN hint TEXT;
ALTER TABLE flashcards ADD COLUMN card_type TEXT NOT NULL DEFAULT 'recall'
    CHECK (card_type IN ('definition','concept','comparison','application','process','recall'));

DROP TRIGGER flashcard_generation_operation_owned_insert;
DROP TRIGGER flashcard_generation_operation_immutable;
DROP TRIGGER flashcard_generation_operation_transition;
DROP TRIGGER flashcard_generation_operation_terminal_immutable;
DROP TRIGGER flashcard_generation_operation_no_delete;
DROP TRIGGER flashcard_generated_deck_ready_fence;
DROP TRIGGER flashcard_generated_card_insert_fence;
DROP TRIGGER flashcard_generation_complete_requires_ready_deck;
DROP TRIGGER flashcards_generated_ready_immutable;

ALTER TABLE flashcard_generation_operations RENAME TO flashcard_generation_operations_phase4;

CREATE TABLE flashcard_generation_operations (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    deck_id TEXT NOT NULL UNIQUE REFERENCES flashcard_decks(id) ON DELETE RESTRICT,
    supersedes_deck_id TEXT REFERENCES flashcard_decks(id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    source_snapshot_json TEXT NOT NULL,
    objective_ids_json TEXT NOT NULL,
    generation_brief_json TEXT NOT NULL,
    origin_json TEXT NOT NULL,
    candidate_output_json TEXT,
    candidate_revision INTEGER NOT NULL DEFAULT 0 CHECK (candidate_revision >= 0),
    provider_receipt_json TEXT,
    cancel_requested_at REAL,
    review_expires_at REAL,
    course_write_epoch INTEGER NOT NULL CHECK (course_write_epoch >= 1),
    deck_write_epoch INTEGER NOT NULL CHECK (deck_write_epoch >= 1),
    item_limit INTEGER NOT NULL CHECK (item_limit BETWEEN 1 AND 48),
    context_char_limit INTEGER NOT NULL CHECK (context_char_limit BETWEEN 1 AND 48000),
    state TEXT NOT NULL CHECK (state IN (
        'queued','running','awaiting_review','completed','failed','cancelling','cancelled'
    )),
    error_code TEXT CHECK (error_code IS NULL OR error_code IN (
        'provider_unavailable','provider_failed','invalid_output','source_changed',
        'authority_changed','interrupted','provider_timed_out','configuration_error',
        'quota_exceeded','insufficient_valid_cards','cancelled'
    )),
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    updated_at REAL NOT NULL,
    UNIQUE(course_id, idempotency_key)
);

INSERT INTO flashcard_generation_operations (
    id,owner_user_id,course_id,deck_id,supersedes_deck_id,idempotency_key,
    request_fingerprint,source_snapshot_json,objective_ids_json,
    generation_brief_json,origin_json,candidate_output_json,candidate_revision,
    provider_receipt_json,cancel_requested_at,review_expires_at,
    course_write_epoch,deck_write_epoch,item_limit,context_char_limit,state,
    error_code,created_at,started_at,completed_at,updated_at
)
SELECT
    id,owner_user_id,course_id,deck_id,supersedes_deck_id,idempotency_key,
    request_fingerprint,source_snapshot_json,objective_ids_json,
    json_object(
        'focus',(SELECT title FROM flashcard_decks WHERE flashcard_decks.id=deck_id),
        'desired_count',CASE WHEN item_limit < 3 THEN 3 ELSE item_limit END,
        'card_type_mix',json_array('recall'),
        'difficulty','mixed',
        'answer_length','short',
        'include_hints',json('false')
    ),
    json_object('kind','workspace'),
    NULL,0,NULL,NULL,NULL,
    course_write_epoch,deck_write_epoch,item_limit,context_char_limit,state,
    error_code,created_at,started_at,completed_at,updated_at
FROM flashcard_generation_operations_phase4;

DROP TABLE flashcard_generation_operations_phase4;

CREATE INDEX idx_flashcard_generation_ops_course_updated
    ON flashcard_generation_operations(course_id, updated_at DESC, id);

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
 OR json_array_length(NEW.source_snapshot_json) NOT BETWEEN 1 AND 64
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
 OR json_valid(NEW.origin_json) != 1
 OR json_type(NEW.origin_json) != 'object'
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
    SELECT RAISE(ABORT, 'flashcard generation requires owned generated draft');
END;

CREATE TRIGGER flashcard_generation_operation_immutable
BEFORE UPDATE OF id,owner_user_id,course_id,deck_id,supersedes_deck_id,
    idempotency_key,request_fingerprint,source_snapshot_json,objective_ids_json,
    generation_brief_json,origin_json,course_write_epoch,deck_write_epoch,
    item_limit,context_char_limit,created_at
ON flashcard_generation_operations
BEGIN
    SELECT RAISE(ABORT, 'flashcard generation authority is immutable');
END;

CREATE TRIGGER flashcard_generation_candidate_monotonic
BEFORE UPDATE OF candidate_output_json,candidate_revision,provider_receipt_json,review_expires_at
ON flashcard_generation_operations
WHEN OLD.state != 'running'
 OR NEW.state != 'awaiting_review'
 OR OLD.candidate_output_json IS NOT NULL
 OR NEW.candidate_output_json IS NULL
 OR json_valid(NEW.candidate_output_json) != 1
 OR json_type(NEW.candidate_output_json) != 'array'
 OR json_array_length(NEW.candidate_output_json) < 1
 OR NEW.candidate_revision != OLD.candidate_revision + 1
 OR NEW.provider_receipt_json IS NULL
 OR json_valid(NEW.provider_receipt_json) != 1
 OR json_type(NEW.provider_receipt_json) != 'object'
 OR NEW.review_expires_at IS NULL
 OR NEW.review_expires_at <= NEW.updated_at
BEGIN
    SELECT RAISE(ABORT, 'invalid flashcard generation candidates');
END;

CREATE TRIGGER flashcard_generation_operation_transition
BEFORE UPDATE OF state,error_code,started_at,completed_at,cancel_requested_at
ON flashcard_generation_operations
WHEN NOT (
    (OLD.state='queued' AND NEW.state IN ('running','failed','cancelled'))
 OR (OLD.state='running' AND NEW.state IN ('awaiting_review','failed','cancelling'))
 OR (OLD.state='cancelling' AND NEW.state IN ('cancelled','failed'))
 OR (OLD.state='awaiting_review' AND NEW.state IN ('completed','cancelled'))
 )
 OR (
    NEW.state IN ('running','awaiting_review','cancelling')
    AND (NEW.started_at IS NULL OR NEW.completed_at IS NOT NULL OR NEW.error_code IS NOT NULL)
 )
 OR (
    NEW.state='completed'
    AND (NEW.completed_at IS NULL OR NEW.error_code IS NOT NULL)
 )
 OR (
    NEW.state='failed'
    AND (NEW.completed_at IS NULL OR NEW.error_code IS NULL)
 )
 OR (
    NEW.state='cancelled'
    AND (NEW.completed_at IS NULL OR NEW.error_code != 'cancelled')
 )
 OR (
    NEW.state IN ('cancelling','cancelled') AND NEW.cancel_requested_at IS NULL
 )
 OR NEW.updated_at < OLD.updated_at
BEGIN
    SELECT RAISE(ABORT, 'invalid flashcard generation transition');
END;

CREATE TRIGGER flashcard_generation_operation_terminal_immutable
BEFORE UPDATE ON flashcard_generation_operations
WHEN OLD.state IN ('completed','failed','cancelled')
BEGIN
    SELECT RAISE(ABORT, 'terminal flashcard generation operations are immutable');
END;

CREATE TRIGGER flashcard_generation_operation_no_delete
BEFORE DELETE ON flashcard_generation_operations
BEGIN
    SELECT RAISE(ABORT, 'flashcard generation operations are retained');
END;

CREATE TRIGGER flashcard_generated_deck_ready_fence
BEFORE UPDATE OF state,ready_at ON flashcard_decks
WHEN OLD.mode='generated' AND OLD.state='draft' AND NEW.state='ready'
 AND NOT EXISTS (
    SELECT 1 FROM flashcard_generation_operations
    WHERE deck_id=OLD.id AND state='awaiting_review'
 )
BEGIN
    SELECT RAISE(ABORT, 'generated flashcard deck requires reviewed candidates');
END;

CREATE TRIGGER flashcard_generated_card_insert_fence
BEFORE INSERT ON flashcards
WHEN EXISTS (
    SELECT 1 FROM flashcard_decks WHERE id=NEW.deck_id AND mode='generated'
 )
 AND NOT EXISTS (
    SELECT 1 FROM flashcard_generation_operations
    WHERE deck_id=NEW.deck_id AND state='awaiting_review'
 )
BEGIN
    SELECT RAISE(ABORT, 'generated flashcards require reviewed candidates');
END;

CREATE TRIGGER flashcard_generation_complete_requires_ready_deck
BEFORE UPDATE OF state ON flashcard_generation_operations
WHEN OLD.state='awaiting_review' AND NEW.state='completed'
 AND NOT EXISTS (
    SELECT 1 FROM flashcard_decks WHERE id=OLD.deck_id AND state='ready'
 )
BEGIN
    SELECT RAISE(ABORT, 'completed flashcard generation requires ready deck');
END;

CREATE TRIGGER flashcards_generated_ready_immutable
BEFORE UPDATE OF prompt,answer,hint,card_type,objective_ids_json,citation_json,ordinal
ON flashcards
WHEN EXISTS (
    SELECT 1 FROM flashcard_decks
    WHERE id=OLD.deck_id AND mode='generated' AND state='ready'
)
BEGIN
    SELECT RAISE(ABORT, 'ready generated flashcards are immutable');
END;
