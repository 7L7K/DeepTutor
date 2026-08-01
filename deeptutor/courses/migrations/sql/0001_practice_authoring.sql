CREATE TABLE IF NOT EXISTS practice_sets (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('manual', 'generated')),
    state TEXT NOT NULL CHECK (state IN ('draft', 'archived')),
    current_revision_id TEXT
        REFERENCES practice_set_revisions(id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    write_epoch INTEGER NOT NULL DEFAULT 1 CHECK (write_epoch >= 1),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    archived_at REAL
);
CREATE INDEX IF NOT EXISTS idx_practice_sets_course_updated
    ON practice_sets(course_id, updated_at DESC);

CREATE TRIGGER practice_sets_owner_matches_course_insert
BEFORE INSERT ON practice_sets
WHEN NOT EXISTS (
    SELECT 1 FROM courses
    WHERE id = NEW.course_id
      AND owner_user_id = NEW.owner_user_id
      AND state = 'active'
)
BEGIN
    SELECT RAISE(ABORT, 'practice set owner must match its Course');
END;

CREATE TRIGGER practice_sets_owner_matches_course_update
BEFORE UPDATE OF owner_user_id, course_id ON practice_sets
WHEN NOT EXISTS (
    SELECT 1 FROM courses
    WHERE id = NEW.course_id
      AND owner_user_id = NEW.owner_user_id
      AND state = 'active'
)
BEGIN
    SELECT RAISE(ABORT, 'practice set owner must match its Course');
END;

CREATE TRIGGER practice_sets_immutable_binding
BEFORE UPDATE OF id, owner_user_id, course_id, created_at ON practice_sets
BEGIN
    SELECT RAISE(ABORT, 'practice set ownership binding is immutable');
END;

CREATE TABLE IF NOT EXISTS practice_set_revisions (
    id TEXT PRIMARY KEY,
    practice_set_id TEXT NOT NULL
        REFERENCES practice_sets(id) ON DELETE RESTRICT,
    revision_number INTEGER NOT NULL CHECK (revision_number >= 1),
    state TEXT NOT NULL CHECK (state IN ('draft', 'ready', 'superseded')),
    source_snapshot_json TEXT NOT NULL DEFAULT '[]',
    objective_ids_json TEXT NOT NULL DEFAULT '[]',
    generation_receipt_json TEXT,
    created_at REAL NOT NULL,
    ready_at REAL,
    UNIQUE (practice_set_id, revision_number)
);
CREATE INDEX IF NOT EXISTS idx_practice_revisions_set_number
    ON practice_set_revisions(practice_set_id, revision_number DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_practice_revisions_one_ready
    ON practice_set_revisions(practice_set_id)
    WHERE state = 'ready';

CREATE TRIGGER practice_revisions_require_active_parents_insert
BEFORE INSERT ON practice_set_revisions
WHEN NOT EXISTS (
    SELECT 1
    FROM practice_sets
    JOIN courses ON courses.id = practice_sets.course_id
    WHERE practice_sets.id = NEW.practice_set_id
      AND practice_sets.state = 'draft'
      AND courses.state = 'active'
)
BEGIN
    SELECT RAISE(ABORT, 'practice revisions require active parents');
END;

CREATE TRIGGER practice_revisions_insert_as_draft
BEFORE INSERT ON practice_set_revisions
WHEN NEW.state != 'draft' OR NEW.ready_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'practice revisions must begin as drafts');
END;

CREATE TRIGGER practice_revisions_require_active_parents_update
BEFORE UPDATE ON practice_set_revisions
WHEN NOT EXISTS (
    SELECT 1
    FROM practice_sets
    JOIN courses ON courses.id = practice_sets.course_id
    WHERE practice_sets.id = OLD.practice_set_id
      AND practice_sets.state = 'draft'
      AND courses.state = 'active'
)
BEGIN
    SELECT RAISE(ABORT, 'practice revisions require active parents');
END;

