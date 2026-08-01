CREATE TABLE IF NOT EXISTS quiz_attempts (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    practice_set_id TEXT NOT NULL REFERENCES practice_sets(id) ON DELETE RESTRICT,
    practice_set_revision_id TEXT NOT NULL
        REFERENCES practice_set_revisions(id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state IN (
        'in_progress', 'submitted', 'graded', 'abandoned', 'archived'
    )),
    score_json TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    course_write_epoch INTEGER NOT NULL CHECK (course_write_epoch >= 1),
    practice_set_write_epoch INTEGER NOT NULL CHECK (practice_set_write_epoch >= 1),
    started_at REAL NOT NULL,
    submitted_at REAL,
    graded_at REAL,
    archived_at REAL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quiz_attempts_course_updated
    ON quiz_attempts(course_id, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_quiz_attempts_one_in_progress_set
    ON quiz_attempts(owner_user_id, practice_set_id)
    WHERE state = 'in_progress';

CREATE TABLE IF NOT EXISTS quiz_attempt_items (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES quiz_attempts(id) ON DELETE RESTRICT,
    question_id TEXT NOT NULL REFERENCES practice_questions(id) ON DELETE RESTRICT,
    display_ordinal INTEGER NOT NULL CHECK (display_ordinal >= 1),
    option_order_json TEXT,
    randomized_values_json TEXT,
    grading_json TEXT,
    error_type TEXT,
    graded_at REAL,
    UNIQUE (attempt_id, question_id),
    UNIQUE (attempt_id, display_ordinal)
);
CREATE INDEX IF NOT EXISTS idx_quiz_attempt_items_attempt_ordinal
    ON quiz_attempt_items(attempt_id, display_ordinal);

CREATE TABLE IF NOT EXISTS quiz_attempt_answers (
    attempt_item_id TEXT PRIMARY KEY
        REFERENCES quiz_attempt_items(id) ON DELETE RESTRICT,
    response_json TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    answered_at REAL
);

CREATE TABLE IF NOT EXISTS quiz_attempt_autosave_receipts (
    attempt_id TEXT NOT NULL REFERENCES quiz_attempts(id) ON DELETE RESTRICT,
    idempotency_token TEXT NOT NULL,
    attempt_item_id TEXT NOT NULL REFERENCES quiz_attempt_items(id) ON DELETE RESTRICT,
    payload_sha256 TEXT NOT NULL,
    response_json TEXT NOT NULL,
    answer_revision INTEGER NOT NULL CHECK (answer_revision >= 1),
    answered_at REAL NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (attempt_id, idempotency_token)
);

CREATE TRIGGER quiz_attempts_require_active_ready_binding_insert
BEFORE INSERT ON quiz_attempts
WHEN NOT EXISTS (
    SELECT 1
    FROM courses
    JOIN practice_sets ON practice_sets.course_id = courses.id
    JOIN practice_set_revisions ON practice_set_revisions.practice_set_id = practice_sets.id
    WHERE courses.id = NEW.course_id
      AND courses.owner_user_id = NEW.owner_user_id
      AND courses.state = 'active'
      AND courses.write_epoch = NEW.course_write_epoch
      AND practice_sets.id = NEW.practice_set_id
      AND practice_sets.state = 'draft'
      AND practice_sets.write_epoch = NEW.practice_set_write_epoch
      AND practice_set_revisions.id = NEW.practice_set_revision_id
      AND practice_set_revisions.state = 'ready'
)
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt requires active ready Course Practice revision');
END;

CREATE TRIGGER quiz_attempts_begin_in_progress
BEFORE INSERT ON quiz_attempts
WHEN NEW.state != 'in_progress'
  OR NEW.score_json IS NOT NULL
  OR NEW.revision != 1
  OR NEW.submitted_at IS NOT NULL
  OR NEW.graded_at IS NOT NULL
  OR NEW.archived_at IS NOT NULL
  OR NEW.updated_at != NEW.started_at
BEGIN
    SELECT RAISE(ABORT, 'quiz attempts must begin clean and in progress');
END;

CREATE TRIGGER quiz_attempts_immutable_binding
BEFORE UPDATE OF id, owner_user_id, course_id, practice_set_id,
    practice_set_revision_id, course_write_epoch, practice_set_write_epoch, started_at
ON quiz_attempts
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt binding is immutable');
END;

CREATE TRIGGER quiz_attempts_state_transition
BEFORE UPDATE OF state, submitted_at, graded_at, archived_at ON quiz_attempts
WHEN NOT (
    (OLD.state = 'in_progress' AND NEW.state IN ('in_progress', 'submitted', 'abandoned', 'archived'))
    OR (OLD.state = 'submitted' AND NEW.state IN ('submitted', 'graded', 'archived'))
    OR (OLD.state = 'graded' AND NEW.state IN ('graded', 'archived'))
    OR (OLD.state = 'abandoned' AND NEW.state = 'abandoned')
    OR (OLD.state = 'archived' AND NEW.state = 'archived')
)
 OR (
    NEW.state != 'archived'
    AND NOT EXISTS (
        SELECT 1 FROM courses
        JOIN practice_sets ON practice_sets.course_id = courses.id
        WHERE courses.id = NEW.course_id
          AND courses.owner_user_id = NEW.owner_user_id
          AND courses.state = 'active'
          AND courses.write_epoch = NEW.course_write_epoch
          AND practice_sets.id = NEW.practice_set_id
          AND practice_sets.state = 'draft'
          AND practice_sets.write_epoch = NEW.practice_set_write_epoch
    )
)
BEGIN
    SELECT RAISE(ABORT, 'invalid quiz attempt state transition');
END;

CREATE TRIGGER quiz_attempts_terminal_timestamps
BEFORE UPDATE OF state, submitted_at, graded_at, archived_at ON quiz_attempts
WHEN (NEW.state = 'in_progress' AND (
        NEW.submitted_at IS NOT NULL OR NEW.graded_at IS NOT NULL OR NEW.archived_at IS NOT NULL
    ))
  OR (NEW.state = 'abandoned' AND (
        NEW.submitted_at IS NOT NULL OR NEW.graded_at IS NOT NULL OR NEW.archived_at IS NOT NULL
    ))
  OR (NEW.state = 'submitted' AND (
        NEW.submitted_at IS NULL OR NEW.graded_at IS NOT NULL OR NEW.archived_at IS NOT NULL
    ))
  OR (NEW.state = 'graded' AND (
        NEW.submitted_at IS NULL OR NEW.graded_at IS NULL OR NEW.archived_at IS NOT NULL
    ))
  OR (NEW.state = 'archived' AND NEW.archived_at IS NULL)
  OR (NEW.state = 'archived' AND OLD.state IN ('in_progress', 'abandoned') AND (
        NEW.submitted_at IS NOT NULL OR NEW.graded_at IS NOT NULL
    ))
  OR (NEW.state = 'archived' AND OLD.state = 'submitted' AND (
        NEW.submitted_at IS NULL OR NEW.graded_at IS NOT NULL
    ))
  OR (NEW.state = 'archived' AND OLD.state = 'graded' AND (
        NEW.submitted_at IS NULL OR NEW.graded_at IS NULL
    ))
  OR NEW.updated_at < NEW.started_at
  OR (NEW.submitted_at IS NOT NULL AND NEW.submitted_at < NEW.started_at)
  OR (NEW.graded_at IS NOT NULL AND (
        NEW.submitted_at IS NULL OR NEW.graded_at < NEW.submitted_at
    ))
  OR (NEW.state = 'submitted' AND NEW.submitted_at != NEW.updated_at)
  OR (NEW.state = 'graded' AND NEW.graded_at != NEW.updated_at)
  OR (NEW.state = 'archived' AND NEW.archived_at != NEW.updated_at)
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt terminal timestamps are inconsistent');
END;

CREATE TRIGGER quiz_attempts_state_change_moves_forward
BEFORE UPDATE OF state ON quiz_attempts
WHEN NEW.state != OLD.state
 AND (
    NEW.revision != OLD.revision + 1
    OR NEW.updated_at <= OLD.updated_at
 )
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt state changes must move revision forward');
END;

CREATE TRIGGER quiz_attempts_grading_reserved
BEFORE UPDATE OF score_json, graded_at ON quiz_attempts
WHEN NEW.score_json IS NOT OLD.score_json
  OR NEW.graded_at IS NOT OLD.graded_at
BEGIN
    SELECT RAISE(ABORT, 'quiz grading is reserved for P4-03');
END;

CREATE TRIGGER quiz_attempts_no_delete
BEFORE DELETE ON quiz_attempts
BEGIN
    SELECT RAISE(ABORT, 'quiz attempts are retained history');
END;

CREATE TRIGGER quiz_attempt_items_require_matching_ready_question
BEFORE INSERT ON quiz_attempt_items
WHEN NOT EXISTS (
    SELECT 1
    FROM quiz_attempts
    JOIN practice_questions ON practice_questions.id = NEW.question_id
    WHERE quiz_attempts.id = NEW.attempt_id
      AND quiz_attempts.state = 'in_progress'
      AND practice_questions.practice_set_revision_id = quiz_attempts.practice_set_revision_id
)
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt item must use its attempt revision question');
END;

CREATE TRIGGER quiz_attempt_items_immutable
BEFORE UPDATE OF id, attempt_id, question_id, display_ordinal, option_order_json,
    randomized_values_json ON quiz_attempt_items
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt presentation is immutable');
END;

CREATE TRIGGER quiz_attempt_items_grading_reserved
BEFORE UPDATE OF grading_json, error_type, graded_at ON quiz_attempt_items
WHEN NEW.grading_json IS NOT OLD.grading_json
  OR NEW.error_type IS NOT OLD.error_type
  OR NEW.graded_at IS NOT OLD.graded_at
BEGIN
    SELECT RAISE(ABORT, 'quiz item grading is reserved for P4-03');
END;

CREATE TRIGGER quiz_attempt_items_no_delete
BEFORE DELETE ON quiz_attempt_items
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt items are retained history');
END;

CREATE TRIGGER quiz_attempt_answers_require_in_progress
BEFORE UPDATE OF response_json, revision, answered_at ON quiz_attempt_answers
WHEN NOT EXISTS (
    SELECT 1
    FROM quiz_attempt_items
    JOIN quiz_attempts ON quiz_attempts.id = quiz_attempt_items.attempt_id
    JOIN courses ON courses.id = quiz_attempts.course_id
    JOIN practice_sets ON practice_sets.id = quiz_attempts.practice_set_id
    WHERE quiz_attempt_items.id = OLD.attempt_item_id
      AND quiz_attempts.state = 'in_progress'
      AND courses.state = 'active'
      AND courses.write_epoch = quiz_attempts.course_write_epoch
      AND practice_sets.state = 'draft'
      AND practice_sets.write_epoch = quiz_attempts.practice_set_write_epoch
)
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt answers are frozen');
END;

CREATE TRIGGER quiz_attempt_answers_insert_requires_in_progress
BEFORE INSERT ON quiz_attempt_answers
WHEN NOT EXISTS (
    SELECT 1
    FROM quiz_attempt_items
    JOIN quiz_attempts ON quiz_attempts.id = quiz_attempt_items.attempt_id
    JOIN courses ON courses.id = quiz_attempts.course_id
    JOIN practice_sets ON practice_sets.id = quiz_attempts.practice_set_id
    WHERE quiz_attempt_items.id = NEW.attempt_item_id
      AND quiz_attempts.state = 'in_progress'
      AND courses.state = 'active'
      AND courses.write_epoch = quiz_attempts.course_write_epoch
      AND practice_sets.state = 'draft'
      AND practice_sets.write_epoch = quiz_attempts.practice_set_write_epoch
)
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt answers require an active attempt');
END;

CREATE TRIGGER quiz_attempt_answers_immutable_identity
BEFORE UPDATE OF attempt_item_id ON quiz_attempt_answers
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt answer identity is immutable');
END;

CREATE TRIGGER quiz_attempt_answers_insert_shape
BEFORE INSERT ON quiz_attempt_answers
WHEN NEW.response_json IS NOT NULL
  OR NEW.revision != 1
  OR NEW.answered_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt answers must begin empty at revision one');
END;

CREATE TRIGGER quiz_attempt_answers_revision_moves_forward
BEFORE UPDATE OF response_json, revision, answered_at ON quiz_attempt_answers
WHEN NEW.revision != OLD.revision + 1
  OR NEW.response_json IS NULL
  OR NEW.answered_at IS NULL
  OR NOT EXISTS (
    SELECT 1
    FROM quiz_attempt_items
    JOIN quiz_attempts ON quiz_attempts.id = quiz_attempt_items.attempt_id
    WHERE quiz_attempt_items.id = OLD.attempt_item_id
      AND NEW.answered_at >= quiz_attempts.started_at
      AND (OLD.answered_at IS NULL OR NEW.answered_at > OLD.answered_at)
  )
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt answer revision must move forward once');
END;

CREATE TRIGGER quiz_attempt_answers_no_delete
BEFORE DELETE ON quiz_attempt_answers
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt answers are retained history');
END;

CREATE TRIGGER quiz_attempt_autosave_receipts_no_update
BEFORE UPDATE ON quiz_attempt_autosave_receipts
BEGIN
    SELECT RAISE(ABORT, 'quiz autosave receipts are immutable');
END;

CREATE TRIGGER quiz_attempt_autosave_receipts_require_matching_item
BEFORE INSERT ON quiz_attempt_autosave_receipts
WHEN length(NEW.idempotency_token) < 1
  OR length(NEW.idempotency_token) > 160
  OR length(NEW.payload_sha256) != 64
  OR NEW.payload_sha256 GLOB '*[^0-9a-f]*'
  OR NOT EXISTS (
    SELECT 1
    FROM quiz_attempt_items
    JOIN quiz_attempt_answers
      ON quiz_attempt_answers.attempt_item_id = quiz_attempt_items.id
    WHERE quiz_attempt_items.id = NEW.attempt_item_id
      AND quiz_attempt_items.attempt_id = NEW.attempt_id
      AND quiz_attempt_answers.response_json = NEW.response_json
      AND quiz_attempt_answers.revision = NEW.answer_revision
      AND quiz_attempt_answers.answered_at = NEW.answered_at
  )
BEGIN
    SELECT RAISE(ABORT, 'quiz autosave receipt must match the applied answer');
END;

CREATE TRIGGER quiz_attempt_autosave_receipts_no_delete
BEFORE DELETE ON quiz_attempt_autosave_receipts
BEGIN
    SELECT RAISE(ABORT, 'quiz autosave receipts are retained history');
END;

CREATE TRIGGER quiz_attempts_archive_on_course_archive
AFTER UPDATE OF state ON courses
WHEN OLD.state = 'active' AND NEW.state = 'archived'
BEGIN
    UPDATE quiz_attempts
    SET state = 'archived', archived_at = NEW.updated_at,
        revision = revision + 1, updated_at = NEW.updated_at
    WHERE course_id = NEW.id AND state = 'in_progress';
END;

CREATE TRIGGER quiz_attempts_archive_on_practice_archive
AFTER UPDATE OF state ON practice_sets
WHEN OLD.state = 'draft' AND NEW.state = 'archived'
BEGIN
    UPDATE quiz_attempts
    SET state = 'archived', archived_at = NEW.updated_at,
        revision = revision + 1, updated_at = NEW.updated_at
    WHERE practice_set_id = NEW.id AND state = 'in_progress';
END;

CREATE TRIGGER quiz_attempts_archive_on_practice_successor
AFTER UPDATE OF current_revision_id ON practice_sets
WHEN OLD.current_revision_id IS NOT NULL
 AND NEW.current_revision_id IS NOT OLD.current_revision_id
BEGIN
    UPDATE quiz_attempts
    SET state = 'archived', archived_at = NEW.updated_at,
        revision = revision + 1, updated_at = NEW.updated_at
    WHERE practice_set_id = NEW.id
      AND practice_set_revision_id != NEW.current_revision_id
      AND state = 'in_progress';
END;
