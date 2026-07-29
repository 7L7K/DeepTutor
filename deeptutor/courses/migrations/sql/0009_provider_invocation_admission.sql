ALTER TABLE flashcard_generation_operations
    ADD COLUMN provider_invoked_at REAL;

CREATE TRIGGER flashcard_generation_provider_invocation_insert_fence
BEFORE INSERT ON flashcard_generation_operations
WHEN NEW.provider_invoked_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'flashcard provider invocation cannot be pre-admitted');
END;

CREATE TRIGGER flashcard_generation_provider_invocation_monotonic
BEFORE UPDATE OF provider_invoked_at
ON flashcard_generation_operations
WHEN OLD.state != 'running'
 OR NEW.state != 'running'
 OR OLD.provider_invoked_at IS NOT NULL
 OR NEW.provider_invoked_at IS NULL
 OR NEW.provider_invoked_at < NEW.started_at
 OR NEW.provider_invoked_at > NEW.updated_at
BEGIN
    SELECT RAISE(ABORT, 'invalid flashcard provider invocation admission');
END;

DROP TRIGGER flashcard_generation_operation_transition;

CREATE TRIGGER flashcard_generation_operation_transition
BEFORE UPDATE OF state,error_code,started_at,completed_at,cancel_requested_at
ON flashcard_generation_operations
WHEN NOT (
    (OLD.state='queued' AND NEW.state IN ('running','failed','cancelled'))
 OR (
    OLD.state='running'
    AND (
        NEW.state IN ('awaiting_review','failed','cancelling')
        OR (NEW.state='cancelled' AND OLD.provider_invoked_at IS NULL)
    )
 )
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
