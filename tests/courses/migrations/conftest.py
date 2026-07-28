"""Explicit Phase 3A legacy-shape builders for migration tests."""

from __future__ import annotations

import hashlib
from importlib import resources
import json
from pathlib import Path
import sqlite3
from typing import Any


def baseline_sql() -> str:
    return (
        resources.files("deeptutor.courses.migrations")
        .joinpath("sql/0000_phase3a_baseline.sql")
        .read_text(encoding="utf-8")
    )


def build_legacy_database(path: Path, *, include_blueway: bool) -> sqlite3.Connection:
    """Build one ledger-free Phase 3A shape solely from the checked-in SQL."""

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(baseline_sql())
    conn.execute("DROP TABLE schema_migrations")
    if not include_blueway:
        conn.execute("DROP TABLE blueway_records")
        conn.execute("DROP TABLE blueway_sync_runs")
        conn.execute("DROP TABLE blueway_course_maps")
        conn.execute("DROP TABLE blueway_connections")
    conn.commit()
    return conn


def seed_phase3a_rows(conn: sqlite3.Connection, *, include_blueway: bool) -> None:
    """Seed non-personal deterministic rows that exercise all legacy relations."""

    conn.execute(
        """INSERT INTO courses
           (id, owner_user_id, title, state, revision, write_epoch, managed_kb_ref,
            created_at, updated_at, archived_at)
           VALUES ('crs_fixture', 'owner_fixture', 'Fixture Course', 'active', 3, 2,
                   'personal:kb:fixture', 100.0, 101.0, NULL)"""
    )
    conn.execute(
        """INSERT INTO course_sources
           (id, course_id, kind, display_name, state, manifest_json, content_sha256,
            revision, operation_id, idempotency_key, supersedes_source_id, created_at,
            updated_at)
           VALUES ('src_fixture', 'crs_fixture', 'syllabus', 'fixture.pdf', 'ready',
                   '[{"path":"fixture.pdf"}]', 'aaaaaaaa', 4, 'op_fixture',
                   'idempotency_fixture', NULL, 102.0, 103.0)"""
    )
    if include_blueway:
        conn.execute(
            """INSERT INTO blueway_connections
               (id, owner_user_id, external_subject, state, scope_version, revision,
                grant_generation, credential_ref, credential_status, created_at,
                updated_at, connected_at, last_sync_at, disconnected_at,
                rotation_request_id, rotation_started_at)
               VALUES ('bwc_fixture', 'owner_fixture', 'subject_fixture', 'active',
                       'phase3a', 5, 2, 'blueway:bwc_fixture', 'healthy', 104.0,
                       105.0, 104.0, 105.0, NULL, NULL, NULL)"""
        )
        conn.execute(
            """INSERT INTO blueway_course_maps
               (connection_id, external_course_id, course_id, remote_title, remote_state,
                remote_hash, first_seen_snapshot_id, last_seen_snapshot_id, created_at,
                updated_at)
               VALUES ('bwc_fixture', 'remote_course', 'crs_fixture', 'Remote Course',
                       'active', 'remote_hash', 'snapshot_one', 'snapshot_two', 106.0, 107.0)"""
        )
        conn.execute(
            """INSERT INTO blueway_records
               (connection_id, record_kind, external_record_id, external_course_id,
                course_id, state, remote_revision, content_sha256, payload_json,
                current_source_id, first_seen_snapshot_id, last_seen_snapshot_id,
                created_at, updated_at)
               VALUES ('bwc_fixture', 'assignment', 'remote_record', 'remote_course',
                       'crs_fixture', 'current', 'r1', 'bbbbbbbb', '{"score":91}',
                       'src_fixture', 'snapshot_one', 'snapshot_two', 108.0, 109.0)"""
        )
        conn.execute(
            """INSERT INTO blueway_sync_runs
               (id, connection_id, expected_generation, snapshot_id, snapshot_sha256,
                state, attempt_count, counts_json, error_code, created_at, updated_at,
                completed_at)
               VALUES ('run_fixture', 'bwc_fixture', 2, 'snapshot_complete',
                       'cccccccc', 'completed', 2, '{"records":1}', NULL, 110.0,
                       111.0, 112.0)"""
        )
    conn.commit()


def domain_digest(conn: sqlite3.Connection) -> str:
    """Return a canonical data digest excluding the migration ledger."""

    tables = [
        str(row[0])
        for row in conn.execute(
            """SELECT name FROM sqlite_master
               WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                 AND name != 'schema_migrations'
               ORDER BY name"""
        )
    ]
    payload: dict[str, list[dict[str, Any]]] = {}
    for table in tables:
        rows = conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
        # Adoption is allowed to add empty baseline tables.  The preservation
        # digest deliberately covers only existing domain rows and values.
        if rows:
            payload[table] = [dict(row) for row in rows]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