CREATE TABLE IF NOT EXISTS practice_questions (
    id TEXT PRIMARY KEY,
    practice_set_revision_id TEXT NOT NULL
        REFERENCES practice_set_revisions(id) ON DELETE RESTRICT,
    question_type TEXT NOT NULL,
    prompt TEXT NOT NULL,
    answer_contract_json TEXT NOT NULL,
    explanation TEXT NOT NULL,
    objective_ids_json TEXT NOT NULL DEFAULT '[]',
    citation_json TEXT NOT NULL DEFAULT '[]',
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    created_at REAL NOT NULL,
    UNIQUE (practice_set_revision_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_practice_questions_revision_ordinal
    ON practice_questions(practice_set_revision_id, ordinal);

CREATE TRIGGER practice_sets_current_revision_matches_set
BEFORE UPDATE OF current_revision_id ON practice_sets
WHEN NEW.current_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM practice_set_revisions
    WHERE id = NEW.current_revision_id
      AND practice_set_id = NEW.id
 )
BEGIN
    SELECT RAISE(ABORT, 'practice set current revision must belong to the set');
END;

CREATE TRIGGER practice_sets_inserted_current_revision_matches_set
BEFORE INSERT ON practice_sets
WHEN NEW.current_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM practice_set_revisions
    WHERE id = NEW.current_revision_id
      AND practice_set_id = NEW.id
 )
BEGIN
    SELECT RAISE(ABORT, 'practice set current revision must belong to the set');
END;

CREATE TRIGGER practice_sets_current_revision_is_ready
BEFORE UPDATE OF current_revision_id ON practice_sets
WHEN NEW.current_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM practice_set_revisions
    WHERE id = NEW.current_revision_id
      AND practice_set_id = NEW.id
      AND state = 'ready'
 )
BEGIN
    SELECT RAISE(ABORT, 'practice set current revision must be ready');
END;

CREATE TRIGGER practice_sets_current_revision_cannot_clear
BEFORE UPDATE OF current_revision_id ON practice_sets
WHEN OLD.current_revision_id IS NOT NULL
 AND NEW.current_revision_id IS NULL
BEGIN
    SELECT RAISE(ABORT, 'practice set current revision cannot be cleared');
END;

CREATE TRIGGER practice_sets_current_revision_moves_forward
BEFORE UPDATE OF current_revision_id ON practice_sets
WHEN OLD.current_revision_id IS NOT NULL
 AND NEW.current_revision_id IS NOT OLD.current_revision_id
 AND NOT EXISTS (
    SELECT 1
    FROM practice_set_revisions AS newer
    JOIN practice_set_revisions AS older
      ON older.id = OLD.current_revision_id
    WHERE newer.id = NEW.current_revision_id
      AND newer.practice_set_id = NEW.id
      AND older.practice_set_id = NEW.id
      AND newer.revision_number > older.revision_number
 )
BEGIN
    SELECT RAISE(ABORT, 'practice set current revision must move forward');
END;

CREATE TRIGGER practice_sets_inserted_current_revision_is_ready
BEFORE INSERT ON practice_sets
WHEN NEW.current_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM practice_set_revisions
    WHERE id = NEW.current_revision_id
      AND practice_set_id = NEW.id
      AND state = 'ready'
 )
BEGIN
    SELECT RAISE(ABORT, 'practice set current revision must be ready');
END;

CREATE TRIGGER practice_sets_no_delete
BEFORE DELETE ON practice_sets
BEGIN
    SELECT RAISE(ABORT, 'practice sets are archive-only');
END;

CREATE TRIGGER practice_revisions_no_delete
BEFORE DELETE ON practice_set_revisions
BEGIN
    SELECT RAISE(ABORT, 'practice revisions are immutable history');
END;

CREATE TRIGGER practice_revisions_immutable_content
BEFORE UPDATE OF source_snapshot_json, objective_ids_json, generation_receipt_json
ON practice_set_revisions
WHEN OLD.state != 'draft'
BEGIN
    SELECT RAISE(ABORT, 'ready practice revision content is immutable');
END;

CREATE TRIGGER practice_revisions_immutable_identity
BEFORE UPDATE OF id, practice_set_id, revision_number, created_at
ON practice_set_revisions
BEGIN
    SELECT RAISE(ABORT, 'practice revision identity is immutable');
