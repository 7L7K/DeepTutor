-- Consume each verified BlueWay workspace assertion once. The table is a
-- short-lived replay fence; expired rows are removed during the write path.
CREATE TABLE blueway_workspace_assertion_replays (
    jti TEXT PRIMARY KEY,
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX blueway_workspace_assertion_replays_expiry
    ON blueway_workspace_assertion_replays(expires_at);
