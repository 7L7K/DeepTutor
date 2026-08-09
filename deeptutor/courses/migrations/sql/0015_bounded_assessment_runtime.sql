-- C3-H2 learner-safe bounded short-answer and single-choice persistence.
-- Historical migrations and retained exact-answer evidence remain unchanged.

ALTER TABLE practice_questions
    ADD COLUMN options_json TEXT NOT NULL DEFAULT '[]'
    CHECK (
        json_valid(options_json) = 1
        AND json_type(options_json) = 'array'
        AND json_array_length(options_json) BETWEEN 0 AND 8
    );

CREATE TRIGGER practice_questions_contract_shape_insert
BEFORE INSERT ON practice_questions
WHEN CASE
    WHEN json_valid(NEW.answer_contract_json) != 1 THEN 1
    WHEN json_extract(NEW.answer_contract_json, '$.kind') = 'exact' THEN
        NEW.question_type != 'short_answer'
        OR json_type(NEW.answer_contract_json, '$.answer') != 'text'
        OR json_array_length(NEW.options_json) != 0
    WHEN json_extract(NEW.answer_contract_json, '$.kind') = 'bounded_short_answer_v1' THEN
        NEW.question_type != 'short_answer'
        OR json_type(NEW.answer_contract_json, '$.canonical_answer') != 'text'
        OR json_type(NEW.answer_contract_json, '$.accepted_normalized_answers') != 'array'
        OR json_array_length(json_extract(NEW.answer_contract_json, '$.accepted_normalized_answers')) < 1
        OR json_extract(NEW.answer_contract_json, '$.normalization_version') != 'bounded-text-normalization-v1'
        OR json_array_length(NEW.options_json) != 0
    WHEN json_extract(NEW.answer_contract_json, '$.kind') = 'single_choice_v1' THEN
        NEW.question_type != 'single_choice'
        OR json_type(NEW.answer_contract_json, '$.correct_option_id') != 'text'
        OR json_array_length(NEW.options_json) NOT BETWEEN 2 AND 8
        OR EXISTS (
            SELECT 1 FROM json_each(NEW.options_json)
            WHERE json_type(value, '$.option_id') != 'text'
               OR json_type(value, '$.text') != 'text'
               OR length(json_extract(value, '$.option_id')) != 36
               OR substr(json_extract(value, '$.option_id'), 1, 4) != 'opt_'
               OR substr(json_extract(value, '$.option_id'), 5) GLOB '*[^0-9a-f]*'
               OR trim(json_extract(value, '$.text')) = ''
        )
        OR length(json_extract(NEW.answer_contract_json, '$.correct_option_id')) != 36
        OR substr(json_extract(NEW.answer_contract_json, '$.correct_option_id'), 1, 4) != 'opt_'
        OR substr(json_extract(NEW.answer_contract_json, '$.correct_option_id'), 5)
           GLOB '*[^0-9a-f]*'
        OR (SELECT COUNT(DISTINCT json_extract(value, '$.option_id'))
            FROM json_each(NEW.options_json)) != json_array_length(NEW.options_json)
        OR (SELECT COUNT(*) FROM json_each(NEW.options_json)
            WHERE json_extract(value, '$.option_id') =
                  json_extract(NEW.answer_contract_json, '$.correct_option_id')) != 1
    ELSE 1
END
OR CASE
    WHEN json_extract(NEW.answer_contract_json, '$.kind') IN (
        'bounded_short_answer_v1', 'single_choice_v1'
    ) THEN teeechr_question_contract_valid(
        NEW.question_type, NEW.answer_contract_json, NEW.options_json
    ) != 1
    ELSE 0
END
BEGIN
    SELECT RAISE(ABORT, 'practice question answer contract is invalid');
END;

