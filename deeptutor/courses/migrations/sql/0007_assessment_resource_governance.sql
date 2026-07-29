-- Retention is append-only: these admission guards cap future history without
-- deleting evidence, attempts, autosave receipts, or review events.

CREATE TRIGGER quiz_attempts_retained_attempt_limit
BEFORE INSERT ON quiz_attempts
WHEN (
    SELECT COUNT(*) FROM quiz_attempts
    WHERE owner_user_id = NEW.owner_user_id
      AND course_id = NEW.course_id
      AND practice_set_id = NEW.practice_set_id
) >= 100
BEGIN
    SELECT RAISE(ABORT, 'quiz attempt retained history limit reached');
END;

CREATE TRIGGER quiz_attempt_autosave_receipts_retention_limit
BEFORE INSERT ON quiz_attempt_autosave_receipts
WHEN (
    SELECT COUNT(*) FROM quiz_attempt_autosave_receipts
    WHERE attempt_id = NEW.attempt_id
) >= 2048
OR (
    SELECT COALESCE(SUM(length(CAST(response_json AS BLOB))), 0)
    FROM quiz_attempt_autosave_receipts
    WHERE attempt_id = NEW.attempt_id
) + length(CAST(NEW.response_json AS BLOB)) > 2097152
BEGIN
    SELECT RAISE(ABORT, 'quiz autosave receipt retained history limit reached');
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

CREATE TRIGGER flashcard_reviews_retention_limit
BEFORE INSERT ON flashcard_reviews
WHEN (
    SELECT COUNT(*) FROM flashcard_reviews
    WHERE deck_id = NEW.deck_id
) >= 10000
BEGIN
    SELECT RAISE(ABORT, 'flashcard review retained history limit reached');
END;
