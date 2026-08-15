"""Transactional, checksum-backed schema authority for ``courses.db``."""

from __future__ import annotations

from contextlib import contextmanager
import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import time
from typing import Any, Iterable, Iterator
import unicodedata

from pydantic import TypeAdapter, ValidationError

from deeptutor.courses.assessment_grading import grade_assessment_response
from deeptutor.courses.database_lock import course_database_lock
from deeptutor.courses.practice_models import (
    BoundedShortAnswerContract,
    ExactAnswerContract,
    PracticeAnswerContract,
    SingleChoiceAnswerContract,
    SingleChoiceOption,
)

_MIGRATION_FILE = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")
_CORE_PHASE3A_TABLES = frozenset({"courses", "course_sources"})
_EXPECTED_SIGNATURE_CACHE_LOCK = threading.Lock()


@contextmanager
def _windows_migration_batch_lock(db_path: Path) -> Iterator[None]:
    """Use a process-session mutex without following a filesystem reparse point."""

    import ctypes
    from ctypes import wintypes

    mutex_name = "Local\\DeepTutorCourseMigration-" + hashlib.sha256(
        os.path.normcase(str(db_path)).encode("utf-8")
    ).hexdigest()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    create_mutex.restype = wintypes.HANDLE
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    wait_for_single_object.restype = wintypes.DWORD
    release_mutex = kernel32.ReleaseMutex
    release_mutex.argtypes = (wintypes.HANDLE,)
    release_mutex.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = create_mutex(None, False, mutex_name)
    if not handle:
        raise CourseMigrationError(
            f"Could not create Course migration mutex: {db_path}"
        )
    acquired = False
    try:
        result = int(wait_for_single_object(handle, 10_000))
        if result not in {0x00000000, 0x00000080}:  # object or abandoned mutex
            if result == 0x00000102:
                raise CourseMigrationError(
                    f"Timed out waiting for Course migration lock: {db_path}"
                )
            raise CourseMigrationError(
                f"Could not acquire Course migration mutex: {db_path}"
            )
        acquired = True
        yield
    finally:
        if acquired:
            release_mutex(handle)
        close_handle(handle)


@contextmanager
def _migration_batch_lock(db_path: Path) -> Iterator[None]:
    """Serialize a database's migration batch without widening SQL rollback.

    SQLite transactions remain authoritative for each individual migration.
    The Windows named mutex or POSIX sidecar lock prevents separate processes
    from interleaving those committed steps and splitting the list of versions
    reported by one startup. The POSIX lock file is intentionally retained so
    removing it cannot race a waiter.
    """

    if os.name == "nt":
        with _windows_migration_batch_lock(db_path):
            yield
        return

    lock_path = db_path.with_name(f".{db_path.name}.migration.lock")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise CourseMigrationError(
            f"Could not open Course migration lock: {db_path}"
        ) from exc
    handle = os.fdopen(descriptor, "r+b", buffering=0)
    metadata = os.fstat(handle.fileno())
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        handle.close()
        raise CourseMigrationError(
            f"Course migration lock is not a private regular file: {db_path}"
        )
    if metadata.st_uid != os.getuid():
        handle.close()
        raise CourseMigrationError(
            f"Course migration lock has an unexpected owner: {db_path}"
        )
    os.fchmod(handle.fileno(), 0o600)
    deadline = time.monotonic() + 10.0
    acquired = False
    try:
        while not acquired:
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise CourseMigrationError(
                        f"Timed out waiting for Course migration lock: {db_path}"
                    ) from exc
                time.sleep(0.02)
        yield
    finally:
        if acquired:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


class CourseMigrationError(RuntimeError):
    """A Course schema migration or receipt validation failed."""


class CourseSchemaMismatchError(CourseMigrationError):
    """A ledger-free or ledger-bearing database has an unknown managed shape."""


@dataclass(frozen=True)
class MigrationArtifact:
    version: int
    name: str
    filename: str
    content: bytes
    checksum_sha256: str

    @classmethod
    def from_resource(cls, filename: str, content: bytes) -> "MigrationArtifact":
        match = _MIGRATION_FILE.fullmatch(filename)
        if match is None:
            raise CourseMigrationError(f"Invalid Course migration filename: {filename}")
        return cls(
            version=int(match.group("version")),
            name=match.group("name"),
            filename=filename,
            content=content,
            checksum_sha256=hashlib.sha256(content).hexdigest(),
        )


