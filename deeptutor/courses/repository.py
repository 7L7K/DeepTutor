"""Transactional per-user SQLite repository for private courses."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator
from uuid import uuid4

from .database_lock import course_database_lock
from .migrations import CourseMigrationError, ensure_course_schema
from .migrations.runner import open_course_connection
from .models import Course, CourseSource


class CourseNotFoundError(LookupError):
    pass


class CourseConflictError(RuntimeError):
    pass


def _course_id() -> str:
    return f"crs_{uuid4().hex}"


def _source_id() -> str:
    return f"src_{uuid4().hex}"


def _operation_id() -> str:
    return f"op_{uuid4().hex}"


class CourseRepository:
    """Own one user's Course aggregate database.

    The repository is intentionally per-user even though rows also carry the
    immutable owner id. This gives physical isolation and a checked logical
    ownership invariant without coupling Course lifetime to chat storage.
    """

    def __init__(self, db_path: Path, owner_user_id: str) -> None:
        if not owner_user_id:
            raise ValueError("owner_user_id is required")
        self.db_path = Path(db_path).resolve()
        self.owner_user_id = owner_user_id
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = course_database_lock(self.db_path)
        self._initialize()
        self._restrict_database_permissions()

    def _restrict_database_permissions(self) -> None:
        """Keep Course metadata private even under a permissive process umask."""
        for path in (
            self.db_path,
            Path(f"{self.db_path}-wal"),
            Path(f"{self.db_path}-shm"),
        ):
            if not path.exists():
                continue
            try:
                path.chmod(0o600)
            except OSError as exc:
                raise RuntimeError(
                    f"Could not enforce private Course database permissions for {path}"
                ) from exc

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = open_course_connection(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        self.ensure_schema()

    def ensure_schema(self) -> None:
        """Validate or migrate this private database through the sole DDL authority."""

        try:
            ensure_course_schema(self.db_path, write_lock=self._write_lock)
        except CourseMigrationError as exc:
            raise RuntimeError(f"Could not initialize private Course database: {exc}") from exc

    @staticmethod
    def _clean_title(title: str) -> str:
        cleaned = " ".join(str(title or "").split())
        if not cleaned:
            raise ValueError("Course title is required")
        if len(cleaned) > 160:
            raise ValueError("Course title must be 160 characters or fewer")
        return cleaned

    @staticmethod
    def _clean_label(value: str, field: str, max_length: int = 160) -> str:
        cleaned = " ".join(str(value or "").split())
        if not cleaned:
            raise ValueError(f"{field} is required")
        if len(cleaned) > max_length:
            raise ValueError(f"{field} must be {max_length} characters or fewer")
        return cleaned

    def _course_from_row(self, row: sqlite3.Row) -> Course:
        course = Course.model_validate(dict(row))
        if course.owner_user_id != self.owner_user_id:
            raise CourseNotFoundError("Course not found")
        return course

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> CourseSource:
        payload = dict(row)
        payload["manifest"] = json.loads(payload.pop("manifest_json") or "[]")
        return CourseSource.model_validate(payload)

    def create_course(self, title: str) -> Course:
        now = time.time()
        cid = _course_id()
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO courses
                   (id, owner_user_id, title, state, revision, write_epoch,
                    managed_kb_ref, created_at, updated_at, archived_at)
                   VALUES (?, ?, ?, 'active', 1, 1, NULL, ?, ?, NULL)""",
                (cid, self.owner_user_id, self._clean_title(title), now, now),
            )
            row = conn.execute("SELECT * FROM courses WHERE id = ?", (cid,)).fetchone()
        assert row is not None
        return self._course_from_row(row)

    def list_courses(self, *, include_archived: bool = True) -> list[Course]:
        sql = "SELECT * FROM courses WHERE owner_user_id = ?"
        params: list[Any] = [self.owner_user_id]
        if not include_archived:
            sql += " AND state = 'active'"
        sql += " ORDER BY updated_at DESC, id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._course_from_row(row) for row in rows]

    def get_course(self, course_id: str) -> Course:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM courses WHERE id = ? AND owner_user_id = ?",
                (course_id, self.owner_user_id),
            ).fetchone()
        if row is None:
            raise CourseNotFoundError("Course not found")
        return self._course_from_row(row)

    def update_course_title(self, course_id: str, title: str, expected_revision: int) -> Course:
        now = time.time()
        with self._write_lock, self._connect() as conn:
            result = conn.execute(
                """UPDATE courses
                   SET title = ?, revision = revision + 1, updated_at = ?
                   WHERE id = ? AND owner_user_id = ? AND revision = ?
                     AND state = 'active'""",
                (
                    self._clean_title(title),
                    now,
                    course_id,
                    self.owner_user_id,
                    expected_revision,
                ),
            )
            if result.rowcount != 1:
                self._raise_missing_or_stale(conn, course_id, expected_state="active")
            row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        assert row is not None
        return self._course_from_row(row)

    def _raise_missing_or_stale(
        self,
        conn: sqlite3.Connection,
        course_id: str,
        *,
        expected_state: str | None = None,
    ) -> None:
        existing = conn.execute(
            "SELECT state FROM courses WHERE id = ? AND owner_user_id = ?",
            (course_id, self.owner_user_id),
        ).fetchone()
        if existing is None:
            raise CourseNotFoundError("Course not found")
        if expected_state and str(existing["state"]) != expected_state:
            raise CourseConflictError(f"Course is {existing['state']}")
        raise CourseConflictError("Course revision is stale")

    def archive_course(self, course_id: str, expected_revision: int) -> Course:
        if self.has_processing_sources(course_id):
            raise CourseConflictError("Course has an active source operation")
        now = time.time()
        with self._write_lock, self._connect() as conn:
            result = conn.execute(
                """UPDATE courses
                   SET state = 'archived', revision = revision + 1,
                       write_epoch = write_epoch + 1, archived_at = ?, updated_at = ?
                   WHERE id = ? AND owner_user_id = ? AND revision = ? AND state = 'active'
                     AND NOT EXISTS (
                       SELECT 1 FROM course_sources
                       WHERE course_sources.course_id = courses.id
                         AND course_sources.state = 'processing'
                     )""",
                (now, now, course_id, self.owner_user_id, expected_revision),
            )
            if result.rowcount != 1:
                processing = conn.execute(
                    """SELECT 1 FROM course_sources
                       WHERE course_id = ? AND state = 'processing' LIMIT 1""",
                    (course_id,),
                ).fetchone()
                if processing is not None:
                    raise CourseConflictError("Course has an active source operation")
                self._raise_missing_or_stale(conn, course_id, expected_state="active")
            row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        assert row is not None
        return self._course_from_row(row)

    def restore_course(self, course_id: str, expected_revision: int) -> Course:
        now = time.time()
        with self._write_lock, self._connect() as conn:
            result = conn.execute(
                """UPDATE courses
                   SET state = 'active', revision = revision + 1,
                       write_epoch = write_epoch + 1, archived_at = NULL, updated_at = ?
                   WHERE id = ? AND owner_user_id = ? AND revision = ? AND state = 'archived'""",
                (now, course_id, self.owner_user_id, expected_revision),
            )
            if result.rowcount != 1:
                self._raise_missing_or_stale(conn, course_id, expected_state="archived")
            row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        assert row is not None
        return self._course_from_row(row)

    def set_managed_kb_ref(self, course_id: str, kb_ref: str, expected_revision: int) -> Course:
        now = time.time()
        with self._write_lock, self._connect() as conn:
            result = conn.execute(
                """UPDATE courses
                   SET managed_kb_ref = ?, revision = revision + 1, updated_at = ?
                   WHERE id = ? AND owner_user_id = ? AND revision = ?
                     AND state = 'active' AND managed_kb_ref IS NULL""",
                (kb_ref, now, course_id, self.owner_user_id, expected_revision),
            )
            if result.rowcount != 1:
                self._raise_missing_or_stale(conn, course_id, expected_state="active")
            row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        assert row is not None
        return self._course_from_row(row)

    def ensure_managed_kb_ref(self, course_id: str, kb_ref: str) -> Course:
        """Set the opaque managed-KB reference once, tolerating a concurrent winner."""
        now = time.time()
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """UPDATE courses
                   SET managed_kb_ref = ?, revision = revision + 1, updated_at = ?
                   WHERE id = ? AND owner_user_id = ? AND state = 'active'
                     AND managed_kb_ref IS NULL""",
                (kb_ref, now, course_id, self.owner_user_id),
            )
            row = conn.execute(
                "SELECT * FROM courses WHERE id = ? AND owner_user_id = ?",
                (course_id, self.owner_user_id),
            ).fetchone()
        if row is None:
            raise CourseNotFoundError("Course not found")
        course = self._course_from_row(row)
        if course.state != "active":
            raise CourseConflictError("Archived courses cannot accept sources")
        if course.managed_kb_ref != kb_ref:
            raise CourseConflictError("Course Knowledge reference is already assigned")
        return course

    def create_source(
        self,
        course_id: str,
        *,
        kind: str,
        display_name: str,
        manifest: list[dict[str, Any]],
        content_sha256: str,
        supersedes_source_id: str | None = None,
        operation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> CourseSource:
        course = self.get_course(course_id)
        if course.state != "active":
            raise CourseConflictError("Archived courses cannot accept sources")
        if supersedes_source_id is not None:
            prior = self.get_source(course_id, supersedes_source_id)
            if prior.state not in {"ready", "archived"}:
                raise CourseConflictError("Only a completed source can be superseded")
        sid = _source_id()
        op_id = operation_id or _operation_id()
        now = time.time()
        with self._write_lock, self._connect() as conn:
            current = conn.execute(
                "SELECT state FROM courses WHERE id = ? AND owner_user_id = ?",
                (course_id, self.owner_user_id),
            ).fetchone()
            if current is None:
                raise CourseNotFoundError("Course not found")
            if str(current["state"]) != "active":
                raise CourseConflictError("Archived courses cannot accept sources")
            try:
                conn.execute(
                    """INSERT INTO course_sources
                       (id, course_id, kind, display_name, state, manifest_json,
                        content_sha256, revision, operation_id, idempotency_key, supersedes_source_id,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'processing', ?, ?, 1, ?, ?, ?, ?, ?)""",
                    (
                        sid,
                        course_id,
                        self._clean_label(kind, "Source kind", 40),
                        self._clean_label(display_name, "Source display name"),
                        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
                        content_sha256,
                        op_id,
                        self._clean_label(idempotency_key, "Idempotency key", 160)
                        if idempotency_key
                        else None,
                        supersedes_source_id,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if supersedes_source_id is not None:
                    live_successor = conn.execute(
                        """SELECT 1 FROM course_sources
                           WHERE supersedes_source_id = ?
                             AND state IN ('processing', 'ready')""",
                        (supersedes_source_id,),
                    ).fetchone()
                    if live_successor is not None:
                        raise CourseConflictError(
                            "Source already has an active replacement"
                        ) from exc
                raise
            row = conn.execute("SELECT * FROM course_sources WHERE id = ?", (sid,)).fetchone()
        assert row is not None
        return self._source_from_row(row)

    def get_source_by_idempotency_key(
        self, course_id: str, idempotency_key: str
    ) -> CourseSource | None:
        self.get_course(course_id)
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM course_sources
                   WHERE course_id = ? AND idempotency_key = ?""",
                (course_id, self._clean_label(idempotency_key, "Idempotency key", 160)),
            ).fetchone()
        return self._source_from_row(row) if row is not None else None

    def update_processing_source_manifest(
        self,
        course_id: str,
        source_id: str,
        *,
        operation_id: str,
        expected_revision: int,
        manifest: list[dict[str, Any]],
        content_sha256: str,
    ) -> CourseSource:
        now = time.time()
        with self._write_lock, self._connect() as conn:
            result = conn.execute(
                """UPDATE course_sources
                   SET manifest_json = ?, content_sha256 = ?,
                       revision = revision + 1, updated_at = ?
                   WHERE id = ? AND course_id = ? AND state = 'processing'
                     AND operation_id = ? AND revision = ?""",
                (
                    json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
                    content_sha256,
                    now,
                    source_id,
                    course_id,
                    operation_id,
                    expected_revision,
                ),
            )
            if result.rowcount != 1:
                exists = conn.execute(
                    "SELECT 1 FROM course_sources WHERE id = ? AND course_id = ?",
                    (source_id, course_id),
                ).fetchone()
                if exists is None:
                    raise CourseNotFoundError("Course source not found")
                raise CourseConflictError("Source operation is stale or no longer writable")
            row = conn.execute("SELECT * FROM course_sources WHERE id = ?", (source_id,)).fetchone()
        assert row is not None
        return self._source_from_row(row)

    def reconcile_abandoned_sources(
        self,
        *,
        active_operation_ids: set[str],
        course_id: str | None = None,
        older_than_seconds: float = 300.0,
        candidate_source_ids: set[str] | None = None,
    ) -> int:
        """Fail processing rows whose in-memory task disappeared after a crash.

        When ``course_id`` is supplied, reconciliation is strictly limited to
        that aggregate.  A Course list/read must never adjudicate another
        Course's background operations using an incomplete active-task set.
        """
        cutoff = time.time() - max(0.0, older_than_seconds)
        with self._write_lock, self._connect() as conn:
            if course_id is None:
                rows = conn.execute(
                    """SELECT id, operation_id FROM course_sources
                       WHERE state = 'processing' AND updated_at <= ?""",
                    (cutoff,),
                ).fetchall()
            else:
                self.get_course(course_id)
                rows = conn.execute(
                    """SELECT id, operation_id FROM course_sources
                       WHERE course_id = ? AND state = 'processing'
                         AND updated_at <= ?""",
                    (course_id, cutoff),
                ).fetchall()
            abandoned = [
                str(row["id"])
                for row in rows
                if candidate_source_ids is None or str(row["id"]) in candidate_source_ids
                if not row["operation_id"] or str(row["operation_id"]) not in active_operation_ids
            ]
            if not abandoned:
                return 0
            placeholders = ",".join("?" for _ in abandoned)
            conn.execute(
                f"""UPDATE course_sources
                    SET state = 'failed', revision = revision + 1, updated_at = ?
                    WHERE id IN ({placeholders}) AND state = 'processing'""",
                [time.time(), *abandoned],
            )
        return len(abandoned)

    def list_sources(self, course_id: str) -> list[CourseSource]:
        self.get_course(course_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM course_sources WHERE course_id = ? ORDER BY updated_at DESC, id",
                (course_id,),
            ).fetchall()
        return [self._source_from_row(row) for row in rows]

    def get_source(self, course_id: str, source_id: str) -> CourseSource:
        self.get_course(course_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM course_sources WHERE id = ? AND course_id = ?",
                (source_id, course_id),
            ).fetchone()
        if row is None:
            raise CourseNotFoundError("Course source not found")
        return self._source_from_row(row)

    def transition_source(
        self,
        course_id: str,
        source_id: str,
        *,
        operation_id: str,
        expected_source_revision: int,
        expected_course_revision: int,
        expected_write_epoch: int,
        state: str,
    ) -> CourseSource:
        if state not in {"ready", "failed"}:
            raise ValueError("Source transition state must be ready or failed")
        now = time.time()
        with self._write_lock, self._connect() as conn:
            result = conn.execute(
                """UPDATE course_sources
                   SET state = ?, revision = revision + 1, updated_at = ?
                   WHERE id = ? AND course_id = ? AND state = 'processing'
                     AND operation_id = ? AND revision = ?
                     AND EXISTS (
                       SELECT 1 FROM courses
                       WHERE courses.id = course_sources.course_id
                         AND courses.owner_user_id = ?
                         AND courses.state = 'active'
                         AND courses.revision = ?
                         AND courses.write_epoch = ?
                     )""",
                (
                    state,
                    now,
                    source_id,
                    course_id,
                    operation_id,
                    expected_source_revision,
                    self.owner_user_id,
                    expected_course_revision,
                    expected_write_epoch,
                ),
            )
            if result.rowcount != 1:
                raise CourseConflictError("Source operation is stale or no longer writable")
            row = conn.execute("SELECT * FROM course_sources WHERE id = ?", (source_id,)).fetchone()
        assert row is not None
        return self._source_from_row(row)

    def fail_source_operation(
        self,
        course_id: str,
        source_id: str,
        *,
        operation_id: str,
        expected_source_revision: int,
    ) -> bool:
        """Terminalize a failed worker without granting it a normal Course commit.

        Revocation, provider failure, or a changed Course revision must prevent a
        successful ``ready`` commit, but must not strand the owned source in
        ``processing`` forever.  This cleanup is limited to the exact operation
        and source revision and can only move processing -> failed.
        """
        now = time.time()
        with self._write_lock, self._connect() as conn:
            result = conn.execute(
                """UPDATE course_sources
                   SET state = 'failed', revision = revision + 1, updated_at = ?
                   WHERE id = ? AND course_id = ? AND state = 'processing'
                     AND operation_id = ? AND revision = ?
                     AND EXISTS (
                       SELECT 1 FROM courses
                       WHERE courses.id = course_sources.course_id
                         AND courses.owner_user_id = ?
                     )""",
                (
                    now,
                    source_id,
                    course_id,
                    operation_id,
                    expected_source_revision,
                    self.owner_user_id,
                ),
            )
        return result.rowcount == 1

    def archive_source(self, course_id: str, source_id: str, expected_revision: int) -> CourseSource:
        course = self.get_course(course_id)
        if course.state != "active":
            raise CourseConflictError("Archived courses cannot change sources")
        now = time.time()
        with self._write_lock, self._connect() as conn:
            result = conn.execute(
                """UPDATE course_sources
                   SET state = 'archived', revision = revision + 1, updated_at = ?
                   WHERE id = ? AND course_id = ? AND revision = ?
                     AND state IN ('ready', 'failed')
                     AND EXISTS (
                       SELECT 1 FROM courses
                       WHERE courses.id = course_sources.course_id
                         AND courses.owner_user_id = ?
                         AND courses.state = 'active'
                     )""",
                (now, source_id, course_id, expected_revision, self.owner_user_id),
            )
            if result.rowcount != 1:
                current_course = conn.execute(
                    "SELECT state FROM courses WHERE id = ? AND owner_user_id = ?",
                    (course_id, self.owner_user_id),
                ).fetchone()
                if current_course is None:
                    raise CourseNotFoundError("Course not found")
                if str(current_course["state"]) != "active":
                    raise CourseConflictError("Archived courses cannot change sources")
                exists = conn.execute(
                    "SELECT state FROM course_sources WHERE id = ? AND course_id = ?",
                    (source_id, course_id),
                ).fetchone()
                if exists is None:
                    raise CourseNotFoundError("Course source not found")
                raise CourseConflictError("Source is active or its revision is stale")
            row = conn.execute("SELECT * FROM course_sources WHERE id = ?", (source_id,)).fetchone()
        assert row is not None
        return self._source_from_row(row)

    def has_processing_sources(self, course_id: str) -> bool:
        self.get_course(course_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM course_sources WHERE course_id = ? AND state = 'processing' LIMIT 1",
                (course_id,),
            ).fetchone()
        return row is not None
