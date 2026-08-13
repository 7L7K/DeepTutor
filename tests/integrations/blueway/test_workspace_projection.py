"""Local owner/term isolation tests for teeechr.workspace.v1."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import logging
from pathlib import Path

import pytest

from deeptutor.courses.repository import CourseRepository
from deeptutor.integrations.blueway.repository import BlueWayRepository
from deeptutor.integrations.blueway.workspace import (
    WORKSPACE_FRESHNESS_SECONDS,
    ConsentRequiredError,
    project_workspace,
)


def _claims(term: str) -> dict[str, object]:
    subject = "blueway-subject"
    return {
        "sub": subject, "subject_hash": hashlib.sha256(subject.encode()).hexdigest(),
        "client_id": "blueway-client", "authorization_id": "auth-1",
        "scope": "teeechr.workspace.read.v1", "external_course_id": "course-1",
        "external_term_id": term,
    }


def test_projection_is_allowlisted_and_term_qualified(tmp_path: Path, monkeypatch, caplog) -> None:
    db = tmp_path / "courses.db"
    courses = CourseRepository(db, "owner-one")
    blueway = BlueWayRepository(courses)
    connection = blueway.create_active_connection(external_subject="blueway-subject", scope_version="v1")
    blueway.create_workspace_authorization(
        authorization_id="auth-1",
        client_id="blueway-client",
        external_subject_hash=hashlib.sha256(b"blueway-subject").hexdigest(),
        scope="teeechr.workspace.read.v1",
        connection_id=connection.id,
        external_course_id="course-1",
        external_term_id="fall",
    )
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute("UPDATE blueway_connections SET last_sync_at = ? WHERE id = ?", (1704067200.0, connection.id))
    fall = blueway.create_course_map(
        connection_id=connection.id, external_course_id="course-1", external_term_id="fall",
        remote_title="History", remote_state="active", remote_hash="a" * 64,
        snapshot_id="snapshot-fall", expected_generation=connection.grant_generation,
    )
    spring = blueway.create_course_map(
        connection_id=connection.id, external_course_id="course-1", external_term_id="spring",
        remote_title="History II", remote_state="active", remote_hash="b" * 64,
        snapshot_id="snapshot-spring", expected_generation=connection.grant_generation,
    )
    ready_source = courses.create_source(
        fall.id, kind="blueway snapshot", display_name="Verified course bundle",
        manifest=[], content_sha256="c" * 64,
    )
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute("UPDATE course_sources SET state = 'ready' WHERE id = ?", (ready_source.id,))
        conn.execute("""INSERT INTO blueway_records
            (connection_id, record_kind, external_record_id, external_course_id, external_term_id,
             course_id, state, remote_revision, content_sha256, payload_json, current_source_id,
             first_seen_snapshot_id, last_seen_snapshot_id, created_at, updated_at)
            VALUES (?, 'class_meetings', 'meeting-1', 'course-1', 'fall', ?, 'current', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (connection.id, fall.id, "1" * 64, "2" * 64, json.dumps({"id": "meeting-1"}), ready_source.id,
             "snapshot-fall", "snapshot-fall", 1.0, 1.0))
    monkeypatch.setattr("deeptutor.integrations.blueway.workspace._candidate_databases", lambda: [db])

    caplog.set_level(logging.INFO, logger="deeptutor.integrations.blueway.workspace")
    result = project_workspace(_claims("fall"), now=1704067200.0 + 3600.0)
    assert result == {
        "schema_version": "teeechr.workspace.v1", "status": "ready",
        "course": {"external_course_id": "course-1", "external_term_id": "fall", "title": "History"},
        "sync": {"last_synced_at": "2024-01-01T00:00:00Z", "is_stale": False},
        "summary": {"connected_sources_count": 1, "meetings_count": 1}, "resume": None, "recommended_next_action": None,
    }
    with pytest.raises(ConsentRequiredError):
        project_workspace(_claims("spring"))
    encoded = str(result)
    assert fall.id not in encoded and spring.id not in encoded and "owner-one" not in encoded
    assert all(key not in result for key in {"owner_user_id", "id", "sources", "records", "transcript", "notes"})
    resolved = next(record for record in caplog.records if record.message == "blueway_workspace_authorization_resolved")
    assert resolved.candidate_database_count == 1
    assert resolved.candidate_databases_scanned == 1

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: project_workspace(_claims("fall"), now=1704067200.0 + 3600.0), range(16)))
    assert all(item["course"]["external_term_id"] == "fall" for item in results)
    stale = project_workspace(
        _claims("fall"),
        now=1704067200.0 + WORKSPACE_FRESHNESS_SECONDS + 1.0,
    )
    assert stale["status"] == "stale"
    assert stale["sync"] == {"last_synced_at": "2024-01-01T00:00:00Z", "is_stale": True}
    assert stale["summary"] == {"connected_sources_count": 1, "meetings_count": 1}
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE blueway_course_maps SET remote_state = 'archived' WHERE course_id = ?",
            (fall.id,),
        )
    assert project_workspace(_claims("fall"), now=1704067200.0 + 3600.0)["status"] == "not_ready"
    with courses._connect() as conn:  # noqa: SLF001
        assert conn.execute("SELECT COUNT(*) FROM courses WHERE owner_user_id = ?", ("owner-one",)).fetchone()[0] == 2

    blueway.revoke_workspace_authorization("auth-1")
    with pytest.raises(ConsentRequiredError):
        project_workspace(_claims("fall"))


def test_first_valid_assertion_provisions_exact_authorization_and_repeated_reads_are_idempotent(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "courses.db"
    courses = CourseRepository(db, "owner-one")
    blueway = BlueWayRepository(courses)
    connection = blueway.create_active_connection(external_subject="blueway-subject", scope_version="v1")
    with courses._write_lock, courses._connect() as conn:
        conn.execute("UPDATE blueway_connections SET last_sync_at = ? WHERE id = ?", (1704067200.0, connection.id))
    course = blueway.create_course_map(
        connection_id=connection.id, external_course_id="course-1", external_term_id="fall",
        remote_title="History", remote_state="active", remote_hash="a" * 64,
        snapshot_id="snapshot-fall", expected_generation=connection.grant_generation,
    )
    source = courses.create_source(course.id, kind="blueway snapshot", display_name="Verified", manifest=[], content_sha256="b" * 64)
    with courses._write_lock, courses._connect() as conn:
        conn.execute("UPDATE course_sources SET state = 'ready' WHERE id = ?", (source.id,))
    monkeypatch.setattr("deeptutor.integrations.blueway.workspace._candidate_databases", lambda: [db])

    first = project_workspace(_claims("fall"), now=1704067200.0 + 3600.0)
    second = project_workspace(_claims("fall"), now=1704067200.0 + 3600.0)
    assert first == second
    with courses._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM blueway_workspace_authorizations").fetchone()[0] == 1
        row = conn.execute("SELECT status, external_course_id, external_term_id FROM blueway_workspace_authorizations").fetchone()
    assert tuple(row) == ("active", "course-1", "fall")


def test_missing_or_altered_authorization_binding_fails_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("deeptutor.integrations.blueway.workspace._candidate_databases", lambda: [])
    with pytest.raises(ConsentRequiredError):
        project_workspace(_claims("fall"))


def test_altered_signed_client_binding_fails_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("deeptutor.integrations.blueway.workspace._candidate_databases", lambda: [])
    claims = _claims("fall")
    claims["client_id"] = "attacker-client"
    with pytest.raises(ConsentRequiredError):
        project_workspace(claims)