def discover_migrations() -> tuple[MigrationArtifact, ...]:
    """Load the immutable packaged SQL artifacts in numeric order."""

    root = resources.files(__package__).joinpath("sql")
    artifacts = [
        MigrationArtifact.from_resource(entry.name, entry.read_bytes())
        for entry in root.iterdir()
        if entry.is_file() and entry.name.endswith(".sql")
    ]
    artifacts.sort(key=lambda item: (item.version, item.name))
    versions: set[int] = set()
    names: set[str] = set()
    for artifact in artifacts:
        if artifact.version in versions:
            raise CourseMigrationError(
                f"Duplicate Course migration version: {artifact.version:04d}"
            )
        if artifact.name in names:
            raise CourseMigrationError(
                f"Duplicate Course migration name: {artifact.name}"
            )
        versions.add(artifact.version)
        names.add(artifact.name)
    if not artifacts or artifacts[0].version != 0:
        raise CourseMigrationError("Course migrations must begin at version 0000")
    return tuple(artifacts)


def open_course_connection(db_path: Path | str) -> sqlite3.Connection:
    """Open a normal Course connection with verified foreign-key enforcement."""

    conn = sqlite3.connect(Path(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    _register_course_validation_functions(conn)
    conn.execute("PRAGMA foreign_keys = ON")
    if int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
        conn.close()
        raise CourseMigrationError("SQLite foreign-key enforcement is unavailable")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _register_course_validation_functions(conn: sqlite3.Connection) -> None:
    """Install deterministic validators used by managed grading triggers."""

    def canonical_sha256(value: object) -> str | None:
        try:
            parsed = json.loads(str(value))
            canonical = json.dumps(
                parsed, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def exact_evidence_valid(
        payload_sha256: object, grading_json: object, algorithm: object,
        attempt_id: object, attempt_item_id: object, question_id: object,
        objective_id: object, module_id: object, knowledge_type: object,
        is_correct: object, error_type: object, answer_contract_json: object,
        response_json: object,
    ) -> int:
        digest = canonical_sha256(grading_json)
        if digest is None or digest != str(payload_sha256) or algorithm != "exact-v1":
            return 0
        try:
            payload = json.loads(str(grading_json))
        except (TypeError, ValueError, json.JSONDecodeError):
            return 0
        required = {
            "algorithm", "attempt_id", "attempt_item_id", "question_id", "objective_id",
            "module_id", "knowledge_type", "contract_sha256", "response_sha256",
            "is_correct", "error_type",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            return 0
        if any(
            not isinstance(payload[key], str) or len(payload[key]) != 64
            or any(char not in "0123456789abcdef" for char in payload[key])
            for key in ("contract_sha256", "response_sha256")
        ):
            return 0
        try:
            contract = json.loads(str(answer_contract_json))
            response = json.loads(str(response_json))
            expected_answer = contract["answer"]
            accepted_answers = contract.get("accepted_answers", [])
            actual_answer = response["answer"]
            if (
                set(contract) not in ({"kind", "answer"}, {"kind", "answer", "accepted_answers"})
                or contract["kind"] != "exact"
                or not isinstance(accepted_answers, list)
                or any(not isinstance(item, str) for item in accepted_answers)
            ):
                return 0
            if set(response) != {"answer"}:
                return 0
            if not isinstance(expected_answer, str) or not isinstance(actual_answer, str):
                return 0
            def normalize(value: str) -> str:
                return unicodedata.normalize("NFC", value).strip().casefold()
            actual_correct = any(
                normalize(actual_answer) == normalize(candidate)
                for candidate in [expected_answer, *accepted_answers]
            )
            actual_error = None if actual_correct else (
                "metacognitive" if not actual_answer.strip() else "application"
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return 0
        expected = {
            "algorithm": algorithm, "attempt_id": attempt_id, "attempt_item_id": attempt_item_id,
            "question_id": question_id, "objective_id": objective_id, "module_id": module_id,
            "knowledge_type": knowledge_type, "is_correct": bool(is_correct), "error_type": error_type,
        }
        return int(
            all(payload[key] == value for key, value in expected.items())
            and payload["contract_sha256"] == canonical_sha256(answer_contract_json)
            and payload["response_sha256"] == canonical_sha256(response_json)
            and payload["is_correct"] == actual_correct
            and payload["error_type"] == actual_error
        )

    answer_contract_adapter = TypeAdapter(PracticeAnswerContract)

    def question_contract_valid(
        question_type: object,
        answer_contract_json: object,
        options_json: object,
    ) -> int:
        try:
            contract = answer_contract_adapter.validate_python(
                json.loads(str(answer_contract_json))
            )
            raw_options = json.loads(str(options_json))
            if not isinstance(raw_options, list):
                return 0
            options = [SingleChoiceOption.model_validate(item) for item in raw_options]
            if isinstance(contract, SingleChoiceAnswerContract):
                option_ids = [item.option_id for item in options]
                option_text = [" ".join(item.text.casefold().split()) for item in options]
                return int(
                    str(question_type) == "single_choice"
                    and 2 <= len(options) <= 8
                    and len(option_ids) == len(set(option_ids))
                    and len(option_text) == len(set(option_text))
                    and contract.correct_option_id in option_ids
                )
            if isinstance(contract, BoundedShortAnswerContract):
                return int(str(question_type) == "short_answer" and not options)
            if isinstance(contract, ExactAnswerContract):
                legacy_type = str(question_type)
                return int(
                    bool(legacy_type)
                    and legacy_type == legacy_type.strip()
                    and len(legacy_type) <= 80
                    and legacy_type != "single_choice"
                    and not options
                )
            return 0
        except (TypeError, ValueError, json.JSONDecodeError, ValidationError):
            return 0

    def assessment_evidence_valid(
        payload_sha256: object,
        grading_json: object,
        algorithm: object,
        attempt_id: object,
        attempt_item_id: object,
        question_id: object,
        objective_id: object,
        module_id: object,
        knowledge_type: object,
        is_correct: object,
        error_type: object,
        answer_contract_json: object,
        options_json: object,
        option_order_json: object,
        response_json: object,
    ) -> int:
        digest = canonical_sha256(grading_json)
        if digest is None or digest != str(payload_sha256):
            return 0
        try:
            payload = json.loads(str(grading_json))
            contract = answer_contract_adapter.validate_python(
                json.loads(str(answer_contract_json))
            )
            raw_options = json.loads(str(options_json))
            response = json.loads(str(response_json))
            if not isinstance(raw_options, list):
                return 0
            options = [SingleChoiceOption.model_validate(item) for item in raw_options]
            decision = grade_assessment_response(response, contract, options)
        except (TypeError, ValueError, json.JSONDecodeError, ValidationError):
            return 0

        contract_kind = contract.kind
        expected_algorithm = (
            "exact-v1" if contract_kind == "exact" else contract_kind
        )
        if algorithm != expected_algorithm:
            return 0
        base_keys = {
            "algorithm",
            "attempt_id",
            "attempt_item_id",
            "question_id",
            "objective_id",
            "module_id",
            "knowledge_type",
            "contract_sha256",
            "response_sha256",
            "is_correct",
            "error_type",
        }
        if expected_algorithm == "exact-v1":
            required_keys = base_keys
        elif expected_algorithm == "bounded_short_answer_v1":
            required_keys = base_keys | {
                "answer_contract_kind",
                "normalization_version",
                "raw_response",
                "normalized_response",
            }
        else:
            required_keys = base_keys | {
                "answer_contract_kind",
                "selected_option_id",
                "correct_option_id",
                "options_sha256",
                "option_order_sha256",
            }
        if not isinstance(payload, dict) or set(payload) != required_keys:
            return 0
        if any(
            not isinstance(payload[key], str)
            or len(payload[key]) != 64
            or any(char not in "0123456789abcdef" for char in payload[key])
            for key in (
                "contract_sha256",
                "response_sha256",
                *(
                    ("options_sha256", "option_order_sha256")
                    if expected_algorithm == "single_choice_v1"
                    else ()
                ),
            )
        ):
            return 0
        expected = {
            "algorithm": expected_algorithm,
            "attempt_id": attempt_id,
            "attempt_item_id": attempt_item_id,
            "question_id": question_id,
            "objective_id": objective_id,
            "module_id": module_id,
            "knowledge_type": knowledge_type,
            "is_correct": bool(is_correct),
            "error_type": error_type,
        }
        if not all(payload[key] == value for key, value in expected.items()):
            return 0
        if (
            payload["contract_sha256"] != canonical_sha256(answer_contract_json)
            or payload["response_sha256"] != canonical_sha256(response_json)
            or payload["is_correct"] != decision.is_correct
            or payload["error_type"] != decision.error_type
        ):
            return 0
        if expected_algorithm == "bounded_short_answer_v1":
            return int(
                payload["answer_contract_kind"] == contract.kind
                and payload["normalization_version"] == contract.normalization_version
                and payload["raw_response"] == decision.raw_response
                and payload["normalized_response"] == decision.normalized_response
            )
        if expected_algorithm == "single_choice_v1":
            try:
                option_order = json.loads(str(option_order_json))
            except (TypeError, ValueError, json.JSONDecodeError):
                return 0
            option_ids = [item.option_id for item in options]
            if (
                not isinstance(option_order, list)
                or any(not isinstance(item, str) for item in option_order)
                or len(option_order) != len(set(option_order))
                or set(option_order) != set(option_ids)
            ):
                return 0
            return int(
                payload["answer_contract_kind"] == contract.kind
                and payload["selected_option_id"] == decision.raw_response
                and payload["correct_option_id"] == contract.correct_option_id
                and payload["options_sha256"] == canonical_sha256(options_json)
                and payload["option_order_sha256"] == canonical_sha256(option_order_json)
            )
        return 1

    def item_grading_valid(grading_json: object, is_correct: object, error_type: object) -> int:
        try:
            payload = json.loads(str(grading_json))
            ids = payload.get("evidence_ids")
            return int(
                isinstance(payload, dict)
                and set(payload) == {"algorithm", "is_correct", "evidence_ids"}
                and payload["algorithm"] in {
                    "exact-v1",
                    "bounded_short_answer_v1",
                    "single_choice_v1",
                }
                and payload["is_correct"] == bool(is_correct)
                and isinstance(ids, list) and bool(ids)
                and len(ids) == len(set(ids)) and all(isinstance(item, str) and item.startswith("grd_") for item in ids)
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return 0

    def score_valid(score_json: object, correct: object, total: object) -> int:
        try:
            payload = json.loads(str(score_json))
            return int(
                isinstance(payload, dict) and set(payload) == {"correct", "total", "fraction"}
                and payload["correct"] == int(correct) and payload["total"] == int(total)
                and isinstance(payload["fraction"], (int, float))
                and payload["fraction"] == int(correct) / int(total)
            )
        except (TypeError, ValueError, ZeroDivisionError, json.JSONDecodeError):
            return 0

    conn.create_function("teeechr_canonical_sha256", 1, canonical_sha256, deterministic=True)
    conn.create_function("teeechr_exact_evidence_valid", 13, exact_evidence_valid, deterministic=True)
    conn.create_function(
        "teeechr_question_contract_valid",
        3,
        question_contract_valid,
        deterministic=True,
    )
    conn.create_function(
        "teeechr_assessment_evidence_valid",
        15,
        assessment_evidence_valid,
        deterministic=True,
    )
    conn.create_function("teeechr_item_grading_valid", 3, item_grading_valid, deterministic=True)
    conn.create_function("teeechr_score_valid", 3, score_valid, deterministic=True)


def ensure_course_schema(
    db_path: Path | str,
    *,
    write_lock: threading.RLock | None = None,
) -> tuple[int, ...]:
    """Validate or migrate one private Course database.

    Returns the versions applied by this invocation. Unknown or partial
    ledger-free schemas are rejected before any schema or journal-mode write.
    """

    resolved = Path(db_path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    lock = write_lock or course_database_lock(resolved)
    artifacts = discover_migrations()
    with lock, _migration_batch_lock(resolved):
        conn = open_course_connection(resolved)
        conn.isolation_level = None
        try:
            applied_count = _inspect_migration_state(conn, artifacts)
            if applied_count == len(artifacts):
                _verify_foreign_keys(conn)
                return ()
            _ensure_wal(conn)
            applied: list[int] = []
            while True:
                try:
                    # The process-local lock coordinates repository wrappers and
                    # the sidecar lock coordinates this complete batch across
                    # processes. Keep one SQLite transaction per migration so a
                    # later failure cannot erase earlier committed receipts.
                    conn.execute("BEGIN IMMEDIATE")
                    applied_count = _inspect_migration_state(conn, artifacts)
                    if applied_count == len(artifacts):
                        _verify_foreign_keys(conn)
                        conn.execute("COMMIT")
                        return tuple(applied)
                    artifact = artifacts[applied_count]
                    _apply_migration_in_transaction(
                        conn,
                        artifact,
                        artifacts[: applied_count + 1],
                    )
                    conn.execute("COMMIT")
                    applied.append(artifact.version)
                except Exception:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise
        finally:
            conn.close()


def _inspect_migration_state(
    conn: sqlite3.Connection,
    artifacts: tuple[MigrationArtifact, ...],
) -> int:
    if _table_exists(conn, "schema_migrations"):
        applied_count = _validate_receipts(conn, artifacts)
        expected = _expected_signature(artifacts[:applied_count])
        _require_signature(conn, expected, context="recorded migration state")
        return applied_count

    profile = _classify_ledger_free(conn, artifacts)
    if profile != "unknown":
        return 0

    expected = _expected_signature(artifacts[:1], include_ledger=False)
    actual = _schema_signature(conn, include_ledger=False)
    detail = "; ".join(_signature_differences(actual, expected))
    raise CourseSchemaMismatchError(
        "Unrecognized Course database schema; no changes were made"
        + (f": {detail}" if detail else "")
    )


def _validate_receipts(
    conn: sqlite3.Connection,
    artifacts: tuple[MigrationArtifact, ...],
) -> int:
    rows = conn.execute(
        """SELECT version, name, checksum_sha256
           FROM schema_migrations ORDER BY version"""
    ).fetchall()
    if len(rows) > len(artifacts):
        raise CourseMigrationError("Course database records an unknown migration")
    for index, row in enumerate(rows):
        expected = artifacts[index]
        actual = (int(row["version"]), str(row["name"]), str(row["checksum_sha256"]))
        wanted = (expected.version, expected.name, expected.checksum_sha256)
        if actual != wanted:
            raise CourseMigrationError(
                "Course migration receipt mismatch at "
                f"{expected.version:04d}_{expected.name}"
            )
    return len(rows)


def _classify_ledger_free(
    conn: sqlite3.Connection,
    artifacts: tuple[MigrationArtifact, ...],
) -> str:
    actual = _schema_signature(conn, include_ledger=False)
    if not actual["tables"] and not actual["views"] and not actual["triggers"]:
        return "empty"
    full = _expected_signature(artifacts[:1], include_ledger=False)
    if actual == full:
        return "phase3a_course_plus_blueway"
    core = _filter_signature_tables(full, _CORE_PHASE3A_TABLES)
    if actual == core:
        return "phase3a_course_only"
    return "unknown"


def _apply_migration_in_transaction(
    conn: sqlite3.Connection,
    artifact: MigrationArtifact,
    expected_artifacts: tuple[MigrationArtifact, ...],
) -> None:
    try:
        _execute_sql_artifact(conn, artifact.content.decode("utf-8"))
        _verify_foreign_keys(conn)
        expected = _expected_signature(expected_artifacts)
        _require_signature(
            conn,
            expected,
            context=f"postcondition for {artifact.filename}",
        )
        conn.execute(
            """INSERT INTO schema_migrations
               (version, name, checksum_sha256, applied_at_utc)
               VALUES (?, ?, ?, ?)""",
            (
                artifact.version,
                artifact.name,
                artifact.checksum_sha256,
                datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            ),
        )
    except Exception as exc:
        if isinstance(exc, CourseMigrationError):
            raise
        raise CourseMigrationError(
            f"Course migration {artifact.filename} failed: {exc}"
        ) from exc


def _execute_sql_artifact(conn: sqlite3.Connection, sql: str) -> None:
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            buffer = ""
            if statement:
                conn.execute(statement)
    if buffer.strip():
        raise CourseMigrationError("Migration artifact ends with incomplete SQL")


def _ensure_wal(conn: sqlite3.Connection) -> None:
    deadline = time.monotonic() + 10.0
    while True:
        try:
            current = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            if current == "wal":
                return
            mode = str(conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
            if mode == "wal":
                return
            raise CourseMigrationError(f"Could not enable SQLite WAL mode: {mode}")
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                raise CourseMigrationError(
                    f"Could not enable SQLite WAL mode: {exc}"
                ) from exc
            time.sleep(0.02)


def _verify_foreign_keys(conn: sqlite3.Connection) -> None:
    if int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
        raise CourseMigrationError("SQLite foreign-key enforcement became disabled")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        first = tuple(violations[0])
        raise CourseMigrationError(f"SQLite foreign-key check failed: {first}")


def _expected_signature(
    artifacts: Iterable[MigrationArtifact],
    *,
    include_ledger: bool = True,
) -> dict[str, Any]:
    """Return the immutable expected schema shape for these migration bytes.

    The expected shape depends only on the migration artifacts, never on a
    user's database. Cache that pure computation so concurrent private-database
    initialization does not rebuild the same in-memory schema once per owner.
    """

    with _EXPECTED_SIGNATURE_CACHE_LOCK:
        cached = _expected_signature_cached(tuple(artifacts), include_ledger)
    return copy.deepcopy(cached)


@lru_cache(maxsize=32)
def _expected_signature_cached(
    artifacts: tuple[MigrationArtifact, ...],
    include_ledger: bool,
) -> dict[str, Any]:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    _register_course_validation_functions(conn)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        for artifact in artifacts:
            conn.execute("BEGIN IMMEDIATE")
            try:
                _execute_sql_artifact(conn, artifact.content.decode("utf-8"))
                conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        return _schema_signature(conn, include_ledger=include_ledger)
    finally:
        conn.close()


def _schema_signature(
    conn: sqlite3.Connection,
    *,
    include_ledger: bool,
) -> dict[str, Any]:
    table_rows = conn.execute(
        """SELECT name, sql FROM sqlite_master
           WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
           ORDER BY name"""
    ).fetchall()
    tables: dict[str, Any] = {}
    for table_row in table_rows:
        table = str(table_row["name"])
        if table == "schema_migrations" and not include_ledger:
            continue
        columns = sorted(
            [
                {
                    "name": str(row["name"]),
                    "type": str(row["type"]).upper(),
                    "notnull": bool(row["notnull"]),
                    "default": row["dflt_value"],
                    "pk": int(row["pk"]),
                    "hidden": int(row["hidden"]),
                }
                for row in conn.execute(f'PRAGMA table_xinfo("{table}")').fetchall()
            ],
            key=lambda item: item["name"],
        )
        foreign_keys = sorted(
            [
                {
                    "id": int(row["id"]),
                    "seq": int(row["seq"]),
                    "from": str(row["from"]),
                    "table": str(row["table"]),
                    "to": str(row["to"]),
                    "on_update": str(row["on_update"]).upper(),
                    "on_delete": str(row["on_delete"]).upper(),
                    "match": str(row["match"]).upper(),
                }
                for row in conn.execute(
                    f'PRAGMA foreign_key_list("{table}")'
                ).fetchall()
            ],
            key=lambda item: (
                item["id"],
                item["seq"],
                item["from"],
                item["table"],
                item["to"],
            ),
        )
        named_indexes: list[dict[str, Any]] = []
        unique_constraints: list[list[dict[str, Any]]] = []
        for index_row in conn.execute(f'PRAGMA index_list("{table}")').fetchall():
            index_name = str(index_row["name"])
            key_terms = [
                {
                    "cid": int(row["cid"]),
                    "name": str(row["name"]) if row["name"] is not None else None,
                    "order": "DESC" if bool(row["desc"]) else "ASC",
                    "collation": (
                        str(row["coll"]).upper() if row["coll"] is not None else None
                    ),
                }
                for row in conn.execute(
                    f'PRAGMA index_xinfo("{index_name}")'
                ).fetchall()
                if bool(row["key"])
            ]
            origin = str(index_row["origin"])
            if origin == "u":
                unique_constraints.append(key_terms)
                continue
            if origin != "c":
                continue
            sql_row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
                (index_name,),
            ).fetchone()
            index_sql = str(sql_row["sql"]) if sql_row else ""
            where_match = re.search(r"\bWHERE\b", index_sql, flags=re.IGNORECASE)
            where = (
                _normalize_sql(index_sql[where_match.end() :])
                if where_match is not None
                else None
            )
            named_indexes.append(
                {
                    "name": index_name,
                    "unique": bool(index_row["unique"]),
                    "key_terms": key_terms,
                    "definition": _normalize_index_definition(index_sql),
                    "where": where,
                }
            )
        tables[table] = {
            "columns": columns,
            "foreign_keys": foreign_keys,
            "checks": _extract_checks(str(table_row["sql"] or "")),
            "explicit_collations": _extract_explicit_collations(
                str(table_row["sql"] or "")
            ),
            "named_indexes": sorted(named_indexes, key=lambda item: item["name"]),
            "unique_constraints": sorted(
                unique_constraints,
                key=lambda terms: repr(terms),
            ),
        }
    views = [
        {
            "name": str(row["name"]),
            "sql": _normalize_sql(str(row["sql"] or "")),
        }
        for row in conn.execute(
            """SELECT name, sql FROM sqlite_master
               WHERE type = 'view' ORDER BY name"""
        ).fetchall()
    ]
    triggers = [
        {
            "name": str(row["name"]),
            "table": str(row["tbl_name"]),
            "sql": _normalize_sql(str(row["sql"] or "")),
        }
        for row in conn.execute(
            """SELECT name, tbl_name, sql FROM sqlite_master
               WHERE type = 'trigger' ORDER BY name"""
        ).fetchall()
    ]
    return {"tables": tables, "views": views, "triggers": triggers}


def _filter_signature_tables(
    signature: dict[str, Any],
    allowed: frozenset[str],
) -> dict[str, Any]:
    return {
        "tables": {
            name: value
            for name, value in signature["tables"].items()
            if name in allowed
        },
        "triggers": [
            trigger
            for trigger in signature["triggers"]
            if trigger["table"] in allowed
        ],
        "views": [],
    }


def _require_signature(
    conn: sqlite3.Connection,
    expected: dict[str, Any],
    *,
    context: str,
) -> None:
    actual = _schema_signature(conn, include_ledger=True)
    if actual == expected:
        return
    detail = "; ".join(_signature_differences(actual, expected))
    raise CourseSchemaMismatchError(
        f"Course schema mismatch in {context}" + (f": {detail}" if detail else "")
    )


def _signature_differences(
    actual: dict[str, Any],
    expected: dict[str, Any],
    *,
    limit: int = 12,
) -> list[str]:
    differences: list[str] = []
    actual_tables = actual["tables"]
    expected_tables = expected["tables"]
    for table in sorted(expected_tables.keys() - actual_tables.keys()):
        differences.append(f"missing table {table}")
    for table in sorted(actual_tables.keys() - expected_tables.keys()):
        differences.append(f"unexpected table {table}")
    for table in sorted(actual_tables.keys() & expected_tables.keys()):
        actual_table = actual_tables[table]
        expected_table = expected_tables[table]
        actual_columns = {item["name"]: item for item in actual_table["columns"]}
        expected_columns = {item["name"]: item for item in expected_table["columns"]}
        for column in sorted(expected_columns.keys() - actual_columns.keys()):
            differences.append(f"{table}: missing column {column}")
        for column in sorted(actual_columns.keys() - expected_columns.keys()):
            differences.append(f"{table}: unexpected column {column}")
        for column in sorted(actual_columns.keys() & expected_columns.keys()):
            if actual_columns[column] != expected_columns[column]:
                differences.append(f"{table}: column mismatch {column}")
        for field in (
            "foreign_keys",
            "checks",
            "explicit_collations",
            "named_indexes",
            "unique_constraints",
        ):
            if actual_table[field] != expected_table[field]:
                differences.append(f"{table}: {field} mismatch")
        if len(differences) >= limit:
            break
    if actual["triggers"] != expected["triggers"]:
        differences.append("trigger definitions mismatch")
    if actual["views"] != expected["views"]:
        differences.append("view definitions mismatch")
    return differences[:limit]


def _normalize_sql(value: str) -> str:
    # SQLite may preserve harmless formatting differences in ``sqlite_master``.
    # Remove whitespace only outside quoted literals/identifiers so equivalent
    # checked-in and legacy definitions compare equally without changing string
    # literal semantics.
    normalized: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(value):
        char = value[index]
        if quote is not None:
            normalized.append(char)
            if char == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    normalized.append(value[index + 1])
                    index += 1
                else:
                    quote = None
        elif char in {"'", '"', "`"}:
            quote = char
            normalized.append(char)
        elif not char.isspace() and char != ";":
            normalized.append(char.lower())
        index += 1
    return "".join(normalized)


def _normalize_index_definition(value: str) -> str:
    """Normalize harmless index DDL spelling while retaining its semantics."""

    return _normalize_sql(value).replace("ifnotexists", "")


def _extract_checks(sql: str) -> list[str]:
    checks: list[str] = []
    upper = sql.upper()
    cursor = 0
    while True:
        match = re.search(r"\bCHECK\s*\(", upper[cursor:])
        if match is None:
            break
        opening = cursor + match.end() - 1
        depth = 0
        quote: str | None = None
        index = opening
        while index < len(sql):
            char = sql[index]
            if quote is not None:
                if char == quote:
                    if index + 1 < len(sql) and sql[index + 1] == quote:
                        index += 1
                    else:
                        quote = None
            elif char in {"'", '"'}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    checks.append(_normalize_sql(sql[opening + 1 : index]))
                    cursor = index + 1
                    break
            index += 1
        else:
            raise CourseMigrationError("Unbalanced CHECK constraint in schema")
    return sorted(checks)


def _extract_explicit_collations(sql: str) -> list[dict[str, str]]:
    """Return explicit column collations, including quoted SQLite identifiers."""

    identifier = (
        r'(?:"(?:[^"]|"")*"|`(?:[^`]|``)*`|\[(?:[^\]]|\]\])*\]|'
        r"[A-Za-z_][A-Za-z0-9_]*)"
    )
    declarations: list[dict[str, str]] = []
    for definition in _split_table_definitions(sql):
        column_match = re.match(rf"\s*(?P<column>{identifier})", definition)
        if column_match is None:
            continue
        column = _unquote_sqlite_identifier(column_match.group("column"))
        if column.upper() in {
            "CHECK",
            "CONSTRAINT",
            "FOREIGN",
            "PRIMARY",
            "UNIQUE",
        }:
            continue
        for match in re.finditer(
            rf"\bCOLLATE\s+(?P<collation>{identifier})",
            definition,
            flags=re.IGNORECASE,
        ):
            declarations.append(
                {
                    "column": column,
                    "collation": _unquote_sqlite_identifier(
                        match.group("collation")
                    ).upper(),
                }
            )
    return sorted(
        declarations,
        key=lambda item: (item["column"], item["collation"]),
    )


def _split_table_definitions(sql: str) -> list[str]:
    opening = sql.find("(")
    if opening < 0:
        return []
    definitions: list[str] = []
    start = opening + 1
    depth = 1
    quote: str | None = None
    index = start
    while index < len(sql):
        char = sql[index]
        if quote is not None:
            if quote == "]":
                if char == "]":
                    quote = None
            elif char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif char in {"'", '"', "`"}:
            quote = char
        elif char == "[":
            quote = "]"
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                definitions.append(sql[start:index])
                break
        elif char == "," and depth == 1:
            definitions.append(sql[start:index])
            start = index + 1
        index += 1
    return definitions


def _unquote_sqlite_identifier(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "`"}:
        return value[1:-1].replace(value[0] * 2, value[0])
    if len(value) >= 2 and value[0] == "[" and value[-1] == "]":
        return value[1:-1].replace("]]", "]")
    return value


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )
