"""Forward-compatibility contract for the observability schema boundary."""

from __future__ import annotations

from pathlib import Path
import time

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
    assert next(
        artifact.version
        for artifact in artifacts
        if artifact.name == "blueway_observability_trace"
    ) == 18

    through_0017 = tuple(artifact for artifact in artifacts if artifact.version <= 17)
    assert tuple(artifact.version for artifact in through_0017) == tuple(range(18))
    monkeypatch.setattr(runner, "discover_migrations", lambda: through_0017)
    courses_at_0017 = CourseRepository(path, "owner_one")
    connection_id = "bwc_11111111111141118111111111111111"
    now = time.time()
    with courses_at_0017._connect() as conn:  # noqa: SLF001 - legacy writer fixture.
        conn.execute(
            """INSERT INTO blueway_connections
               (id, owner_user_id, external_subject, state, scope_version,
                revision, grant_generation, credential_ref, credential_status,
                created_at, updated_at, connected_at, last_sync_at,
                disconnected_at, rotation_request_id, rotation_started_at)
               VALUES (?, ?, ?, 'active', ?, 1, 1, ?, 'healthy', ?, ?, ?,
                       NULL, NULL, NULL, NULL)""",
            (
                connection_id,
                "owner_one",
                "provider-subject",
                "academic.read.v1",
                f"blueway:{connection_id}",
                now,
                now,
                now,
            ),
        )

    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts)
    candidate = BlueWayRepository(CourseRepository(path, "owner_one"))
    candidate.ensure_observability_trace(
        connection_id,
        trace_id="bwr_11111111-1111-4111-8111-111111111111",
    )

    restarted = BlueWayRepository(CourseRepository(path, "owner_one"))
    hydrated = restarted.active_connection()

    assert hydrated is not None
    assert hydrated.id == connection_id
    assert hydrated.observability_trace_id == "bwr_11111111-1111-4111-8111-111111111111"
    with restarted.courses._connect() as conn:  # noqa: SLF001 - receipt proof.
        receipts = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    assert tuple(row["version"] for row in receipts) == tuple(
        artifact.version for artifact in artifacts
    )
