CREATE TABLE IF NOT EXISTS flashcard_decks (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('manual', 'generated')),
    state TEXT NOT NULL CHECK (state IN ('draft', 'ready', 'archived')),
    source_snapshot_json TEXT NOT NULL DEFAULT '[]',
    generation_receipt_json TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    write_epoch INTEGER NOT NULL DEFAULT 1 CHECK (write_epoch >= 1),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    ready_at REAL,
    archived_at REAL
);
CREATE INDEX IF NOT EXISTS idx_flashcard_decks_course_updated
    ON flashcard_decks(course_id, updated_at DESC, id);

CREATE TRIGGER flashcard_decks_owner_matches_course_insert
BEFORE INSERT ON flashcard_decks
WHEN NEW.id NOT LIKE 'dck_%'
 OR length(NEW.id) < 5
 OR length(NEW.id) > 80
 OR NEW.state != 'draft'
 OR NEW.ready_at IS NOT NULL
 OR NEW.archived_at IS NOT NULL
 OR json_valid(NEW.source_snapshot_json) != 1
 OR json_type(NEW.source_snapshot_json) != 'array'
 OR (NEW.generation_receipt_json IS NOT NULL AND json_valid(NEW.generation_receipt_json) != 1)
 OR NOT EXISTS (
    SELECT 1 FROM courses
    WHERE id = NEW.course_id AND owner_user_id = NEW.owner_user_id AND state = 'active'
 )
BEGIN
    SELECT RAISE(ABORT, 'flashcard deck requires owned active Course draft');
END;

CREATE TRIGGER flashcard_decks_immutable_binding
BEFORE UPDATE OF id, owner_user_id, course_id, mode, source_snapshot_json,
    generation_receipt_json, created_at ON flashcard_decks
BEGIN
    SELECT RAISE(ABORT, 'flashcard deck ownership and provenance are immutable');
END;

CREATE TRIGGER flashcard_decks_valid_transition
BEFORE UPDATE OF state, ready_at, archived_at ON flashcard_decks
WHEN NOT (
    (OLD.state = 'draft' AND NEW.state IN ('draft', 'ready', 'archived'))
    OR (OLD.state = 'ready' AND NEW.state IN ('ready', 'archived'))
    OR (OLD.state = 'archived' AND NEW.state IN ('archived', 'draft', 'ready'))
 )
 OR (NEW.state = 'draft' AND (NEW.ready_at IS NOT NULL OR NEW.archived_at IS NOT NULL))
 OR (NEW.state = 'ready' AND (NEW.ready_at IS NULL OR NEW.archived_at IS NOT NULL))
 OR (NEW.state = 'archived' AND NEW.archived_at IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'invalid flashcard deck state transition');
END;

CREATE TRIGGER flashcard_decks_no_delete
BEFORE DELETE ON flashcard_decks
BEGIN
    SELECT RAISE(ABORT, 'flashcard decks are archive-only');
END;

