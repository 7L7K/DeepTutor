-- Bind reverse workspace authorization metadata to the exact external Course
-- and term. Existing rows are intentionally left unscoped and therefore do
-- not authorize a new workspace read or direct Course launch.
ALTER TABLE blueway_workspace_authorizations ADD COLUMN external_course_id TEXT;
ALTER TABLE blueway_workspace_authorizations ADD COLUMN external_term_id TEXT;
ALTER TABLE blueway_workspace_authorizations ADD COLUMN last_verified_at REAL;
ALTER TABLE blueway_workspace_authorizations ADD COLUMN lease_expires_at REAL;

CREATE UNIQUE INDEX blueway_workspace_authorizations_exact_scope
    ON blueway_workspace_authorizations(
        connection_id,
        external_course_id,
        COALESCE(external_term_id, '')
    )
    WHERE external_course_id IS NOT NULL;
