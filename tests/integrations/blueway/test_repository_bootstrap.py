"""P4-01C bootstrap-authority regressions for the BlueWay facade."""

from __future__ import annotations

from pathlib import Path
import threading

import pytest

from deeptutor.courses import repository as course_repository_module
from deeptutor.courses.migrations.runner import discover_migrations
from deeptutor.courses.repository import CourseRepository
from deeptutor.integrations.blueway.repository import BlueWayRepository


def test_fresh_blueway_repository_consumes_course_migrated_schema_without_ddl(
    tmp_path: Path,
) -> None:
    path = tmp_path / "courses.db"
    courses = CourseRepository(path, "owner_one")
    statements: list[str] = []
    with courses._connect() as conn:  # noqa: SLF001 - capture facade bootstrap SQL.
        conn.set_trace_callback(statements.append)
        BlueWayRepository(courses)
        conn.set_trace_callback(None)

    schema_statements = [
        statement for statement in statements
        if statement.lstrip().upper().startswith(("CREATE", "ALTER", "DROP"))
    ]
    assert schema_statements == []
    with courses._connect() as conn:  # noqa: SLF001 - migration receipt is sole authority.
        assert (
            conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            == len(discover_migrations())
        )


def test_fresh_course_repository_delegates_schema_creation_to_migration_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, object]] = []

    def record_runner(path: Path, *, write_lock: object) -> tuple[int, ...]:
        calls.append((path, write_lock))
        return (0,)

    monkeypatch.setattr(course_repository_module, "ensure_course_schema", record_runner)
    courses = CourseRepository(tmp_path / "courses.db", "owner_one")

    assert len(calls) == 1
    assert calls[0][0] == courses.db_path
    assert calls[0][1] is courses._write_lock  # noqa: SLF001 - delegated lock is contract.


def test_repeated_blueway_startup_is_receipt_and_schema_write_free(
    tmp_path: Path,
) -> None:
    path = tmp_path / "courses.db"
    courses = CourseRepository(path, "owner_one")
    with courses._connect() as conn:  # noqa: SLF001 - establish receipt identity.
        receipts_before = [
            tuple(row) for row in conn.execute(
            "SELECT version, name, checksum_sha256, applied_at_utc FROM schema_migrations"
            " ORDER BY version"
        ).fetchall()]

    BlueWayRepository(courses)
    restarted = CourseRepository(path, "owner_one")
    BlueWayRepository(restarted)

    with restarted._connect() as conn:  # noqa: SLF001 - prove restart remains no-op.
        assert [
            tuple(row) for row in conn.execute(
            "SELECT version, name, checksum_sha256, applied_at_utc FROM schema_migrations"
            " ORDER BY version"
        ).fetchall()] == receipts_before


def test_concurrent_course_and_blueway_wrappers_share_one_path_lock_and_bootstrap_once(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "courses.db"
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    locks: list[object] = []

    def initialize() -> None:
        try:
            barrier.wait(timeout=5)
            courses = CourseRepository(path, "owner_race")
            locks.append(courses._write_lock)  # noqa: SLF001 - lock identity is contract.
            BlueWayRepository(courses)
        except BaseException as exc:  # noqa: BLE001 - preserve thread failure.
            errors.append(exc)

    first, second = threading.Thread(target=initialize), threading.Thread(target=initialize)
    first.start()
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert len(locks) == 2 and locks[0] is locks[1]
    with CourseRepository(path, "owner_race")._connect() as conn:  # noqa: SLF001
        assert (
            conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            == len(discover_migrations())
        )


def test_blueway_bootstrap_delegates_only_to_course_schema_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses = CourseRepository(tmp_path / "courses.db", "owner_one")
    calls: list[object] = []

    def record_only() -> None:
        calls.append(object())

    def no_independent_database_access() -> None:
        raise AssertionError("BlueWay bootstrap must not open its own DDL connection")

    monkeypatch.setattr(courses, "ensure_schema", record_only)
    monkeypatch.setattr(courses, "_connect", no_independent_database_access)
    BlueWayRepository(courses)
    assert len(calls) == 1