CREATE TRIGGER practice_questions_contract_shape_update
BEFORE UPDATE OF question_type, answer_contract_json, options_json ON practice_questions
WHEN CASE
    WHEN json_valid(NEW.answer_contract_json) != 1 THEN 1
    WHEN json_extract(NEW.answer_contract_json, '$.kind') = 'exact' THEN
        (NEW.question_type != 'short_answer' AND NEW.question_type IS NOT OLD.question_type)
        OR json_type(NEW.answer_contract_json, '$.answer') != 'text'
        OR json_array_length(NEW.options_json) != 0
    WHEN json_extract(NEW.answer_contract_json, '$.kind') = 'bounded_short_answer_v1' THEN
        NEW.question_type != 'short_answer'
        OR json_type(NEW.answer_contract_json, '$.canonical_answer') != 'text'
        OR json_type(NEW.answer_contract_json, '$.accepted_normalized_answers') != 'array'
        OR json_array_length(json_extract(NEW.answer_contract_json, '$.accepted_normalized_answers')) < 1
        OR json_extract(NEW.answer_contract_json, '$.normalization_version') != 'bounded-text-normalization-v1'
        OR json_array_length(NEW.options_json) != 0
    WHEN json_extract(NEW.answer_contract_json, '$.kind') = 'single_choice_v1' THEN
        NEW.question_type != 'single_choice'
        OR json_type(NEW.answer_contract_json, '$.correct_option_id') != 'text'
        OR json_array_length(NEW.options_json) NOT BETWEEN 2 AND 8
        OR EXISTS (
            SELECT 1 FROM json_each(NEW.options_json)
            WHERE json_type(value, '$.option_id') != 'text'
               OR json_type(value, '$.text') != 'text'
               OR length(json_extract(value, '$.option_id')) != 36
               OR substr(json_extract(value, '$.option_id'), 1, 4) != 'opt_'
               OR substr(json_extract(value, '$.option_id'), 5) GLOB '*[^0-9a-f]*'
               OR trim(json_extract(value, '$.text')) = ''
        )
        OR length(json_extract(NEW.answer_contract_json, '$.correct_option_id')) != 36
        OR substr(json_extract(NEW.answer_contract_json, '$.correct_option_id'), 1, 4) != 'opt_'
        OR substr(json_extract(NEW.answer_contract_json, '$.correct_option_id'), 5)
           GLOB '*[^0-9a-f]*'
        OR (SELECT COUNT(DISTINCT json_extract(value, '$.option_id'))
            FROM json_each(NEW.options_json)) != json_array_length(NEW.options_json)
        OR (SELECT COUNT(*) FROM json_each(NEW.options_json)
            WHERE json_extract(value, '$.option_id') =
                  json_extract(NEW.answer_contract_json, '$.correct_option_id')) != 1
    ELSE 1
END
OR CASE
    WHEN json_extract(NEW.answer_contract_json, '$.kind') IN (
        'bounded_short_answer_v1', 'single_choice_v1'
    ) THEN teeechr_question_contract_valid(
        NEW.question_type, NEW.answer_contract_json, NEW.options_json
    ) != 1
    ELSE 0
END
BEGIN
    SELECT RAISE(ABORT, 'practice question answer contract is invalid');
END;

CREATE TRIGGER quiz_attempts_submit_requires_complete_answers
BEFORE UPDATE OF state ON quiz_attempts
WHEN NEW.state = 'submitted'
 AND OLD.state = 'in_progress'
 AND EXISTS (
    SELECT 1 FROM quiz_attempt_items AS items
    WHERE items.attempt_id = NEW.id
      AND NOT EXISTS (
          SELECT 1 FROM quiz_attempt_answers AS answers
          WHERE answers.attempt_item_id = items.id
            AND answers.response_json IS NOT NULL
      )
 )
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt requires every answer before submission');
END;

-- SQLite cannot widen the existing algorithm CHECK in place. Rebuild both the
-- retained evidence table and its only foreign-key child inside this migration.
DROP TRIGGER quiz_grading_evidence_requires_submitted_attempt;
DROP TRIGGER quiz_grading_evidence_immutable;
DROP TRIGGER quiz_grading_evidence_state_transition;
DROP TRIGGER quiz_grading_evidence_no_delete;
DROP TRIGGER quiz_grading_evidence_item_results_agree;
DROP TRIGGER quiz_attempt_items_grading_requires_evidence;
DROP TRIGGER quiz_attempts_grading_requires_complete_evidence;
DROP TRIGGER quiz_grading_evidence_retention_limit;
DROP TRIGGER practice_question_invalidation_owned_insert;
DROP TRIGGER practice_question_invalidation_no_update;
DROP TRIGGER practice_question_invalidation_no_delete;

