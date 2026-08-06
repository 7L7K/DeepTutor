-- Metadata-only authorization for the read-only BlueWay workspace projection.
-- No provider access or refresh token is persisted here.
CREATE TABLE blueway_workspace_authorizations (
    authorization_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    connection_id TEXT NOT NULL REFERENCES blueway_connections(id) ON DELETE RESTRICT,
    client_id TEXT NOT NULL,
    external_subject_hash TEXT NOT NULL,
    scope TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'inactive', 'revoked')),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    revoked_at REAL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    UNIQUE (connection_id, authorization_id)
);
CREATE INDEX blueway_workspace_authorizations_owner
    ON blueway_workspace_authorizations(owner_user_id, status);
CREATE INDEX blueway_workspace_authorizations_connection
    ON blueway_workspace_authorizations(connection_id, status);
