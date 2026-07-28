"""Transactional, checksum-backed schema authority for ``courses.db``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from importlib import resources
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any, Iterable

from deeptutor.courses.database_lock import course_database_lock

_MIGRATION_FILE = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")
_CORE_PHASE3A_TABLES = frozenset({"courses", "course_sources"})


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
    conn.execute("PRAGMA foreign_keys = ON")
    if int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
        conn.close()
        raise CourseMigrationError("SQLite foreign-key enforcement is unavailable")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


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
    with lock:
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
                    # The process-local path lock coordinates repository wrappers
                    # here. BEGIN IMMEDIATE is the cross-process authority. State
                    # must be re-read after acquiring it because another process
                    # may have migrated after our initial classification.
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
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
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
