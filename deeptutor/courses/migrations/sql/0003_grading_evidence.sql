CREATE TABLE IF NOT EXISTS quiz_item_grading_evidence (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    practice_set_id TEXT NOT NULL REFERENCES practice_sets(id) ON DELETE RESTRICT,
    attempt_id TEXT NOT NULL REFERENCES quiz_attempts(id) ON DELETE RESTRICT,
    attempt_item_id TEXT NOT NULL REFERENCES quiz_attempt_items(id) ON DELETE RESTRICT,
    question_id TEXT NOT NULL REFERENCES practice_questions(id) ON DELETE RESTRICT,
    objective_id TEXT NOT NULL,
    module_id TEXT,
    knowledge_type TEXT,
    algorithm TEXT NOT NULL CHECK (algorithm = 'exact-v1'),
    payload_sha256 TEXT NOT NULL,
    is_correct INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
    grading_json TEXT NOT NULL,
    error_type TEXT,
    state TEXT NOT NULL CHECK (state IN ('pending', 'applied', 'unmapped')),
    created_at REAL NOT NULL,
    applied_at REAL,
    UNIQUE (attempt_item_id, objective_id)
);
CREATE INDEX IF NOT EXISTS idx_quiz_grading_evidence_attempt
    ON quiz_item_grading_evidence(attempt_id, state, attempt_item_id);

CREATE TRIGGER quiz_grading_evidence_requires_submitted_attempt
BEFORE INSERT ON quiz_item_grading_evidence
WHEN NEW.algorithm != 'exact-v1'
 OR length(NEW.payload_sha256) != 64
 OR NEW.payload_sha256 GLOB '*[^0-9a-f]*'
 OR (NEW.state = 'pending' AND NEW.applied_at IS NOT NULL)
 OR (NEW.state = 'pending' AND (
        NEW.objective_id = '' OR NEW.module_id IS NULL OR NEW.module_id = ''
        OR NEW.knowledge_type NOT IN ('memory', 'concept', 'procedure', 'design')
    ))
 OR (NEW.state = 'applied')
 OR (NEW.state = 'unmapped' AND (
        NEW.applied_at IS NULL OR NEW.module_id IS NOT NULL OR NEW.knowledge_type IS NOT NULL
    ))
 OR teeechr_exact_evidence_valid(
        NEW.payload_sha256, NEW.grading_json, NEW.algorithm, NEW.attempt_id,
        NEW.attempt_item_id, NEW.question_id, NEW.objective_id, NEW.module_id,
        NEW.knowledge_type, NEW.is_correct, NEW.error_type,
        (SELECT answer_contract_json FROM practice_questions WHERE id = NEW.question_id),
        (SELECT answers.response_json FROM quiz_attempt_answers AS answers
         WHERE answers.attempt_item_id = NEW.attempt_item_id)
    ) != 1
 OR (NEW.objective_id = '' AND json_array_length(
        (SELECT objective_ids_json FROM practice_questions WHERE id = NEW.question_id)
    ) != 0)
 OR (NEW.objective_id != '' AND NOT EXISTS (
        SELECT 1 FROM json_each(
            (SELECT objective_ids_json FROM practice_questions WHERE id = NEW.question_id)
        ) WHERE value = NEW.objective_id
    ))
 OR NOT EXISTS (
    SELECT 1 FROM quiz_attempts
    JOIN quiz_attempt_items ON quiz_attempt_items.attempt_id = quiz_attempts.id
    JOIN practice_questions ON practice_questions.id = quiz_attempt_items.question_id
    JOIN courses ON courses.id = quiz_attempts.course_id
    JOIN practice_sets ON practice_sets.id = quiz_attempts.practice_set_id
    WHERE quiz_attempts.id = NEW.attempt_id
      AND quiz_attempts.state = 'submitted'
      AND quiz_attempts.owner_user_id = NEW.owner_user_id
      AND quiz_attempts.course_id = NEW.course_id
      AND quiz_attempts.practice_set_id = NEW.practice_set_id
      AND quiz_attempt_items.id = NEW.attempt_item_id
      AND practice_questions.id = NEW.question_id
      AND courses.owner_user_id = NEW.owner_user_id
      AND courses.state = 'active'
      AND courses.write_epoch = quiz_attempts.course_write_epoch
      AND practice_sets.state = 'draft'
      AND practice_sets.write_epoch = quiz_attempts.practice_set_write_epoch
)
BEGIN
    SELECT RAISE(ABORT, 'grading evidence requires an owned submitted attempt');
