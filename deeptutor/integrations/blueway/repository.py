"""Owner-scoped BlueWay rows colocated with one private ``courses.db``."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
import time
from typing import Any
from uuid import uuid4

from deeptutor.courses.models import Course
from deeptutor.courses.repository import CourseConflictError, CourseRepository


class BlueWayNotFoundError(LookupError):
    pass


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass(frozen=True)
class Connection:
    id: str
    owner_user_id: str
    external_subject: str
    state: str
    scope_version: str
    revision: int
    grant_generation: int
    credential_ref: str | None
    credential_status: str
    created_at: float
    updated_at: float
    connected_at: float | None
    last_sync_at: float | None
    disconnected_at: float | None
    rotation_request_id: str | None = None
    rotation_started_at: float | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Connection":
        return cls(**dict(row))


@dataclass(frozen=True)
class SyncRun:
    id: str
    connection_id: str
    expected_generation: int
    snapshot_id: str | None
    snapshot_sha256: str | None
    state: str
    attempt_count: int
    counts: dict[str, int]
    error_code: str | None
    created_at: float
    updated_at: float
    completed_at: float | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "SyncRun":
        payload = dict(row)
        payload["counts"] = json.loads(payload.pop("counts_json") or "{}")
        return cls(**payload)


class BlueWayRepository:
    """Repository facade that never accepts an owner id from request data."""

    def __init__(self, courses: CourseRepository) -> None:
        self.courses = courses
        self.owner_user_id = courses.owner_user_id
        self._initialize()

    def _initialize(self) -> None:
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS blueway_connections (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    external_subject TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('pending','active','revocation_pending','disconnected','error')),
                    scope_version TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
                    grant_generation INTEGER NOT NULL DEFAULT 1 CHECK (grant_generation >= 1),
                    credential_ref TEXT,
                    credential_status TEXT NOT NULL DEFAULT 'healthy',
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    connected_at REAL, last_sync_at REAL, disconnected_at REAL,
                    rotation_request_id TEXT, rotation_started_at REAL
                );
                DROP INDEX IF EXISTS blueway_one_active_connection;
                CREATE UNIQUE INDEX IF NOT EXISTS blueway_one_live_connection
                    ON blueway_connections(owner_user_id) WHERE state IN ('active', 'revocation_pending');
                CREATE TABLE IF NOT EXISTS blueway_course_maps (
                    connection_id TEXT NOT NULL REFERENCES blueway_connections(id) ON DELETE RESTRICT,
                    external_course_id TEXT NOT NULL,
                    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
                    remote_title TEXT NOT NULL,
                    remote_state TEXT NOT NULL CHECK (remote_state IN ('active','archived')),
                    remote_hash TEXT NOT NULL,
                    first_seen_snapshot_id TEXT NOT NULL, last_seen_snapshot_id TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY (connection_id, external_course_id), UNIQUE (connection_id, course_id)
                );
                CREATE TABLE IF NOT EXISTS blueway_records (
                    connection_id TEXT NOT NULL REFERENCES blueway_connections(id) ON DELETE RESTRICT,
                    record_kind TEXT NOT NULL,
                    external_record_id TEXT NOT NULL,
                    external_course_id TEXT, course_id TEXT REFERENCES courses(id) ON DELETE RESTRICT,
                    state TEXT NOT NULL CHECK (state IN ('current','unlinked','archived')),
                    remote_revision TEXT, content_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL,
                    current_source_id TEXT REFERENCES course_sources(id) ON DELETE RESTRICT,
                    first_seen_snapshot_id TEXT NOT NULL, last_seen_snapshot_id TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY (connection_id, record_kind, external_record_id)
                );
                CREATE TABLE IF NOT EXISTS blueway_sync_runs (
                    id TEXT PRIMARY KEY,
                    connection_id TEXT NOT NULL REFERENCES blueway_connections(id) ON DELETE RESTRICT,
                    expected_generation INTEGER NOT NULL, snapshot_id TEXT, snapshot_sha256 TEXT,
                    state TEXT NOT NULL CHECK (state IN ('queued','fetching','validating','staging','indexing','completed','failed','cancelled')),
                    attempt_count INTEGER NOT NULL DEFAULT 0, counts_json TEXT NOT NULL DEFAULT '{}',
                    error_code TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL, completed_at REAL
                );
                DROP INDEX IF EXISTS blueway_snapshot_replay;
                CREATE UNIQUE INDEX blueway_snapshot_replay
                    ON blueway_sync_runs(connection_id, snapshot_id)
                    WHERE snapshot_id IS NOT NULL AND state = 'completed';
                CREATE INDEX IF NOT EXISTS blueway_runs_connection_updated
                    ON blueway_sync_runs(connection_id, updated_at DESC);
                """
            )
            columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(blueway_connections)")}
            if "rotation_request_id" not in columns:
                conn.execute("ALTER TABLE blueway_connections ADD COLUMN rotation_request_id TEXT")
            if "rotation_started_at" not in columns:
                conn.execute("ALTER TABLE blueway_connections ADD COLUMN rotation_started_at REAL")
            if "credential_status" not in columns:
                conn.execute(
                    """ALTER TABLE blueway_connections
                       ADD COLUMN credential_status TEXT NOT NULL DEFAULT 'healthy'"""
                )

    def create_active_connection(
        self, *, external_subject: str, scope_version: str, connection_id: str | None = None
    ) -> Connection:
        if not external_subject or not scope_version:
            raise ValueError("BlueWay subject and scope version are required")
        now, connection_id = time.time(), connection_id or _id("bwc")
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """INSERT INTO blueway_connections
                       (id, owner_user_id, external_subject, state, scope_version, revision, grant_generation,
                        credential_ref, credential_status, created_at, updated_at, connected_at,
                        last_sync_at, disconnected_at, rotation_request_id, rotation_started_at)
                       VALUES (?, ?, ?, 'active', ?, 1, 1, ?, 'healthy', ?, ?, ?, NULL, NULL, NULL, NULL)""",
                    (connection_id, self.owner_user_id, external_subject, scope_version,
                     f"blueway:{connection_id}", now, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise CourseConflictError("An active BlueWay connection already exists") from exc
            row = conn.execute("SELECT * FROM blueway_connections WHERE id = ?", (connection_id,)).fetchone()
        assert row is not None
        return Connection.from_row(row)

    def prepare_rotation(self, connection_id: str, *, expected_generation: int) -> str:
        """Durably reserve one 60-second rotation id before a fallible refresh."""
        now = time.time()
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            row = conn.execute(
                """SELECT rotation_request_id, rotation_started_at FROM blueway_connections
                   WHERE id = ? AND owner_user_id = ? AND state = 'active'
                     AND credential_status = 'healthy' AND grant_generation = ?""",
                (connection_id, self.owner_user_id, expected_generation),
            ).fetchone()
            if row is None:
                raise CourseConflictError("BlueWay connection is stale or no longer writable")
            current = row["rotation_request_id"]
            started = row["rotation_started_at"]
            if current and started is not None and now - float(started) <= 60.0:
                return str(current)
            request_id = str(uuid4())
            conn.execute("UPDATE blueway_connections SET rotation_request_id = ?, rotation_started_at = ?, updated_at = ? WHERE id = ?", (request_id, now, now, connection_id))
        return request_id

    def clear_rotation(self, connection_id: str, *, expected_generation: int, request_id: str) -> None:
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            result = conn.execute(
                """UPDATE blueway_connections SET rotation_request_id = NULL, rotation_started_at = NULL, updated_at = ?
                   WHERE id = ? AND owner_user_id = ? AND state = 'active'
                     AND credential_status = 'healthy' AND grant_generation = ?
                     AND rotation_request_id = ?""",
                (time.time(), connection_id, self.owner_user_id, expected_generation, request_id),
            )
        if result.rowcount != 1:
            raise CourseConflictError("BlueWay connection is stale or no longer writable")

    def active_connection(self) -> Connection | None:
        with self.courses._connect() as conn:  # noqa: SLF001
            row = conn.execute(
                """SELECT * FROM blueway_connections WHERE owner_user_id = ?
                   AND state = 'active' AND credential_status = 'healthy'""",
                (self.owner_user_id,),
            ).fetchone()
        return Connection.from_row(row) if row else None

    def visible_connection(self) -> Connection | None:
        """Return the active or locally-fenced revocation state for its owner."""
        with self.courses._connect() as conn:  # noqa: SLF001
            row = conn.execute(
                """SELECT * FROM blueway_connections WHERE owner_user_id = ?
                   AND state IN ('active', 'revocation_pending')
                   ORDER BY updated_at DESC LIMIT 1""",
                (self.owner_user_id,),
            ).fetchone()
        return Connection.from_row(row) if row else None

    def get_connection(self, connection_id: str, *, active_only: bool = False) -> Connection:
        sql = "SELECT * FROM blueway_connections WHERE id = ? AND owner_user_id = ?"
        params: list[Any] = [connection_id, self.owner_user_id]
        if active_only:
            sql += " AND state = 'active' AND credential_status = 'healthy'"
        with self.courses._connect() as conn:  # noqa: SLF001
            row = conn.execute(sql, params).fetchone()
        if row is None:
            raise BlueWayNotFoundError("Integration resource not found")
        return Connection.from_row(row)

    def require_credential_recovery(
        self, connection_id: str, *, expected_revision: int | None = None,
    ) -> Connection:
        """Fence an unreadable local credential without changing its remote grant.

        This additive status is deliberately separate from the provider grant
        lifecycle in ``state``.  It invalidates every in-flight generation and
        preserves the connection, credential reference, Courses, records,
        sources, mastery, and history for an owner-approved recovery.
        """
        now = time.time()
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT * FROM blueway_connections
                   WHERE id = ? AND owner_user_id = ?
                     AND state IN ('active', 'revocation_pending')""",
                (connection_id, self.owner_user_id),
            ).fetchone()
            if row is None:
                raise BlueWayNotFoundError("Integration resource not found")
            if (
                expected_revision is not None
                and int(row["revision"]) != expected_revision
            ):
                raise CourseConflictError("BlueWay connection revision is stale")
            if str(row["credential_status"]) == "healthy":
                conn.execute(
                    """UPDATE blueway_connections
                       SET credential_status = 'recovery_required',
                           revision = revision + 1,
                           grant_generation = grant_generation + 1,
                           rotation_request_id = NULL,
                           rotation_started_at = NULL,
                           updated_at = ?
                       WHERE id = ? AND owner_user_id = ?
                         AND credential_status = 'healthy'""",
                    (now, connection_id, self.owner_user_id),
                )
                conn.execute(
                    """UPDATE blueway_sync_runs
                       SET state = 'cancelled',
                           error_code = 'credential_recovery_required',
                           updated_at = ?, completed_at = ?
                       WHERE connection_id = ?
                         AND state IN ('queued','fetching','validating','staging','indexing')""",
                    (now, now, connection_id),
                )
            updated = conn.execute(
                "SELECT * FROM blueway_connections WHERE id = ?",
                (connection_id,),
            ).fetchone()
        assert updated is not None
        return Connection.from_row(updated)

    def complete_credential_recovery(
        self, connection_id: str, *, expected_revision: int,
        expected_generation: int,
    ) -> Connection:
        """Reactivate the same connection after an owner-approved same-subject grant."""
        now = time.time()
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            result = conn.execute(
                """UPDATE blueway_connections
                   SET credential_status = 'healthy',
                       revision = revision + 1,
                       grant_generation = grant_generation + 1,
                       rotation_request_id = NULL,
                       rotation_started_at = NULL,
                       updated_at = ?
                   WHERE id = ? AND owner_user_id = ?
                     AND state IN ('active', 'revocation_pending')
                     AND credential_status = 'recovery_required'
                     AND revision = ? AND grant_generation = ?""",
                (
                    now, connection_id, self.owner_user_id,
                    expected_revision, expected_generation,
                ),
            )
            if result.rowcount != 1:
                raise CourseConflictError(
                    "BlueWay credential recovery is stale"
                )
            row = conn.execute(
                "SELECT * FROM blueway_connections WHERE id = ?",
                (connection_id,),
            ).fetchone()
        assert row is not None
        return Connection.from_row(row)

    def begin_disconnect(self, connection_id: str, *, expected_revision: int) -> Connection:
        """Fence locally before a fallible remote revoke operation."""
        now = time.time()
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            result = conn.execute(
                """UPDATE blueway_connections
                   SET state = 'revocation_pending', revision = revision + 1,
                       grant_generation = grant_generation + 1, updated_at = ?
                   WHERE id = ? AND owner_user_id = ? AND state = 'active'
                     AND credential_status = 'healthy' AND revision = ?""",
                (now, connection_id, self.owner_user_id, expected_revision),
            )
            if result.rowcount != 1:
                self.get_connection(connection_id, active_only=True)
                raise CourseConflictError("BlueWay connection revision is stale")
            conn.execute(
                """UPDATE blueway_sync_runs SET state = 'cancelled', updated_at = ?, completed_at = ?
                   WHERE connection_id = ? AND state IN ('queued','fetching','validating','staging','indexing')""",
                (now, now, connection_id),
            )
            row = conn.execute("SELECT * FROM blueway_connections WHERE id = ?", (connection_id,)).fetchone()
        assert row is not None
        return Connection.from_row(row)

    def complete_disconnect(self, connection_id: str, *, expected_revision: int) -> Connection:
        now = time.time()
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            result = conn.execute(
                """UPDATE blueway_connections
                   SET state = 'disconnected', credential_ref = NULL, updated_at = ?, disconnected_at = ?
                   WHERE id = ? AND owner_user_id = ? AND state = 'revocation_pending'
                     AND credential_status = 'healthy' AND revision = ?""",
                (now, now, connection_id, self.owner_user_id, expected_revision),
            )
            if result.rowcount != 1:
                raise BlueWayNotFoundError("Integration resource not found")
            row = conn.execute("SELECT * FROM blueway_connections WHERE id = ?", (connection_id,)).fetchone()
        assert row is not None
        return Connection.from_row(row)

    def pending_connections(self) -> list[Connection]:
        with self.courses._connect() as conn:  # noqa: SLF001
            rows = conn.execute(
                """SELECT * FROM blueway_connections WHERE owner_user_id = ?
                   AND state = 'revocation_pending'
                   AND credential_status = 'healthy'""",
                (self.owner_user_id,),
            ).fetchall()
        return [Connection.from_row(row) for row in rows]

    def credential_connection_ids(self) -> set[str]:
        with self.courses._connect() as conn:  # noqa: SLF001
            rows = conn.execute(
                """SELECT id FROM blueway_connections WHERE owner_user_id = ?
                   AND state IN ('active', 'revocation_pending') AND credential_ref IS NOT NULL""",
                (self.owner_user_id,),
            ).fetchall()
        return {str(row["id"]) for row in rows}

    def require_repair(self, connection_id: str, *, expected_generation: int) -> None:
        """Terminalize a permanently rejected provider grant under its exact fence."""
        now = time.time()
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute(
                """UPDATE blueway_connections SET state = 'error', credential_ref = NULL,
                   grant_generation = grant_generation + 1, revision = revision + 1, updated_at = ?
                   WHERE id = ? AND owner_user_id = ? AND state = 'active'
                     AND credential_status = 'healthy' AND grant_generation = ?""",
                (now, connection_id, self.owner_user_id, expected_generation),
            )
            if changed.rowcount != 1:
                raise CourseConflictError("BlueWay connection is stale or no longer writable")
            conn.execute(
                """UPDATE blueway_sync_runs SET state = 'cancelled', error_code = 'provider_authority_lost',
                   updated_at = ?, completed_at = ? WHERE connection_id = ?
                   AND state IN ('queued','fetching','validating','staging','indexing')""",
                (now, now, connection_id),
            )

    def queue_sync(self, connection_id: str) -> SyncRun:
        now, run_id = time.time(), _id("bwr")
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            conn.execute("BEGIN IMMEDIATE")
            connection = conn.execute(
                """SELECT id, grant_generation FROM blueway_connections
                   WHERE id = ? AND owner_user_id = ? AND state = 'active'
                     AND credential_status = 'healthy'""",
                (connection_id, self.owner_user_id),
            ).fetchone()
            if connection is None:
                raise BlueWayNotFoundError("Integration resource not found")
            existing = conn.execute(
                """SELECT * FROM blueway_sync_runs WHERE connection_id = ?
                   AND state IN ('queued','fetching','validating','staging','indexing')""",
                (connection["id"],),
            ).fetchone()
            if existing:
                return SyncRun.from_row(existing)
            conn.execute(
                """INSERT INTO blueway_sync_runs
                   (id, connection_id, expected_generation, snapshot_id, snapshot_sha256, state,
                    attempt_count, counts_json, error_code, created_at, updated_at, completed_at)
                   VALUES (?, ?, ?, NULL, NULL, 'queued', 0, '{}', NULL, ?, ?, NULL)""",
                (run_id, connection["id"], connection["grant_generation"], now, now),
            )
            row = conn.execute("SELECT * FROM blueway_sync_runs WHERE id = ?", (run_id,)).fetchone()
        assert row is not None
        return SyncRun.from_row(row)

    def get_run(self, run_id: str) -> SyncRun:
        with self.courses._connect() as conn:  # noqa: SLF001
            row = conn.execute(
                """SELECT r.* FROM blueway_sync_runs r JOIN blueway_connections c ON c.id = r.connection_id
                   WHERE r.id = ? AND c.owner_user_id = ?""",
                (run_id, self.owner_user_id),
            ).fetchone()
        if row is None:
            raise BlueWayNotFoundError("Integration resource not found")
        return SyncRun.from_row(row)

    def active_run(self, connection_id: str) -> SyncRun | None:
        self.get_connection(connection_id)
        with self.courses._connect() as conn:  # noqa: SLF001
            row = conn.execute(
                """SELECT * FROM blueway_sync_runs WHERE connection_id = ?
                   ORDER BY CASE WHEN state IN ('queued','fetching','validating','staging','indexing') THEN 0 ELSE 1 END,
                            updated_at DESC LIMIT 1""",
                (connection_id,),
            ).fetchone()
        return SyncRun.from_row(row) if row else None

    def list_unlinked(self, connection_id: str) -> list[dict[str, Any]]:
        self.get_connection(connection_id)
        with self.courses._connect() as conn:  # noqa: SLF001
            rows = conn.execute(
                """SELECT record_kind, external_record_id
                   FROM blueway_records WHERE connection_id = ? AND state = 'unlinked'
                   ORDER BY record_kind, external_record_id""",
                (connection_id,),
            ).fetchall()
        return [{"record_kind": row["record_kind"], "external_record_id": row["external_record_id"]} for row in rows]

    def bundle_records(self, connection_id: str) -> list[tuple[str, str, list[dict[str, Any]]]]:
        """Read only owner-mapped current records; unlinked data is never rendered."""
        self.get_connection(connection_id, active_only=True)
        with self.courses._connect() as conn:  # noqa: SLF001
            rows = conn.execute(
                """SELECT r.course_id, m.external_course_id, r.record_kind, r.external_record_id, r.payload_json
                   FROM blueway_records r JOIN courses c ON c.id = r.course_id
                   JOIN blueway_course_maps m ON m.connection_id = r.connection_id AND m.course_id = r.course_id
                   WHERE r.connection_id = ? AND r.state = 'current' AND c.owner_user_id = ?
                     AND c.state = 'active' ORDER BY r.course_id, r.record_kind, r.external_record_id""",
                (connection_id, self.owner_user_id),
            ).fetchall()
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            record = json.loads(row["payload_json"])
            # Preserve the validated receipt, but never grant an empty capture
            # retrieval authority merely because it belongs to a mapped Course.
            if row["record_kind"] == "transcripts" and not any(
                isinstance(segment, dict) and str(segment.get("text") or "").strip()
                for segment in record.get("segments", [])
            ):
                continue
            grouped.setdefault((str(row["course_id"]), str(row["external_course_id"])), []).append(
                {"kind": row["record_kind"], "record": record}
            )
        return [(course_id, external_course_id, records) for (course_id, external_course_id), records in sorted(grouped.items())]

    def finalize_bundle_source(
        self, connection_id: str, *, course_id: str, source_id: str, operation_id: str,
        expected_source_revision: int, expected_generation: int,
    ) -> None:
        """Grant ready state only under the same BlueWay authority fence.

        CourseRepository's public transition intentionally knows nothing about
        integrations.  Generated BlueWay sources therefore use this narrow
        transaction so a disconnect/revocation cannot win between indexing and
        the visibility grant.
        """
        now = time.time()
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            conn.execute("BEGIN IMMEDIATE")
            updated = conn.execute(
                """UPDATE course_sources SET state = 'ready', revision = revision + 1, updated_at = ?
                   WHERE id = ? AND course_id = ? AND state = 'processing' AND operation_id = ?
                     AND revision = ? AND EXISTS (
                       SELECT 1 FROM courses WHERE courses.id = course_sources.course_id
                       AND courses.owner_user_id = ? AND courses.state = 'active'
                     ) AND EXISTS (
                       SELECT 1 FROM blueway_connections WHERE id = ? AND owner_user_id = ?
                       AND state = 'active' AND credential_status = 'healthy'
                       AND grant_generation = ?
                     )""",
                (now, source_id, course_id, operation_id, expected_source_revision,
                 self.owner_user_id, connection_id, self.owner_user_id, expected_generation),
            )
        if updated.rowcount != 1:
            raise CourseConflictError("BlueWay generated source is stale or no longer writable")

    def commit_bundle_sources(
        self, connection_id: str, *, expected_generation: int, items: list[dict[str, Any]],
    ) -> None:
        """Atomically make a staged set of BlueWay bundle sources visible."""
        now = time.time()
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            conn.execute("BEGIN IMMEDIATE")
            live = conn.execute(
                """SELECT 1 FROM blueway_connections WHERE id = ? AND owner_user_id = ?
                   AND state = 'active' AND credential_status = 'healthy'
                   AND grant_generation = ?""",
                (connection_id, self.owner_user_id, expected_generation),
            ).fetchone()
            if live is None:
                raise CourseConflictError("BlueWay connection is stale or no longer writable")
            for item in items:
                if item.get("already_ready"):
                    ready = conn.execute(
                        """SELECT 1 FROM course_sources WHERE id = ? AND course_id = ? AND state = 'ready'
                           AND operation_id = ? AND revision = ? AND EXISTS (
                             SELECT 1 FROM courses WHERE id = course_sources.course_id
                             AND owner_user_id = ? AND state = 'active'
                           )""",
                        (item["source_id"], item["course_id"], item["operation_id"], item["source_revision"], self.owner_user_id),
                    ).fetchone()
                    if ready is None:
                        raise CourseConflictError("BlueWay generated source is stale or no longer writable")
                else:
                    changed = conn.execute(
                        """UPDATE course_sources SET state = 'ready', revision = revision + 1, updated_at = ?
                           WHERE id = ? AND course_id = ? AND state = 'processing' AND operation_id = ? AND revision = ?
                             AND EXISTS (SELECT 1 FROM courses WHERE id = course_sources.course_id
                               AND owner_user_id = ? AND state = 'active')""",
                        (now, item["source_id"], item["course_id"], item["operation_id"], item["source_revision"], self.owner_user_id),
                    )
                    if changed.rowcount != 1:
                        raise CourseConflictError("BlueWay generated source is stale or no longer writable")
            for item in items:
                conn.execute(
                    """UPDATE blueway_records SET current_source_id = ?, updated_at = ?
                       WHERE connection_id = ? AND course_id = ? AND state = 'current'""",
                    (item["source_id"], now, connection_id, item["course_id"]),
                )
                previous = item.get("previous_source_id")
                if previous:
                    conn.execute(
                        """UPDATE course_sources SET state = 'archived', revision = revision + 1, updated_at = ?
                           WHERE id = ? AND state = 'ready'""",
                        (now, previous),
                    )

    def abandon_bundle_source(self, *, course_id: str, source_id: str, operation_id: str, expected_revision: int) -> None:
        """Fail a generated staging row and release only its retry key together."""
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            result = conn.execute(
                """UPDATE course_sources SET state = 'failed', idempotency_key = NULL,
                   revision = revision + 1, updated_at = ?
                   WHERE id = ? AND course_id = ? AND state = 'processing' AND operation_id = ?
                     AND revision = ? AND EXISTS (SELECT 1 FROM courses WHERE id = course_sources.course_id
                       AND owner_user_id = ?)""",
                (time.time(), source_id, course_id, operation_id, expected_revision, self.owner_user_id),
            )
        if result.rowcount != 1:
            raise CourseConflictError("BlueWay generated source is stale or no longer writable")

    def set_bundle_source(self, connection_id: str, *, course_id: str, source_id: str, expected_generation: int) -> None:
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            conn.execute("BEGIN IMMEDIATE")
            live = conn.execute(
                """SELECT 1 FROM blueway_connections WHERE id = ? AND owner_user_id = ?
                   AND state = 'active' AND credential_status = 'healthy'
                   AND grant_generation = ?""",
                (connection_id, self.owner_user_id, expected_generation),
            ).fetchone()
            course = conn.execute("SELECT 1 FROM courses WHERE id = ? AND owner_user_id = ? AND state = 'active'", (course_id, self.owner_user_id)).fetchone()
            if live is None or course is None:
                raise CourseConflictError("BlueWay connection is stale or no longer writable")
            conn.execute(
                """UPDATE blueway_records SET current_source_id = ?, updated_at = ?
                   WHERE connection_id = ? AND course_id = ? AND state = 'current'""",
                (source_id, time.time(), connection_id, course_id),
            )

    def archive_absent_records(self, connection_id: str, *, snapshot_id: str) -> int:
        """Apply complete-snapshot removals without deleting data or provenance.

        Any associated ready CourseSource is archived, which removes it from
        current retrieval while preserving its immutable manifest and bytes.
        Callers must invoke this only after complete-snapshot/hash validation.
        """
        self.get_connection(connection_id, active_only=True)
        now = time.time()
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                """SELECT grant_generation FROM blueway_connections
                   WHERE id = ? AND owner_user_id = ? AND state = 'active'
                     AND credential_status = 'healthy'""",
                (connection_id, self.owner_user_id),
            ).fetchone()
            if current is None:
                raise CourseConflictError("BlueWay connection is stale or no longer writable")
            rows = conn.execute(
                """SELECT current_source_id FROM blueway_records
                   WHERE connection_id = ? AND state = 'current' AND last_seen_snapshot_id <> ?""",
                (connection_id, snapshot_id),
            ).fetchall()
            conn.execute(
                """UPDATE blueway_records SET state = 'archived', updated_at = ?
                   WHERE connection_id = ? AND state = 'current' AND last_seen_snapshot_id <> ?""",
                (now, connection_id, snapshot_id),
            )
            source_ids = [str(row["current_source_id"]) for row in rows if row["current_source_id"]]
            if source_ids:
                marks = ",".join("?" for _ in source_ids)
                conn.execute(
                    f"""UPDATE course_sources SET state = 'archived', revision = revision + 1, updated_at = ?
                        WHERE id IN ({marks}) AND state = 'ready'""",
                    [now, *source_ids],
                )
        return len(rows)

    def create_course_map(
        self, *, connection_id: str, external_course_id: str, remote_title: str,
        remote_state: str, remote_hash: str, snapshot_id: str, expected_generation: int,
    ) -> Course:
        """Create one opaque Course and its exact external-ID map in one transaction.

        The remote title is display data only: replay never changes the learner's
        Course title, and no lookup is performed by title.
        """
        if remote_state not in {"active", "archived"}:
            raise ValueError("Invalid remote course state")
        if not external_course_id or not snapshot_id or not remote_hash:
            raise ValueError("Course map identity fields are required")
        if expected_generation < 1:
            raise ValueError("Expected connection generation is required")
        now, course_id = time.time(), _id("crs")
        title = CourseRepository._clean_title(remote_title)  # noqa: SLF001
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            conn.execute("BEGIN IMMEDIATE")
            # This is the authority fence: a disconnect can win between fetch
            # and this transaction, but cannot permit a late Course/map write.
            connection = conn.execute(
                """SELECT id FROM blueway_connections
                   WHERE id = ? AND owner_user_id = ? AND state = 'active'
                     AND credential_status = 'healthy'
                     AND grant_generation = ?""",
                (connection_id, self.owner_user_id, expected_generation),
            ).fetchone()
            if connection is None:
                raise CourseConflictError("BlueWay connection is stale or no longer writable")
            existing = conn.execute(
                "SELECT course_id FROM blueway_course_maps WHERE connection_id = ? AND external_course_id = ?",
                (connection_id, external_course_id),
            ).fetchone()
            if existing:
                row = conn.execute("SELECT * FROM courses WHERE id = ?", (existing["course_id"],)).fetchone()
                assert row is not None
                return self.courses._course_from_row(row)  # noqa: SLF001
            conn.execute(
                """INSERT INTO courses (id, owner_user_id, title, state, revision, write_epoch,
                    managed_kb_ref, created_at, updated_at, archived_at)
                   VALUES (?, ?, ?, 'active', 1, 1, NULL, ?, ?, NULL)""",
                (course_id, self.owner_user_id, title, now, now),
            )
            conn.execute(
                """INSERT INTO blueway_course_maps (connection_id, external_course_id, course_id, remote_title,
                    remote_state, remote_hash, first_seen_snapshot_id, last_seen_snapshot_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (connection_id, external_course_id, course_id, remote_title, remote_state, remote_hash,
                 snapshot_id, snapshot_id, now, now),
            )
            row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        assert row is not None
        return self.courses._course_from_row(row)  # noqa: SLF001

    def transition_run(self, run_id: str, *, state: str) -> SyncRun:
        """Advance a durable run only while its exact connection fence holds."""
        if state not in {"fetching", "validating", "staging", "indexing"}:
            raise ValueError("Invalid BlueWay sync state")
        now = time.time()
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            row = conn.execute(
                """SELECT r.* FROM blueway_sync_runs r JOIN blueway_connections c ON c.id = r.connection_id
                   WHERE r.id = ? AND c.owner_user_id = ? AND c.state = 'active'
                     AND c.credential_status = 'healthy'
                     AND c.grant_generation = r.expected_generation
                     AND r.state IN ('queued','fetching','validating','staging','indexing')""",
                (run_id, self.owner_user_id),
            ).fetchone()
            if row is None:
                raise CourseConflictError("BlueWay sync run is stale or no longer writable")
            conn.execute(
                """UPDATE blueway_sync_runs SET state = ?, attempt_count = attempt_count + ?, updated_at = ?
                   WHERE id = ?""",
                (state, 1 if state == "fetching" else 0, now, run_id),
            )
            updated = conn.execute("SELECT * FROM blueway_sync_runs WHERE id = ?", (run_id,)).fetchone()
        assert updated is not None
        return SyncRun.from_row(updated)

    def fail_run(self, run_id: str, *, error_code: str) -> SyncRun:
        now = time.time()
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            conn.execute(
                """UPDATE blueway_sync_runs SET state = 'failed', error_code = ?, updated_at = ?, completed_at = ?
                   WHERE id = ? AND state NOT IN ('completed','cancelled')""",
                (error_code[:80], now, now, run_id),
            )
            row = conn.execute("SELECT * FROM blueway_sync_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise BlueWayNotFoundError("Integration resource not found")
        return SyncRun.from_row(row)

    def apply_verified_snapshot(self, run_id: str, snapshot: dict[str, Any]) -> SyncRun:
        """Atomically mirror one verified page and only archive on a complete receipt."""
        snapshot_id = str(snapshot["snapshot_id"])
        snapshot_hash = str(snapshot["payload_sha256"])
        now = time.time()
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            conn.execute("BEGIN IMMEDIATE")
            run = conn.execute(
                """SELECT r.*, c.id AS checked_connection_id, c.external_subject FROM blueway_sync_runs r
                   JOIN blueway_connections c ON c.id = r.connection_id
                   WHERE r.id = ? AND c.owner_user_id = ? AND c.state = 'active'
                     AND c.credential_status = 'healthy'
                     AND c.grant_generation = r.expected_generation
                     AND r.state IN ('validating','staging')""",
                (run_id, self.owner_user_id),
            ).fetchone()
            if run is None:
                raise CourseConflictError("BlueWay sync run is stale or no longer writable")
            connection_id = str(run["connection_id"])
            replay = conn.execute(
                """SELECT * FROM blueway_sync_runs WHERE connection_id = ? AND snapshot_id = ?
                   AND state = 'completed'""",
                (connection_id, snapshot_id),
            ).fetchone()
            if replay is not None:
                if str(replay["snapshot_sha256"] or "") != snapshot_hash:
                    raise CourseConflictError("BlueWay snapshot id was replayed with different provenance")
                # A replay is a distinct run receipt.  Do not reuse the
                # previous row's unique completed snapshot identity.
                conn.execute(
                    "UPDATE blueway_sync_runs SET state = 'completed', snapshot_sha256 = ?, counts_json = ?, error_code = NULL, updated_at = ?, completed_at = ? WHERE id = ?",
                    (snapshot_hash, replay["counts_json"], now, now, run_id),
                )
                updated = conn.execute("SELECT * FROM blueway_sync_runs WHERE id = ?", (run_id,)).fetchone()
                assert updated is not None
                return SyncRun.from_row(updated)
            counts: dict[str, int] = {}
            course_ids: dict[str, str] = {}
            unavailable = {str(item["dataset"]) for item in snapshot.get("unavailable", [])}
            for remote in snapshot["datasets"]["courses"]:
                external_id, title = str(remote["id"]), str(remote["title"])
                mapped = conn.execute(
                    "SELECT course_id FROM blueway_course_maps WHERE connection_id = ? AND external_course_id = ?",
                    (connection_id, external_id),
                ).fetchone()
                if mapped is None:
                    # A safely disconnected reconnect retains the learner's
                    # Course only for the exact upstream subject and opaque
                    # course id.  Title similarity is never identity.
                    rebound = conn.execute(
                        """SELECT m.course_id FROM blueway_course_maps m
                           JOIN blueway_connections prior ON prior.id = m.connection_id
                           JOIN courses course ON course.id = m.course_id
                           WHERE prior.owner_user_id = ? AND prior.external_subject = ?
                             AND m.external_course_id = ? AND course.owner_user_id = ?
                           ORDER BY m.updated_at DESC LIMIT 1""",
                        (self.owner_user_id, run["external_subject"], external_id, self.owner_user_id),
                    ).fetchone()
                    if rebound is None:
                        local_id = _id("crs")
                        conn.execute(
                            """INSERT INTO courses (id, owner_user_id, title, state, revision, write_epoch, managed_kb_ref, created_at, updated_at, archived_at)
                               VALUES (?, ?, ?, 'active', 1, 1, NULL, ?, ?, NULL)""",
                            (local_id, self.owner_user_id, CourseRepository._clean_title(title), now, now),  # noqa: SLF001
                        )
                    else:
                        local_id = str(rebound["course_id"])
                    conn.execute(
                        """INSERT INTO blueway_course_maps (connection_id, external_course_id, course_id, remote_title, remote_state, remote_hash, first_seen_snapshot_id, last_seen_snapshot_id, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (connection_id, external_id, local_id, title, "active", remote["content_sha256"], snapshot_id, snapshot_id, now, now),
                    )
                else:
                    local_id = str(mapped["course_id"])
                    conn.execute(
                        """UPDATE blueway_course_maps SET remote_title = ?, remote_state = ?, remote_hash = ?, last_seen_snapshot_id = ?, updated_at = ?
                           WHERE connection_id = ? AND external_course_id = ?""",
                        (title, "active", remote["content_sha256"], snapshot_id, now, connection_id, external_id),
                    )
                course_ids[external_id] = local_id
            if "courses" in unavailable:
                # The course list is non-authoritative for this receipt, but
                # available course-linked records must retain their exact prior
                # binding instead of being converted to unlinked rows.
                course_ids = {
                    str(row["external_course_id"]): str(row["course_id"])
                    for row in conn.execute(
                        """SELECT external_course_id, course_id FROM blueway_course_maps
                           WHERE connection_id = ? AND remote_state = 'active'""",
                        (connection_id,),
                    )
                }
            counts["courses"] = len(course_ids)
            if snapshot["complete"] and "courses" not in unavailable:
                marks = ",".join("?" for _ in course_ids)
                unseen = conn.execute(
                    f"""SELECT course_id FROM blueway_course_maps WHERE connection_id = ?
                       AND remote_state = 'active' AND external_course_id NOT IN ({marks or "''"})""",
                    [connection_id, *course_ids],
                ).fetchall()
                if unseen:
                    local_ids = [str(row["course_id"]) for row in unseen]
                    local_marks = ",".join("?" for _ in local_ids)
                    conn.execute(
                        f"UPDATE blueway_course_maps SET remote_state = 'archived', updated_at = ? WHERE connection_id = ? AND course_id IN ({local_marks})",
                        [now, connection_id, *local_ids],
                    )
                    conn.execute(
                        f"""UPDATE course_sources SET state = 'archived', revision = revision + 1, updated_at = ?
                           WHERE course_id IN ({local_marks}) AND state = 'ready' AND id IN (
                             SELECT current_source_id FROM blueway_records WHERE connection_id = ? AND course_id IN ({local_marks})
                           )""",
                        [now, *local_ids, connection_id, *local_ids],
                    )
            explicitly_archived_source_ids: list[str] = []
            for kind, records in snapshot["datasets"].items():
                if kind == "courses":
                    continue
                counts[kind] = len(records)
                for remote in records:
                    prior = conn.execute(
                        """SELECT state, current_source_id FROM blueway_records
                           WHERE connection_id = ? AND record_kind = ? AND external_record_id = ?""",
                        (connection_id, kind, remote["id"]),
                    ).fetchone()
                    external_course_id = remote.get("course_id")
                    local_course_id = course_ids.get(str(external_course_id)) if external_course_id else None
                    if local_course_id is not None:
                        course_row = conn.execute("SELECT state FROM courses WHERE id = ? AND owner_user_id = ?", (local_course_id, self.owner_user_id)).fetchone()
                        if course_row is None or str(course_row["state"]) != "active":
                            # A learner's archived Course never becomes writable through an import.
                            local_course_id = None
                    state = "unlinked" if local_course_id is None else str(remote["state"])
                    payload = json.dumps(remote, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    conn.execute(
                        """INSERT INTO blueway_records (connection_id, record_kind, external_record_id, external_course_id, course_id, state, remote_revision, content_sha256, payload_json, current_source_id, first_seen_snapshot_id, last_seen_snapshot_id, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                           ON CONFLICT(connection_id, record_kind, external_record_id) DO UPDATE SET
                             external_course_id=excluded.external_course_id, course_id=excluded.course_id, state=excluded.state,
                             remote_revision=excluded.remote_revision, content_sha256=excluded.content_sha256,
                             payload_json=excluded.payload_json, last_seen_snapshot_id=excluded.last_seen_snapshot_id, updated_at=excluded.updated_at""",
                        (connection_id, kind, remote["id"], external_course_id, local_course_id, state, remote["revision"], remote["content_sha256"], payload, snapshot_id, snapshot_id, now, now),
                    )
                    if state == "archived" and prior is not None and prior["state"] == "current" and prior["current_source_id"]:
                        explicitly_archived_source_ids.append(str(prior["current_source_id"]))
            if explicitly_archived_source_ids:
                marks = ",".join("?" for _ in explicitly_archived_source_ids)
                conn.execute(
                    f"UPDATE course_sources SET state = 'archived', revision = revision + 1, updated_at = ? WHERE id IN ({marks}) AND state = 'ready'",
                    [now, *explicitly_archived_source_ids],
                )
            if snapshot["complete"]:
                archive_kinds = [kind for kind in snapshot["datasets"] if kind not in unavailable and kind != "courses"]
                if not archive_kinds:
                    archive_kinds = []
                marks = ",".join("?" for _ in archive_kinds)
                extra = f" AND record_kind IN ({marks})" if archive_kinds else " AND 1 = 0"
                absent = conn.execute(
                    f"""SELECT current_source_id FROM blueway_records WHERE connection_id = ? AND state = 'current'
                       AND last_seen_snapshot_id <> ?{extra}""",
                    [connection_id, snapshot_id, *archive_kinds],
                ).fetchall()
                conn.execute(
                    f"""UPDATE blueway_records SET state = 'archived', updated_at = ?
                       WHERE connection_id = ? AND state = 'current' AND last_seen_snapshot_id <> ?{extra}""",
                    [now, connection_id, snapshot_id, *archive_kinds],
                )
                source_ids = [str(item["current_source_id"]) for item in absent if item["current_source_id"]]
                if source_ids:
                    marks = ",".join("?" for _ in source_ids)
                    conn.execute(f"UPDATE course_sources SET state = 'archived', revision = revision + 1, updated_at = ? WHERE id IN ({marks}) AND state = 'ready'", [now, *source_ids])
            conn.execute(
                """UPDATE blueway_sync_runs SET state = 'indexing', snapshot_id = ?, snapshot_sha256 = ?,
                   counts_json = ?, error_code = NULL, updated_at = ?, completed_at = NULL WHERE id = ?""",
                (snapshot_id, snapshot_hash, json.dumps(counts, sort_keys=True), now, run_id),
            )
            updated = conn.execute("SELECT * FROM blueway_sync_runs WHERE id = ?", (run_id,)).fetchone()
        assert updated is not None
        return SyncRun.from_row(updated)

    def complete_materialization(self, run_id: str) -> SyncRun:
        """Finish a run only after every generated Course bundle is ready."""
        now = time.time()
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT r.* FROM blueway_sync_runs r JOIN blueway_connections c ON c.id = r.connection_id
                   WHERE r.id = ? AND c.owner_user_id = ? AND c.state = 'active'
                     AND c.credential_status = 'healthy'
                     AND c.grant_generation = r.expected_generation AND r.state = 'indexing'""",
                (run_id, self.owner_user_id),
            ).fetchone()
            if row is None:
                raise CourseConflictError("BlueWay sync run is stale or no longer writable")
            conn.execute(
                "UPDATE blueway_sync_runs SET state = 'completed', updated_at = ?, completed_at = ? WHERE id = ?",
                (now, now, run_id),
            )
            conn.execute(
                "UPDATE blueway_connections SET last_sync_at = ?, updated_at = ? WHERE id = ?",
                (now, now, row["connection_id"]),
            )
            updated = conn.execute("SELECT * FROM blueway_sync_runs WHERE id = ?", (run_id,)).fetchone()
        assert updated is not None
        return SyncRun.from_row(updated)

    def reconcile_interrupted_runs(self) -> int:
        """Restart policy: queued is safe; unfinished remote work is failed for explicit retry."""
        now = time.time()
        with self.courses._write_lock, self.courses._connect() as conn:  # noqa: SLF001
            result = conn.execute(
                """UPDATE blueway_sync_runs SET state = 'failed', error_code = 'interrupted_restart', updated_at = ?, completed_at = ?
                   WHERE state IN ('fetching','validating','staging','indexing')""",
                (now, now),
            )
        return result.rowcount