END;

CREATE TRIGGER practice_revisions_immutable_ready_at
BEFORE UPDATE OF ready_at ON practice_set_revisions
WHEN OLD.state != 'draft'
BEGIN
    SELECT RAISE(ABORT, 'ready practice revision timestamp is immutable');
END;

CREATE TRIGGER practice_revisions_ready_at_matches_state
BEFORE INSERT ON practice_set_revisions
WHEN (NEW.state = 'draft' AND NEW.ready_at IS NOT NULL)
  OR (NEW.state IN ('ready', 'superseded') AND NEW.ready_at IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'practice revision ready timestamp is inconsistent');
END;

CREATE TRIGGER practice_revisions_updated_ready_at_matches_state
BEFORE UPDATE OF state, ready_at ON practice_set_revisions
WHEN (NEW.state = 'draft' AND NEW.ready_at IS NOT NULL)
  OR (NEW.state IN ('ready', 'superseded') AND NEW.ready_at IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'practice revision ready timestamp is inconsistent');
END;

CREATE TRIGGER practice_revisions_valid_state_transition
BEFORE UPDATE OF state ON practice_set_revisions
WHEN NOT (
    (OLD.state = 'draft' AND NEW.state = 'ready')
    OR (OLD.state = 'ready' AND NEW.state = 'superseded')
    OR OLD.state = NEW.state
)
BEGIN
    SELECT RAISE(ABORT, 'invalid practice revision state transition');
END;

CREATE TRIGGER practice_revisions_ready_requires_question
BEFORE UPDATE OF state ON practice_set_revisions
WHEN OLD.state = 'draft'
 AND NEW.state = 'ready'
 AND NOT EXISTS (
    SELECT 1 FROM practice_questions
    WHERE practice_set_revision_id = OLD.id
 )
BEGIN
    SELECT RAISE(ABORT, 'ready practice revisions require a question');
END;

CREATE TRIGGER practice_questions_no_delete
BEFORE DELETE ON practice_questions
BEGIN
    SELECT RAISE(ABORT, 'practice questions are immutable history');
END;

CREATE TRIGGER practice_questions_insert_only_into_draft
BEFORE INSERT ON practice_questions
WHEN NOT EXISTS (
    SELECT 1
    FROM practice_set_revisions
    JOIN practice_sets
      ON practice_sets.id = practice_set_revisions.practice_set_id
    JOIN courses ON courses.id = practice_sets.course_id
    WHERE practice_set_revisions.id = NEW.practice_set_revision_id
      AND practice_set_revisions.state = 'draft'
      AND practice_sets.state = 'draft'
      AND courses.state = 'active'
)
BEGIN
    SELECT RAISE(ABORT, 'practice questions require active draft parents');
END;

CREATE TRIGGER practice_questions_require_active_parents_update
BEFORE UPDATE ON practice_questions
WHEN NOT EXISTS (
    SELECT 1
    FROM practice_set_revisions
    JOIN practice_sets
      ON practice_sets.id = practice_set_revisions.practice_set_id
    JOIN courses ON courses.id = practice_sets.course_id
    WHERE practice_set_revisions.id = OLD.practice_set_revision_id
      AND practice_sets.state = 'draft'
      AND courses.state = 'active'
)
BEGIN
    SELECT RAISE(ABORT, 'practice questions require active parents');
END;

CREATE TRIGGER practice_questions_immutable_identity
BEFORE UPDATE OF id, practice_set_revision_id, created_at ON practice_questions
BEGIN
    SELECT RAISE(ABORT, 'practice question identity is immutable');
END;

CREATE TRIGGER practice_questions_immutable_when_ready
BEFORE UPDATE ON practice_questions
WHEN EXISTS (
    SELECT 1 FROM practice_set_revisions
    WHERE id = OLD.practice_set_revision_id
      AND state != 'draft'
)
BEGIN
    SELECT RAISE(ABORT, 'ready practice questions are immutable');
END;