END;

CREATE TRIGGER quiz_grading_evidence_immutable
BEFORE UPDATE OF id, owner_user_id, course_id, practice_set_id, attempt_id,
    attempt_item_id, question_id, objective_id, module_id, knowledge_type, algorithm,
    payload_sha256, is_correct, grading_json, error_type,
    created_at ON quiz_item_grading_evidence
BEGIN
    SELECT RAISE(ABORT, 'grading evidence is immutable');
END;

CREATE TRIGGER quiz_grading_evidence_state_transition
BEFORE UPDATE OF state, applied_at ON quiz_item_grading_evidence
WHEN NOT (
    (OLD.state = 'pending' AND NEW.state = 'applied' AND NEW.applied_at >= OLD.created_at)
    OR (OLD.state = NEW.state AND OLD.applied_at IS NEW.applied_at)
)
BEGIN
    SELECT RAISE(ABORT, 'grading evidence state is immutable after apply');
END;

CREATE TRIGGER quiz_grading_evidence_no_delete
BEFORE DELETE ON quiz_item_grading_evidence
BEGIN
    SELECT RAISE(ABORT, 'grading evidence is retained history');
END;

DROP TRIGGER quiz_attempts_grading_reserved;
DROP TRIGGER quiz_attempt_items_grading_reserved;
DROP TRIGGER quiz_attempts_archive_on_course_archive;
DROP TRIGGER quiz_attempts_archive_on_practice_archive;
DROP TRIGGER quiz_attempts_archive_on_practice_successor;

CREATE TRIGGER quiz_grading_evidence_item_results_agree
BEFORE INSERT ON quiz_item_grading_evidence
WHEN EXISTS (
    SELECT 1 FROM quiz_item_grading_evidence
    WHERE attempt_item_id = NEW.attempt_item_id
      AND (is_correct != NEW.is_correct OR error_type IS NOT NEW.error_type)
)
BEGIN
    SELECT RAISE(ABORT, 'one item must have one immutable grading result');
END;

CREATE TRIGGER quiz_attempt_items_grading_requires_evidence
BEFORE UPDATE OF grading_json, error_type, graded_at ON quiz_attempt_items
WHEN (
    NEW.grading_json IS NOT OLD.grading_json
    OR NEW.error_type IS NOT OLD.error_type
    OR NEW.graded_at IS NOT OLD.graded_at
)
AND (
    OLD.graded_at IS NOT NULL
    OR NEW.graded_at IS NULL
    OR NOT EXISTS (
        SELECT 1 FROM quiz_item_grading_evidence
        WHERE attempt_item_id = NEW.id
    )
    OR teeechr_item_grading_valid(
        NEW.grading_json,
        (SELECT is_correct FROM quiz_item_grading_evidence
         WHERE attempt_item_id = NEW.id ORDER BY id LIMIT 1),
        (SELECT error_type FROM quiz_item_grading_evidence
         WHERE attempt_item_id = NEW.id ORDER BY id LIMIT 1)
    ) != 1
    OR (SELECT COUNT(*) FROM quiz_item_grading_evidence
        WHERE attempt_item_id = NEW.id) != json_array_length(json_extract(NEW.grading_json, '$.evidence_ids'))
    OR EXISTS (
        SELECT 1 FROM json_each(json_extract(NEW.grading_json, '$.evidence_ids')) AS ids
        WHERE NOT EXISTS (
            SELECT 1 FROM quiz_item_grading_evidence
            WHERE attempt_item_id = NEW.id AND id = ids.value
        )
    )
)
BEGIN
    SELECT RAISE(ABORT, 'item grading requires applied evidence exactly once');
END;

