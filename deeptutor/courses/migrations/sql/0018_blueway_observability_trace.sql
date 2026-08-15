-- Diagnostic-only correlation for one BlueWay pairing lifecycle.
-- Persisted integration state remains authoritative; this reference is never
-- used to authorize, select, or mutate a connection or Course.

ALTER TABLE blueway_connections
    ADD COLUMN observability_trace_id TEXT;