ALTER TABLE practice_question_invalidations
    RENAME TO practice_question_invalidations_pre_0015;
ALTER TABLE quiz_item_grading_evidence
    RENAME TO quiz_item_grading_evidence_pre_0015;

CREATE TABLE quiz_item_grading_evidence (
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
    algorithm TEXT NOT NULL CHECK (
        algorithm IN ('exact-v1', 'bounded_short_answer_v1', 'single_choice_v1')
    ),
    payload_sha256 TEXT NOT NULL,
    is_correct INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
    grading_json TEXT NOT NULL,
    error_type TEXT,
    state TEXT NOT NULL CHECK (state IN ('pending', 'applied', 'unmapped')),
    created_at REAL NOT NULL,
    applied_at REAL,
    UNIQUE (attempt_item_id, objective_id)
);

INSERT INTO quiz_item_grading_evidence
    (id, owner_user_id, course_id, practice_set_id, attempt_id,
     attempt_item_id, question_id, objective_id, module_id, knowledge_type,
     algorithm, payload_sha256, is_correct, grading_json, error_type,
     state, created_at, applied_at)
SELECT id, owner_user_id, course_id, practice_set_id, attempt_id,
       attempt_item_id, question_id, objective_id, module_id, knowledge_type,
       algorithm, payload_sha256, is_correct, grading_json, error_type,
       state, created_at, applied_at
FROM quiz_item_grading_evidence_pre_0015;

CREATE TABLE practice_question_invalidations (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    practice_set_id TEXT NOT NULL REFERENCES practice_sets(id) ON DELETE RESTRICT,
    practice_set_revision_id TEXT NOT NULL REFERENCES practice_set_revisions(id) ON DELETE RESTRICT,
    question_id TEXT NOT NULL REFERENCES practice_questions(id) ON DELETE RESTRICT,
    report_id TEXT NOT NULL REFERENCES practice_question_quality_reports(id) ON DELETE RESTRICT,
    evidence_id TEXT REFERENCES quiz_item_grading_evidence(id) ON DELETE RESTRICT,
    reason TEXT NOT NULL,
    invalidated_by TEXT NOT NULL,
    invalidated_at REAL NOT NULL,
    UNIQUE (question_id, evidence_id)
);

INSERT INTO practice_question_invalidations
    (id, owner_user_id, course_id, practice_set_id, practice_set_revision_id,
     question_id, report_id, evidence_id, reason, invalidated_by, invalidated_at)
SELECT id, owner_user_id, course_id, practice_set_id, practice_set_revision_id,
       question_id, report_id, evidence_id, reason, invalidated_by, invalidated_at
FROM practice_question_invalidations_pre_0015;

DROP TABLE practice_question_invalidations_pre_0015;
DROP TABLE quiz_item_grading_evidence_pre_0015;

CREATE INDEX idx_quiz_grading_evidence_attempt
    ON quiz_item_grading_evidence(attempt_id, state, attempt_item_id);
CREATE INDEX practice_question_invalidations_attempt_lookup
    ON practice_question_invalidations(course_id, practice_set_id, question_id, evidence_id);

