"""Forward-compatibility contract for the observability schema boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.courses.migrations import runner
from deeptutor.courses.migrations.runner import discover_migrations
from deeptutor.courses.repository import CourseRepository
from deeptutor.integrations.blueway.repository import BlueWayRepository


def test_bridge_upgrades_0017_and_restarts_after_full_candidate_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bridge is the rollback floor after it upgrades an 0017 database."""

    path = tmp_path / "courses.db"
    artifacts = discover_migrations()
    assert artifacts[-1].version == 18

    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts[:-1])
    courses_at_0017 = CourseRepository(path, "owner_one")
    connection_at_0017 = BlueWayRepository(courses_at_0017).create_active_connection(
        external_subject="provider-subject",
        scope_version="academic.read.v1",
    )
    assert connection_at_0017.observability_trace_id is None

    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts)
    bridge = CourseRepository(path, "owner_one")
    with bridge._connect() as conn:  # noqa: SLF001 - simulate a full-candidate write.
        conn.execute(
            "UPDATE blueway_connections SET observability_trace_id = ? WHERE id = ?",
            ("bwr_11111111-1111-4111-8111-111111111111", connection_at_0017.id),
        )

    restarted = BlueWayRepository(CourseRepository(path, "owner_one"))
    hydrated = restarted.active_connection()

    assert hydrated is not None
    assert hydrated.id == connection_at_0017.id
    assert hydrated.observability_trace_id == "bwr_11111111-1111-4111-8111-111111111111"
    with restarted.courses._connect() as conn:  # noqa: SLF001 - receipt proof.
        receipts = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    assert tuple(row["version"] for row in receipts) == tuple(
        artifact.version for artifact in artifacts
    )