CREATE TABLE IF NOT EXISTS flashcards (
    id TEXT PRIMARY KEY,
    deck_id TEXT NOT NULL REFERENCES flashcard_decks(id) ON DELETE RESTRICT,
    prompt TEXT NOT NULL,
    answer TEXT NOT NULL,
    objective_ids_json TEXT NOT NULL DEFAULT '[]',
    citation_json TEXT NOT NULL DEFAULT '[]',
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    state TEXT NOT NULL CHECK (state IN ('active', 'archived')),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    archived_at REAL,
    UNIQUE(deck_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_flashcards_deck_ordinal
    ON flashcards(deck_id, ordinal, id);

CREATE TRIGGER flashcards_require_active_parent_insert
BEFORE INSERT ON flashcards
WHEN NEW.id NOT LIKE 'crd_%'
 OR length(NEW.id) < 5
 OR length(NEW.id) > 80
 OR NEW.state != 'active'
 OR NEW.archived_at IS NOT NULL
 OR json_valid(NEW.objective_ids_json) != 1
 OR json_type(NEW.objective_ids_json) != 'array'
 OR json_valid(NEW.citation_json) != 1
 OR json_type(NEW.citation_json) != 'array'
 OR NOT EXISTS (
    SELECT 1 FROM flashcard_decks
    JOIN courses ON courses.id = flashcard_decks.course_id
    WHERE flashcard_decks.id = NEW.deck_id
      AND flashcard_decks.state IN ('draft', 'ready')
      AND courses.state = 'active'
 )
BEGIN
    SELECT RAISE(ABORT, 'flashcard requires active owned deck');
END;

CREATE TRIGGER flashcards_immutable_binding
BEFORE UPDATE OF id, deck_id, created_at ON flashcards
BEGIN
    SELECT RAISE(ABORT, 'flashcard ownership binding is immutable');
END;

CREATE TRIGGER flashcards_require_active_parent_update
BEFORE UPDATE ON flashcards
WHEN NOT EXISTS (
    SELECT 1 FROM flashcard_decks
    JOIN courses ON courses.id = flashcard_decks.course_id
    WHERE flashcard_decks.id = OLD.deck_id
      AND flashcard_decks.state IN ('draft', 'ready')
      AND courses.state = 'active'
)
BEGIN
    SELECT RAISE(ABORT, 'flashcard requires active owned deck');
END;

CREATE TRIGGER flashcards_valid_state_transition
BEFORE UPDATE OF state, archived_at ON flashcards
WHEN NOT (
    (OLD.state = 'active' AND NEW.state IN ('active', 'archived'))
    OR OLD.state = NEW.state
)
 OR (NEW.state = 'active' AND NEW.archived_at IS NOT NULL)
 OR (NEW.state = 'archived' AND NEW.archived_at IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'invalid flashcard state transition');
END;

CREATE TRIGGER flashcards_generated_ready_immutable
BEFORE UPDATE OF prompt, answer, objective_ids_json, citation_json, ordinal
ON flashcards
WHEN EXISTS (
    SELECT 1 FROM flashcard_decks
    WHERE id = OLD.deck_id AND mode = 'generated' AND state = 'ready'
)
BEGIN
    SELECT RAISE(ABORT, 'ready generated flashcards are immutable');
END;

CREATE TRIGGER flashcards_no_delete
BEFORE DELETE ON flashcards
BEGIN
    SELECT RAISE(ABORT, 'flashcards are archive-only');
END;

CREATE TABLE IF NOT EXISTS flashcard_reviews (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    deck_id TEXT NOT NULL REFERENCES flashcard_decks(id) ON DELETE RESTRICT,
    card_id TEXT NOT NULL REFERENCES flashcards(id) ON DELETE RESTRICT,
    rating TEXT NOT NULL CHECK (rating IN ('again', 'hard', 'good', 'easy')),
    idempotency_key TEXT NOT NULL,
    course_write_epoch INTEGER NOT NULL CHECK (course_write_epoch >= 1),
    deck_revision INTEGER NOT NULL CHECK (deck_revision >= 1),
    card_revision INTEGER NOT NULL CHECK (card_revision >= 1),
    review_count INTEGER NOT NULL CHECK (review_count >= 1),
    interval_seconds INTEGER NOT NULL CHECK (interval_seconds >= 1),
    was_due INTEGER NOT NULL CHECK (was_due IN (0, 1)),
    reviewed_at REAL NOT NULL,
    next_review_at REAL NOT NULL,
    UNIQUE(deck_id, idempotency_key),
    UNIQUE(card_id, review_count)
);
CREATE INDEX IF NOT EXISTS idx_flashcard_reviews_deck_reviewed
    ON flashcard_reviews(deck_id, reviewed_at DESC, id);

CREATE TABLE IF NOT EXISTS flashcard_review_states (
    card_id TEXT PRIMARY KEY REFERENCES flashcards(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    deck_id TEXT NOT NULL REFERENCES flashcard_decks(id) ON DELETE RESTRICT,
    review_count INTEGER NOT NULL DEFAULT 0 CHECK (review_count >= 0),
    interval_seconds INTEGER NOT NULL DEFAULT 0 CHECK (interval_seconds >= 0),
    next_review_at REAL NOT NULL,
    last_review_id TEXT REFERENCES flashcard_reviews(id) ON DELETE RESTRICT,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_flashcard_review_states_deck_due
    ON flashcard_review_states(deck_id, next_review_at, card_id);

CREATE TRIGGER flashcard_review_states_requires_card_insert
BEFORE INSERT ON flashcard_review_states
WHEN NEW.review_count != 0
 OR NEW.interval_seconds != 0
 OR NEW.last_review_id IS NOT NULL
 OR NOT EXISTS (
    SELECT 1 FROM flashcards
    JOIN flashcard_decks ON flashcard_decks.id = flashcards.deck_id
    JOIN courses ON courses.id = flashcard_decks.course_id
    WHERE flashcards.id = NEW.card_id
      AND flashcards.deck_id = NEW.deck_id
      AND flashcard_decks.course_id = NEW.course_id
      AND courses.owner_user_id = NEW.owner_user_id
 )
BEGIN
    SELECT RAISE(ABORT, 'flashcard review state requires owned card');
END;

CREATE TRIGGER flashcard_review_states_immutable_binding
BEFORE UPDATE OF card_id, owner_user_id, course_id, deck_id ON flashcard_review_states
BEGIN
    SELECT RAISE(ABORT, 'flashcard review state ownership is immutable');
END;

CREATE TRIGGER flashcard_review_states_no_delete
BEFORE DELETE ON flashcard_review_states
BEGIN
    SELECT RAISE(ABORT, 'flashcard review state is retained');
END;

CREATE TRIGGER flashcard_reviews_require_owned_ready_card
BEFORE INSERT ON flashcard_reviews
WHEN NEW.id NOT LIKE 'rvw_%'
 OR length(NEW.id) < 5
 OR length(NEW.id) > 80
 OR length(NEW.idempotency_key) < 1
 OR length(NEW.idempotency_key) > 160
 OR NEW.next_review_at < NEW.reviewed_at
 OR NOT EXISTS (
    SELECT 1 FROM flashcards
    JOIN flashcard_decks ON flashcard_decks.id = flashcards.deck_id
    JOIN courses ON courses.id = flashcard_decks.course_id
    JOIN flashcard_review_states ON flashcard_review_states.card_id = flashcards.id
    WHERE flashcards.id = NEW.card_id
      AND flashcards.deck_id = NEW.deck_id
      AND flashcards.state = 'active'
      AND flashcard_decks.course_id = NEW.course_id
      AND flashcard_decks.owner_user_id = NEW.owner_user_id
      AND flashcard_decks.state = 'ready'
      AND courses.write_epoch = NEW.course_write_epoch
      AND flashcard_decks.revision = NEW.deck_revision
      AND flashcards.revision = NEW.card_revision
      AND courses.state = 'active'
      AND flashcard_review_states.review_count + 1 = NEW.review_count
      AND flashcard_review_states.deck_id = NEW.deck_id
      AND flashcard_review_states.course_id = NEW.course_id
      AND flashcard_review_states.owner_user_id = NEW.owner_user_id
 )
BEGIN
    SELECT RAISE(ABORT, 'flashcard review requires owned ready current card');
END;

CREATE TRIGGER flashcard_reviews_immutable
BEFORE UPDATE ON flashcard_reviews
BEGIN
    SELECT RAISE(ABORT, 'flashcard reviews are append-only');
END;

CREATE TRIGGER flashcard_reviews_no_delete
BEFORE DELETE ON flashcard_reviews
BEGIN
    SELECT RAISE(ABORT, 'flashcard reviews are retained history');
END;

CREATE TRIGGER flashcard_review_state_requires_matching_review
BEFORE UPDATE OF review_count, interval_seconds, next_review_at, last_review_id, updated_at
ON flashcard_review_states
WHEN NEW.review_count != OLD.review_count + 1
 OR NEW.last_review_id IS NULL
 OR NOT EXISTS (
    SELECT 1 FROM flashcard_reviews
    WHERE id = NEW.last_review_id
      AND card_id = NEW.card_id
      AND deck_id = NEW.deck_id
      AND course_id = NEW.course_id
      AND owner_user_id = NEW.owner_user_id
      AND review_count = NEW.review_count
      AND interval_seconds = NEW.interval_seconds
      AND next_review_at = NEW.next_review_at
      AND reviewed_at = NEW.updated_at
 )
BEGIN
    SELECT RAISE(ABORT, 'flashcard schedule requires matching review');
END;
