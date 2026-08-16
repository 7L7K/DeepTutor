"""P4-01A checks for the transactional Course migration kernel."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import multiprocessing
import os
from pathlib import Path
import sqlite3
import threading

import pytest

from deeptutor.courses.migrations import runner
from deeptutor.courses.migrations.runner import (
    CourseMigrationError,
    CourseSchemaMismatchError,
    MigrationArtifact,
    discover_migrations,
    ensure_course_schema,
    open_course_connection,
)


def _artifact(version: int, name: str, sql: str) -> MigrationArtifact:
    return MigrationArtifact.from_resource(f"{version:04d}_{name}.sql", sql.encode())


def _ledger_sql() -> str:
    return """CREATE TABLE schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        checksum_sha256 TEXT NOT NULL,
        applied_at_utc TEXT NOT NULL
    );"""


def _spawned_first_start(
    db_path: str,
    barrier: multiprocessing.synchronize.Barrier,
    outcomes: multiprocessing.queues.Queue,
) -> None:
    """Run the public startup path in a separate interpreter/process."""

    try:
        barrier.wait(timeout=10)
        outcomes.put(("ok", ensure_course_schema(db_path)))
    except BaseException as exc:  # noqa: BLE001 - return child failure to parent assertion.
        outcomes.put(("error", f"{type(exc).__name__}: {exc}"))


def test_discovery_orders_exactly_and_rejects_duplicate_version_or_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Entry:
        def __init__(self, name: str) -> None:
            self.name = name

        def is_file(self) -> bool:
            return True

        def read_bytes(self) -> bytes:
            return b"SELECT 1;"

    class Root:
        def __init__(self, names: list[str]) -> None:
            self._entries = [Entry(name) for name in names]

        def joinpath(self, _name: str) -> "Root":
            return self

        def iterdir(self) -> list[Entry]:
            return self._entries

    monkeypatch.setattr(runner.resources, "files", lambda _package: Root([
        "0002_second.sql", "0000_first.sql", "0001_middle.sql",
    ]))
    assert [item.filename for item in discover_migrations()] == [
        "0000_first.sql", "0001_middle.sql", "0002_second.sql",
    ]

    monkeypatch.setattr(runner.resources, "files", lambda _package: Root([
        "0000_first.sql", "0000_second.sql",
    ]))
    with pytest.raises(CourseMigrationError, match="Duplicate Course migration version"):
        discover_migrations()

    monkeypatch.setattr(runner.resources, "files", lambda _package: Root([
        "0000_first.sql", "0001_first.sql",
    ]))
    with pytest.raises(CourseMigrationError, match="Duplicate Course migration name"):
        discover_migrations()


def test_expected_signature_cache_reuses_only_immutable_migration_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact(0, "cached", _ledger_sql() + "\nCREATE TABLE cached (id INTEGER);")
    calls = 0
    original_execute = runner._execute_sql_artifact

    def counted_execute(conn: sqlite3.Connection, sql: str) -> None:
        nonlocal calls
        calls += 1
        original_execute(conn, sql)

    runner._expected_signature_cached.cache_clear()
    monkeypatch.setattr(runner, "_execute_sql_artifact", counted_execute)
    try:
        first = runner._expected_signature((artifact,))
        baseline = runner._expected_signature((artifact,))
        first["tables"]["cached"]["columns"].clear()
        second = runner._expected_signature(iter((artifact,)))
    finally:
        runner._expected_signature_cached.cache_clear()

    assert baseline == second
    assert calls == 1

    runner._expected_signature_cached.cache_clear()
    calls = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        concurrent = list(pool.map(lambda _: runner._expected_signature((artifact,)), range(4)))

    assert concurrent == [baseline] * 4
    assert calls == 1


def test_receipt_uses_exact_artifact_bytes_and_tamper_blocks_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "courses.db"
    artifacts = discover_migrations()
    expected_versions = tuple(artifact.version for artifact in artifacts)
    assert ensure_course_schema(path) == expected_versions
    artifact = artifacts[0]
    with open_course_connection(path) as conn:
        receipt_before = tuple(conn.execute(
            "SELECT version, name, checksum_sha256 FROM schema_migrations"
        ).fetchone())
        table_count_before = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0]

    assert receipt_before == (artifact.version, artifact.name, artifact.checksum_sha256)
    tampered = replace(artifact, content=artifact.content + b"\n-- changed bytes\n")
    tampered = replace(tampered, checksum_sha256=runner.hashlib.sha256(tampered.content).hexdigest())
    monkeypatch.setattr(
        runner,
        "discover_migrations",
        lambda: (tampered, *artifacts[1:]),
    )

    with pytest.raises(CourseMigrationError, match="receipt mismatch"):
        ensure_course_schema(path)
    with open_course_connection(path) as conn:
        assert tuple(conn.execute(
            "SELECT version, name, checksum_sha256 FROM schema_migrations"
        ).fetchone()) == receipt_before
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0] == table_count_before


def test_unknown_recorded_receipt_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "courses.db"
    ensure_course_schema(path)
    with open_course_connection(path) as conn:
        conn.execute(
            "INSERT INTO schema_migrations VALUES (9999, 'unknown', 'deadbeef', 'now')"
        )
    with pytest.raises(CourseMigrationError, match="unknown migration"):
        ensure_course_schema(path)


def test_sql_failure_rolls_back_its_schema_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _artifact(
        0,
        "broken",
        _ledger_sql() + "\nCREATE TABLE should_rollback (id INTEGER);\nNOT VALID SQL;",
    )
    monkeypatch.setattr(runner, "discover_migrations", lambda: (artifact,))
    path = tmp_path / "courses.db"

    with pytest.raises(CourseMigrationError, match="0000_broken.sql failed"):
        ensure_course_schema(path)
    with sqlite3.connect(path) as conn:
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
    assert "schema_migrations" not in names
    assert "should_rollback" not in names


def test_failed_postcondition_rolls_back_its_schema_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _artifact(0, "postcondition", _ledger_sql() + "\nCREATE TABLE should_rollback (id INTEGER);")
    original_require = runner._require_signature

    def fail_postcondition(conn: sqlite3.Connection, expected: dict, *, context: str) -> None:
        if context.startswith("postcondition"):
            raise CourseSchemaMismatchError("intentional postcondition failure")
        original_require(conn, expected, context=context)

    monkeypatch.setattr(runner, "discover_migrations", lambda: (artifact,))
    monkeypatch.setattr(runner, "_require_signature", fail_postcondition)
    path = tmp_path / "courses.db"

    with pytest.raises(CourseSchemaMismatchError, match="intentional postcondition failure"):
        ensure_course_schema(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0] == 0


def test_foreign_key_check_rolls_back_only_the_active_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _artifact(
        0,
        "base",
        _ledger_sql()
        + "\nCREATE TABLE parents (id INTEGER PRIMARY KEY);"
        + "\nCREATE TABLE children (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parents(id));",
    )
    second = _artifact(1, "next", "CREATE TABLE should_rollback (id INTEGER);")
    path = tmp_path / "courses.db"
    monkeypatch.setattr(runner, "discover_migrations", lambda: (first,))
    assert ensure_course_schema(path) == (0,)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("INSERT INTO children (id, parent_id) VALUES (1, 404)")
        conn.commit()

    monkeypatch.setattr(runner, "discover_migrations", lambda: (first, second))
    with pytest.raises(CourseMigrationError, match="foreign-key check failed"):
        ensure_course_schema(path)
    with open_course_connection(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'should_rollback'"
        ).fetchone()[0] == 0


def test_concurrent_startup_applies_once_and_other_wrapper_observes_receipt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "courses.db"
    expected_versions = tuple(artifact.version for artifact in discover_migrations())
    barrier = threading.Barrier(2)
    results: list[tuple[int, ...]] = []
    errors: list[BaseException] = []

    def startup() -> None:
        try:
            barrier.wait(timeout=5)
            results.append(ensure_course_schema(path))
        except BaseException as exc:  # noqa: BLE001 - retain concurrent failure.
            errors.append(exc)

    first, second = threading.Thread(target=startup), threading.Thread(target=startup)
    first.start()
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert sorted(results) == [(), expected_versions]
    with open_course_connection(path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            == len(discover_migrations())
        )


def test_spawned_processes_first_start_apply_once_and_converge_on_one_receipt(
    tmp_path: Path,
) -> None:
    """The batch lock prevents process interleaving while SQLite protects each step."""

    path = tmp_path / "courses.db"
    expected_versions = tuple(artifact.version for artifact in discover_migrations())
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    outcomes = context.Queue()
    processes = [
        context.Process(target=_spawned_first_start, args=(str(path), barrier, outcomes))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)

    assert all(not process.is_alive() for process in processes)
    assert [process.exitcode for process in processes] == [0, 0]
    results = [outcomes.get(timeout=5) for _ in processes]
    assert sorted(results) == [
        ("ok", ()),
        ("ok", expected_versions),
    ]
    with open_course_connection(path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            == len(discover_migrations())
        )
        assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
        assert runner._schema_signature(conn, include_ledger=True) == runner._expected_signature(
            discover_migrations()
        )


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink contract")
def test_migration_lock_rejects_symlink_substitution(tmp_path: Path) -> None:
    path = tmp_path / "courses.db"
    target = tmp_path / "do-not-touch"
    target.write_text("private", encoding="utf-8")
    target.chmod(0o640)
    lock = tmp_path / ".courses.db.migration.lock"
    lock.symlink_to(target)

    with pytest.raises(CourseMigrationError, match="Could not open Course migration lock"):
        ensure_course_schema(path)

    assert target.read_text(encoding="utf-8") == "private"
    assert target.stat().st_mode & 0o777 == 0o640


def test_normal_connection_enables_and_verifies_foreign_keys(tmp_path: Path) -> None:
    path = tmp_path / "courses.db"
    ensure_course_schema(path)
    with open_course_connection(path) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
