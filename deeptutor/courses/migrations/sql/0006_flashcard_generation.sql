ALTER TABLE flashcard_decks ADD COLUMN supersedes_deck_id TEXT
    REFERENCES flashcard_decks(id) ON DELETE RESTRICT;
CREATE INDEX idx_flashcard_decks_supersedes ON flashcard_decks(supersedes_deck_id);

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
    course_write_epoch INTEGER NOT NULL CHECK (course_write_epoch >= 1),
    deck_write_epoch INTEGER NOT NULL CHECK (deck_write_epoch >= 1),
    item_limit INTEGER NOT NULL CHECK (item_limit BETWEEN 1 AND 48),
    context_char_limit INTEGER NOT NULL CHECK (context_char_limit BETWEEN 1 AND 48000),
    state TEXT NOT NULL CHECK (state IN ('queued','running','completed','failed')),
    error_code TEXT CHECK (error_code IS NULL OR error_code IN ('provider_unavailable','provider_failed','invalid_output','source_changed','authority_changed','interrupted','provider_timed_out')),
    created_at REAL NOT NULL, started_at REAL, completed_at REAL, updated_at REAL NOT NULL,
    UNIQUE(course_id, idempotency_key)
);
CREATE INDEX idx_flashcard_generation_ops_course_updated
    ON flashcard_generation_operations(course_id, updated_at DESC, id);

CREATE TRIGGER flashcard_generation_operation_owned_insert
BEFORE INSERT ON flashcard_generation_operations
WHEN NEW.id NOT LIKE 'ofg_%' OR length(NEW.id) < 5 OR length(NEW.id) > 80
 OR length(NEW.idempotency_key) < 1 OR length(NEW.idempotency_key) > 160
 OR length(NEW.request_fingerprint) != 64
 OR NEW.state != 'queued' OR NEW.error_code IS NOT NULL OR NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL
 OR json_valid(NEW.source_snapshot_json) != 1 OR json_type(NEW.source_snapshot_json) != 'array'
 OR json_array_length(NEW.source_snapshot_json) NOT BETWEEN 1 AND 64
 OR EXISTS (SELECT 1 FROM json_each(NEW.source_snapshot_json) AS receipt WHERE json_type(receipt.value) != 'object'
       OR (SELECT count(*) FROM json_each(receipt.value)) != 3
       OR json_type(receipt.value,'$.source_id') != 'text' OR json_extract(receipt.value,'$.source_id') NOT LIKE 'src_%' OR length(json_extract(receipt.value,'$.source_id')) > 80
       OR json_type(receipt.value,'$.source_revision') != 'integer' OR json_extract(receipt.value,'$.source_revision') < 1
       OR json_type(receipt.value,'$.content_sha256') != 'text' OR length(json_extract(receipt.value,'$.content_sha256')) != 64
       OR json_extract(receipt.value,'$.content_sha256') GLOB '*[^0-9a-f]*')
 OR json_valid(NEW.objective_ids_json) != 1 OR json_type(NEW.objective_ids_json) != 'array'
 OR json_array_length(NEW.objective_ids_json) > 64
 OR NOT EXISTS (SELECT 1 FROM courses WHERE id = NEW.course_id AND owner_user_id = NEW.owner_user_id AND state = 'active' AND write_epoch = NEW.course_write_epoch)
 OR NOT EXISTS (SELECT 1 FROM flashcard_decks WHERE id = NEW.deck_id AND owner_user_id = NEW.owner_user_id AND course_id = NEW.course_id AND mode = 'generated' AND state = 'draft' AND write_epoch = NEW.deck_write_epoch AND source_snapshot_json = NEW.source_snapshot_json)
 OR (NEW.supersedes_deck_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM flashcard_decks WHERE id = NEW.supersedes_deck_id AND owner_user_id = NEW.owner_user_id AND course_id = NEW.course_id AND mode = 'generated' AND state = 'ready'))
BEGIN SELECT RAISE(ABORT, 'flashcard generation requires owned generated draft'); END;

CREATE TRIGGER flashcard_generation_operation_immutable
BEFORE UPDATE OF id, owner_user_id, course_id, deck_id, supersedes_deck_id, idempotency_key,
    request_fingerprint, source_snapshot_json, objective_ids_json, course_write_epoch,
    deck_write_epoch, item_limit, context_char_limit, created_at ON flashcard_generation_operations
BEGIN SELECT RAISE(ABORT, 'flashcard generation authority is immutable'); END;

CREATE TRIGGER flashcard_generation_operation_transition
BEFORE UPDATE OF state, error_code, started_at, completed_at ON flashcard_generation_operations
WHEN NOT ((OLD.state = 'queued' AND NEW.state IN ('running','failed')) OR (OLD.state = 'running' AND NEW.state IN ('completed','failed')))
 OR (NEW.state = 'running' AND (NEW.started_at IS NULL OR NEW.error_code IS NOT NULL OR NEW.completed_at IS NOT NULL))
 OR (NEW.state = 'completed' AND (NEW.completed_at IS NULL OR NEW.error_code IS NOT NULL))
 OR (NEW.state = 'failed' AND (NEW.completed_at IS NULL OR NEW.error_code IS NULL))
 OR NEW.updated_at < OLD.updated_at
BEGIN SELECT RAISE(ABORT, 'invalid flashcard generation transition'); END;

CREATE TRIGGER flashcard_generation_operation_terminal_immutable
BEFORE UPDATE ON flashcard_generation_operations
WHEN OLD.state IN ('completed','failed')
BEGIN SELECT RAISE(ABORT, 'terminal flashcard generation operations are immutable'); END;

CREATE TRIGGER flashcard_generation_operation_no_delete
BEFORE DELETE ON flashcard_generation_operations
BEGIN SELECT RAISE(ABORT, 'flashcard generation operations are retained'); END;

CREATE TRIGGER flashcard_generated_deck_binding
BEFORE INSERT ON flashcard_decks
WHEN NEW.mode = 'generated' AND NEW.generation_receipt_json IS NULL
BEGIN SELECT RAISE(ABORT, 'generated flashcard deck needs generation receipt binding'); END;

CREATE TRIGGER flashcard_generated_deck_ready_fence
BEFORE UPDATE OF state, ready_at ON flashcard_decks
WHEN OLD.mode = 'generated' AND OLD.state = 'draft' AND NEW.state = 'ready'
 AND NOT EXISTS (SELECT 1 FROM flashcard_generation_operations WHERE deck_id = OLD.id AND state = 'running')
BEGIN SELECT RAISE(ABORT, 'generated flashcard deck requires running operation'); END;

CREATE TRIGGER flashcard_generated_card_insert_fence
BEFORE INSERT ON flashcards
WHEN EXISTS (SELECT 1 FROM flashcard_decks WHERE id = NEW.deck_id AND mode = 'generated')
 AND NOT EXISTS (SELECT 1 FROM flashcard_generation_operations WHERE deck_id = NEW.deck_id AND state = 'running')
BEGIN SELECT RAISE(ABORT, 'generated flashcards require running generation operation'); END;

CREATE TRIGGER flashcard_generation_complete_requires_ready_deck
BEFORE UPDATE OF state ON flashcard_generation_operations
WHEN OLD.state = 'running' AND NEW.state = 'completed'
 AND NOT EXISTS (SELECT 1 FROM flashcard_decks WHERE id = OLD.deck_id AND state = 'ready')
BEGIN SELECT RAISE(ABORT, 'completed flashcard generation requires ready deck'); END;
