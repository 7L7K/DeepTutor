"""BlueWay SQLite bootstrap concurrency and replay-guard regressions."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import threading
import time

import pytest

from deeptutor.courses.repository import CourseRepository
from deeptutor.integrations.blueway import repository as blueway_repository_module
from deeptutor.integrations.blueway.repository import BlueWayRepository


def test_blueway_repository_concurrent_initialization_keeps_replay_index_semantics(
    tmp_path: Path,
) -> None:
    """A worker and request can safely initialize separate wrappers together."""
    database_path = tmp_path / "user" / "courses.db"
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    left_courses = CourseRepository(database_path, "owner-race")
    right_courses = CourseRepository(database_path, "owner-race")

    def initialize(courses: CourseRepository) -> None:
        try:
            barrier.wait(timeout=5)
            BlueWayRepository(courses)
        except BaseException as exc:  # noqa: BLE001 - preserve thread failure.
            errors.append(exc)

    left = threading.Thread(target=initialize, args=(left_courses,))
    right = threading.Thread(target=initialize, args=(right_courses,))
    left.start()
    right.start()
    left.join(timeout=5)
    right.join(timeout=5)

    assert not left.is_alive() and not right.is_alive()
    assert errors == []
    repository = CourseRepository(database_path, "owner-race")
    with repository._connect() as connection:  # noqa: SLF001 - inspect effective definition.
        row = connection.execute(
            """SELECT sql FROM sqlite_master
               WHERE type = 'index' AND name = 'blueway_snapshot_replay'"""
        ).fetchone()
    assert row is not None
    normalized = " ".join(str(row["sql"]).upper().split())
    assert "CREATE UNIQUE INDEX BLUEWAY_SNAPSHOT_REPLAY" in normalized
    assert "ON BLUEWAY_SYNC_RUNS(CONNECTION_ID, SNAPSHOT_ID)" in normalized
    assert "WHERE SNAPSHOT_ID IS NOT NULL AND STATE = 'COMPLETED'" in normalized


def test_blueway_initialization_never_removes_live_replay_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A completed-receipt writer stays fenced while another wrapper initializes."""
    database_path = tmp_path / "user" / "courses.db"
    courses = CourseRepository(database_path, "owner-race")
    repository = BlueWayRepository(courses)
    connection = repository.create_active_connection(
        external_subject="subject-race", scope_version="phase3a"
    )
    now = time.time()
    with courses._connect() as database:  # noqa: SLF001 - arrange exact replay rows.
        database.executemany(
            """INSERT INTO blueway_sync_runs
               (id, connection_id, expected_generation, snapshot_id, snapshot_sha256,
                state, attempt_count, counts_json, error_code, created_at, updated_at,
                completed_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, '{}', NULL, ?, ?, ?)""",
            [
                (
                    "run-completed",
                    connection.id,
                    connection.grant_generation,
                    "snapshot-race",
                    "hash-race",
                    "completed",
                    now,
                    now,
                    now,
                ),
                (
                    "run-competing",
                    connection.id,
                    connection.grant_generation,
                    "snapshot-race",
                    "hash-race",
                    "indexing",
                    now,
                    now,
                    None,
                ),
            ],
        )

    initializer_entered = threading.Event()
    release_initializer = threading.Event()
    original_check = blueway_repository_module._snapshot_replay_index_is_current

    def pause_with_write_transaction(database: sqlite3.Connection) -> bool:
        current = original_check(database)
        initializer_entered.set()
        assert release_initializer.wait(5)
        return current

    monkeypatch.setattr(
        blueway_repository_module,
        "_snapshot_replay_index_is_current",
        pause_with_write_transaction,
    )
    initializer_errors: list[BaseException] = []
    writer_errors: list[BaseException] = []

    def initialize() -> None:
        try:
            BlueWayRepository(CourseRepository(database_path, "owner-race"))
        except BaseException as exc:  # noqa: BLE001 - preserve thread failure.
            initializer_errors.append(exc)

    def complete_duplicate() -> None:
        try:
            writer_courses = CourseRepository(database_path, "owner-race")
            with writer_courses._connect() as database:  # noqa: SLF001 - adversarial writer.
                database.execute("BEGIN IMMEDIATE")
                database.execute(
                    """UPDATE blueway_sync_runs
                       SET state = 'completed', completed_at = ?
                       WHERE id = 'run-competing'""",
                    (time.time(),),
                )
        except BaseException as exc:  # noqa: BLE001 - expected replay rejection.
            writer_errors.append(exc)

    initializer = threading.Thread(target=initialize)
    initializer.start()
    assert initializer_entered.wait(5)
    writer = threading.Thread(target=complete_duplicate)
    writer.start()
    time.sleep(0.05)
    assert writer.is_alive()
    release_initializer.set()
    initializer.join(timeout=5)
    writer.join(timeout=5)

    assert not initializer.is_alive() and not writer.is_alive()
    assert initializer_errors == []
    assert len(writer_errors) == 1
    assert isinstance(writer_errors[0], sqlite3.IntegrityError)
    with courses._connect() as database:  # noqa: SLF001 - verify durable invariant.
        completed = database.execute(
            """SELECT COUNT(*) FROM blueway_sync_runs
               WHERE connection_id = ? AND snapshot_id = ? AND state = 'completed'""",
            (connection.id, "snapshot-race"),
        ).fetchone()[0]
    assert completed == 1