CREATE TRIGGER quiz_grading_evidence_requires_submitted_attempt
BEFORE INSERT ON quiz_item_grading_evidence
WHEN NEW.algorithm NOT IN ('exact-v1', 'bounded_short_answer_v1', 'single_choice_v1')
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
 OR teeechr_assessment_evidence_valid(
        NEW.payload_sha256, NEW.grading_json, NEW.algorithm,
        NEW.attempt_id, NEW.attempt_item_id, NEW.question_id, NEW.objective_id,
        NEW.module_id, NEW.knowledge_type, NEW.is_correct, NEW.error_type,
        (SELECT answer_contract_json FROM practice_questions WHERE id = NEW.question_id),
        (SELECT options_json FROM practice_questions WHERE id = NEW.question_id),
        (SELECT items.option_order_json FROM quiz_attempt_items AS items
         WHERE items.id = NEW.attempt_item_id),
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

CREATE TRIGGER quiz_grading_evidence_item_results_agree
BEFORE INSERT ON quiz_item_grading_evidence
WHEN EXISTS (
    SELECT 1 FROM quiz_item_grading_evidence
    WHERE attempt_item_id = NEW.attempt_item_id
      AND (
        is_correct != NEW.is_correct
        OR error_type IS NOT NEW.error_type
        OR algorithm != NEW.algorithm
      )
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
    OR json_extract(NEW.grading_json, '$.algorithm') != (
        SELECT algorithm FROM quiz_item_grading_evidence
        WHERE attempt_item_id = NEW.id ORDER BY id LIMIT 1
    )
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

CREATE TRIGGER quiz_grading_evidence_retention_limit
BEFORE INSERT ON quiz_item_grading_evidence
WHEN (
    SELECT COUNT(*) FROM quiz_item_grading_evidence
    WHERE attempt_id = NEW.attempt_id
) >= 4096
OR (
    SELECT COALESCE(SUM(length(CAST(grading_json AS BLOB))), 0)
    FROM quiz_item_grading_evidence
    WHERE attempt_id = NEW.attempt_id
) + length(CAST(NEW.grading_json AS BLOB)) > 2097152
BEGIN
    SELECT RAISE(ABORT, 'quiz grading evidence retained history limit reached');
END;

CREATE TRIGGER practice_question_invalidation_owned_insert
BEFORE INSERT ON practice_question_invalidations
WHEN NEW.invalidated_by = ''
 OR NOT EXISTS (
    SELECT 1 FROM practice_question_quality_reports AS reports
    WHERE reports.id = NEW.report_id AND reports.owner_user_id = NEW.owner_user_id
      AND reports.course_id = NEW.course_id AND reports.practice_set_id = NEW.practice_set_id
      AND reports.practice_set_revision_id = NEW.practice_set_revision_id
      AND reports.question_id = NEW.question_id AND reports.state = 'invalidated'
)
 OR NOT EXISTS (
    SELECT 1 FROM courses
    JOIN practice_sets ON practice_sets.course_id = courses.id
    JOIN practice_set_revisions ON practice_set_revisions.practice_set_id = practice_sets.id
    JOIN practice_questions ON practice_questions.practice_set_revision_id = practice_set_revisions.id
    WHERE courses.id = NEW.course_id AND courses.owner_user_id = NEW.owner_user_id
      AND practice_sets.id = NEW.practice_set_id AND practice_sets.owner_user_id = NEW.owner_user_id
      AND practice_set_revisions.id = NEW.practice_set_revision_id
      AND practice_questions.id = NEW.question_id
)
 OR (NEW.evidence_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM quiz_item_grading_evidence AS evidence
    JOIN quiz_attempts AS attempts ON attempts.id = evidence.attempt_id
    WHERE evidence.id = NEW.evidence_id
      AND evidence.owner_user_id = NEW.owner_user_id
      AND evidence.course_id = NEW.course_id
      AND evidence.practice_set_id = NEW.practice_set_id
      AND evidence.question_id = NEW.question_id
      AND attempts.practice_set_revision_id = NEW.practice_set_revision_id
))
BEGIN
    SELECT RAISE(ABORT, 'quality invalidation must bind to an approved report and evidence');
END;

CREATE TRIGGER practice_question_invalidation_no_update
BEFORE UPDATE ON practice_question_invalidations
BEGIN
    SELECT RAISE(ABORT, 'quality invalidations are immutable');
END;

CREATE TRIGGER practice_question_invalidation_no_delete
BEFORE DELETE ON practice_question_invalidations
BEGIN
    SELECT RAISE(ABORT, 'quality invalidations are retained history');
END;
