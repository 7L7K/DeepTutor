-- C3 content-quality profile and append-only learner report/invalidation ledger.
-- Existing C2 practice and grading rows remain immutable. The ledger is the
-- correction authority for a question that is later found unsafe to count.
ALTER TABLE practice_generation_operations
    ADD COLUMN quality_profile TEXT NOT NULL DEFAULT 'baseline-v1'
    CHECK (quality_profile IN ('baseline-v1', 'c3-biology-v1'));

ALTER TABLE practice_generation_plans
    ADD COLUMN quality_profile TEXT NOT NULL DEFAULT 'baseline-v1'
    CHECK (quality_profile IN ('baseline-v1', 'c3-biology-v1'));

CREATE TABLE practice_question_quality_reports (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    practice_set_id TEXT NOT NULL REFERENCES practice_sets(id) ON DELETE RESTRICT,
    practice_set_revision_id TEXT NOT NULL REFERENCES practice_set_revisions(id) ON DELETE RESTRICT,
    question_id TEXT NOT NULL REFERENCES practice_questions(id) ON DELETE RESTRICT,
    reporter_user_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('reported', 'reviewed', 'rejected', 'invalidated')),
    reviewer_user_id TEXT,
    review_note TEXT,
    created_at REAL NOT NULL,
    reviewed_at REAL,
    UNIQUE (id, owner_user_id, course_id),
    UNIQUE (question_id, reporter_user_id, created_at)
);
CREATE INDEX practice_question_quality_reports_course
    ON practice_question_quality_reports(course_id, practice_set_id, state, created_at);

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
CREATE INDEX practice_question_invalidations_attempt_lookup
    ON practice_question_invalidations(course_id, practice_set_id, question_id, evidence_id);

CREATE TRIGGER practice_question_quality_report_owned_insert
BEFORE INSERT ON practice_question_quality_reports
WHEN NEW.state != 'reported'
 OR NEW.reporter_user_id != NEW.owner_user_id
 OR NEW.reason = ''
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
BEGIN
    SELECT RAISE(ABORT, 'quality report must bind to an owned Course question');
END;

CREATE TRIGGER practice_question_quality_report_transition
BEFORE UPDATE OF owner_user_id, course_id, practice_set_id, practice_set_revision_id,
    question_id, reporter_user_id, reason, state, reviewer_user_id, review_note,
    created_at ON practice_question_quality_reports
WHEN NEW.owner_user_id IS NOT OLD.owner_user_id
 OR NEW.course_id IS NOT OLD.course_id
 OR NEW.practice_set_id IS NOT OLD.practice_set_id
 OR NEW.practice_set_revision_id IS NOT OLD.practice_set_revision_id
 OR NEW.question_id IS NOT OLD.question_id
 OR NEW.reporter_user_id IS NOT OLD.reporter_user_id
 OR NEW.reason IS NOT OLD.reason
 OR NEW.created_at IS NOT OLD.created_at
 OR NOT (
    (OLD.state = 'reported' AND NEW.state IN ('reviewed', 'rejected'))
    OR (OLD.state = 'reviewed' AND NEW.state = 'invalidated')
    OR (OLD.state = NEW.state AND OLD.reviewer_user_id IS NEW.reviewer_user_id
        AND OLD.review_note IS NEW.review_note AND OLD.reviewed_at IS NEW.reviewed_at)
 )
BEGIN
    SELECT RAISE(ABORT, 'quality report transition is invalid');
END;

CREATE TRIGGER practice_question_quality_report_no_delete
BEFORE DELETE ON practice_question_quality_reports
BEGIN
    SELECT RAISE(ABORT, 'quality reports are retained history');
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
BEGIN
    SELECT RAISE(ABORT, 'quality invalidation must bind to an approved report');
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