CREATE TRIGGER quiz_attempts_grading_requires_complete_evidence
BEFORE UPDATE OF state, score_json, graded_at ON quiz_attempts
WHEN NEW.state = 'graded'
AND (
    OLD.state != 'submitted'
    OR NEW.score_json IS NULL
    OR NEW.graded_at IS NULL
    OR EXISTS (
        SELECT 1 FROM quiz_attempt_items
        WHERE attempt_id = NEW.id AND graded_at IS NULL
    )
    OR EXISTS (
        SELECT 1 FROM quiz_attempt_items
        WHERE attempt_id = NEW.id
          AND NOT EXISTS (
              SELECT 1 FROM quiz_item_grading_evidence
              WHERE attempt_item_id = quiz_attempt_items.id
          )
    )
    OR EXISTS (
        SELECT 1 FROM quiz_item_grading_evidence
        WHERE attempt_id = NEW.id AND state NOT IN ('pending', 'applied', 'unmapped')
    )
    OR json_type(NEW.score_json, '$.correct') != 'integer'
    OR json_type(NEW.score_json, '$.total') != 'integer'
    OR json_type(NEW.score_json, '$.fraction') NOT IN ('integer', 'real')
    OR (SELECT COUNT(*) FROM json_each(NEW.score_json)) != 3
    OR EXISTS (
        SELECT 1 FROM json_each(NEW.score_json)
        WHERE key NOT IN ('correct', 'total', 'fraction')
    )
    OR json_extract(NEW.score_json, '$.correct') != (
        SELECT COUNT(*) FROM quiz_attempt_items
        WHERE attempt_id = NEW.id AND json_extract(grading_json, '$.is_correct') = 1
    )
    OR json_extract(NEW.score_json, '$.total') != (
        SELECT COUNT(*) FROM quiz_attempt_items WHERE attempt_id = NEW.id
    )
    OR json_extract(NEW.score_json, '$.fraction') != (
        SELECT CAST(COUNT(*) AS REAL) / (SELECT COUNT(*) FROM quiz_attempt_items WHERE attempt_id = NEW.id)
        FROM quiz_attempt_items
        WHERE attempt_id = NEW.id AND json_extract(grading_json, '$.is_correct') = 1
    )
)
BEGIN
    SELECT RAISE(ABORT, 'attempt grading requires every applied item evidence');
END;

CREATE TRIGGER quiz_attempts_grading_requires_final_state
BEFORE UPDATE OF score_json, graded_at ON quiz_attempts
WHEN (NEW.score_json IS NOT OLD.score_json OR NEW.graded_at IS NOT OLD.graded_at)
 AND NEW.state != 'graded'
BEGIN
    SELECT RAISE(ABORT, 'attempt grading fields require a graded attempt');
END;

CREATE TRIGGER quiz_attempts_grading_immutable
BEFORE UPDATE OF score_json, graded_at ON quiz_attempts
WHEN OLD.graded_at IS NOT NULL
 AND (NEW.score_json IS NOT OLD.score_json OR NEW.graded_at IS NOT OLD.graded_at)
BEGIN
    SELECT RAISE(ABORT, 'graded attempt results are immutable');
END;

CREATE TRIGGER quiz_attempts_archive_on_course_archive
AFTER UPDATE OF state ON courses
WHEN OLD.state = 'active' AND NEW.state = 'archived'
 AND EXISTS (SELECT 1 FROM quiz_attempts WHERE course_id = NEW.id AND state IN ('in_progress', 'submitted'))
BEGIN
    UPDATE quiz_attempts
    SET state = 'archived', archived_at = NEW.updated_at,
        revision = revision + 1, updated_at = NEW.updated_at
    WHERE course_id = NEW.id AND state IN ('in_progress', 'submitted');
END;

CREATE TRIGGER quiz_attempts_archive_on_practice_archive
AFTER UPDATE OF state ON practice_sets
WHEN OLD.state = 'draft' AND NEW.state = 'archived'
 AND EXISTS (SELECT 1 FROM quiz_attempts WHERE practice_set_id = NEW.id AND state IN ('in_progress', 'submitted'))
BEGIN
    UPDATE quiz_attempts
    SET state = 'archived', archived_at = NEW.updated_at,
        revision = revision + 1, updated_at = NEW.updated_at
    WHERE practice_set_id = NEW.id AND state IN ('in_progress', 'submitted');
END;

CREATE TRIGGER quiz_attempts_archive_on_practice_successor
AFTER UPDATE OF current_revision_id ON practice_sets
WHEN OLD.current_revision_id IS NOT NULL
 AND NEW.current_revision_id IS NOT OLD.current_revision_id
 AND EXISTS (
    SELECT 1 FROM quiz_attempts
    WHERE practice_set_id = NEW.id AND practice_set_revision_id != NEW.current_revision_id
      AND state IN ('in_progress', 'submitted')
 )
BEGIN
    UPDATE quiz_attempts
    SET state = 'archived', archived_at = NEW.updated_at,
        revision = revision + 1, updated_at = NEW.updated_at
    WHERE practice_set_id = NEW.id
      AND practice_set_revision_id != NEW.current_revision_id
      AND state IN ('in_progress', 'submitted');
END;
