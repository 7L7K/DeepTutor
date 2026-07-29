"""Course-rooted persistence for immutable Practice authoring history."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Iterable
from uuid import uuid4

from pydantic import ValidationError

from .models import Course
from .practice_models import (
    ExactAnswerContract,
    PracticeCitation,
    PracticeMode,
    PracticeQuestion,
    PracticeSet,
    PracticeSetRevision,
    PracticeSourceReceipt,
)
from .repository import CourseConflictError, CourseNotFoundError, CourseRepository

_MAX_OBJECTIVES = 64
_MAX_SOURCES = 64
_MAX_CITATIONS = 32
_MAX_JSON_BYTES = 16_384


def _practice_set_id() -> str:
    return f"prc_{uuid4().hex}"


def _practice_revision_id() -> str:
    return f"prv_{uuid4().hex}"


def _practice_question_id() -> str:
    return f"qst_{uuid4().hex}"


class CoursePracticeRepository:
    """Persist Practice records through a ``CourseRepository`` aggregate.

    This intentionally reuses the parent repository's private database path,
    connection policy, and resolved-path lock. It never accepts an owner or a
    filesystem path from the caller.
    """

    def __init__(self, course_repository: CourseRepository) -> None:
        self.course_repository = course_repository

    @property
    def owner_user_id(self) -> str:
        return self.course_repository.owner_user_id

    @staticmethod
    def _not_found() -> CourseNotFoundError:
        return CourseNotFoundError("Practice resource not found")

    @staticmethod
    def _clean_text(value: str, field: str, *, maximum: int, required: bool = True) -> str:
        cleaned = " ".join(str(value or "").split())
        if required and not cleaned:
            raise ValueError(f"{field} is required")
        if len(cleaned) > maximum:
            raise ValueError(f"{field} must be {maximum} characters or fewer")
        return cleaned

    @classmethod
    def _objective_ids(cls, objective_ids: Iterable[str]) -> list[str]:
        if isinstance(objective_ids, (str, bytes)):
            raise ValueError("objective_ids must be a list of objective IDs")
        try:
            values = list(objective_ids)
        except TypeError as exc:
            raise ValueError("objective_ids must be a list of objective IDs") from exc
        if len(values) > _MAX_OBJECTIVES:
            raise ValueError("too many objective IDs")
        cleaned = [cls._clean_text(value, "Objective ID", maximum=160) for value in values]
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("objective_ids must not contain duplicates")
        return cleaned

    def _course_for_write(
        self,
        conn: sqlite3.Connection,
        course_id: str,
        expected_course_write_epoch: int,
    ) -> Course:
        row = conn.execute(
            """SELECT * FROM courses
               WHERE id = ? AND owner_user_id = ?""",
            (course_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        course = Course.model_validate(dict(row))
        if course.state != "active":
            raise CourseConflictError("Archived courses cannot author Practice")
        if course.write_epoch != expected_course_write_epoch:
            raise CourseConflictError("Course write epoch is stale")
        return course

    def _set_from_row(self, row: sqlite3.Row) -> PracticeSet:
        record = PracticeSet.model_validate(dict(row))
        if record.owner_user_id != self.owner_user_id:
            raise self._not_found()
        return record

    @staticmethod
    def _revision_from_row(row: sqlite3.Row) -> PracticeSetRevision:
        payload = dict(row)
        payload["source_snapshot"] = json.loads(payload.pop("source_snapshot_json") or "[]")
        payload["objective_ids"] = json.loads(payload.pop("objective_ids_json") or "[]")
        payload["generation_receipt"] = json.loads(payload.pop("generation_receipt_json")) if payload.get("generation_receipt_json") else None
        payload.pop("generation_receipt_json", None)
        return PracticeSetRevision.model_validate(payload)

    @staticmethod
    def _question_from_row(row: sqlite3.Row) -> PracticeQuestion:
        payload = dict(row)
        payload["answer_contract"] = json.loads(payload.pop("answer_contract_json"))
        payload["objective_ids"] = json.loads(payload.pop("objective_ids_json") or "[]")
        payload["citations"] = json.loads(payload.pop("citation_json") or "[]")
        return PracticeQuestion.model_validate(payload)

    def _owned_set_row(
        self, conn: sqlite3.Connection, course_id: str, practice_set_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            """SELECT practice_sets.* FROM practice_sets
               JOIN courses ON courses.id = practice_sets.course_id
               WHERE practice_sets.id = ? AND practice_sets.course_id = ?
                 AND courses.owner_user_id = ?""",
            (practice_set_id, course_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        return row

    def _owned_revision_row(
        self,
        conn: sqlite3.Connection,
        course_id: str,
        practice_set_id: str,
        revision_id: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            """SELECT revisions.* FROM practice_set_revisions AS revisions
               JOIN practice_sets ON practice_sets.id = revisions.practice_set_id
               JOIN courses ON courses.id = practice_sets.course_id
               WHERE revisions.id = ? AND revisions.practice_set_id = ?
                 AND practice_sets.id = ? AND practice_sets.course_id = ?
                 AND courses.owner_user_id = ?""",
            (revision_id, practice_set_id, practice_set_id, course_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        return row

    def _source_snapshot(
        self, conn: sqlite3.Connection, course_id: str, source_ids: Iterable[str]
    ) -> tuple[list[PracticeSourceReceipt], str]:
        if isinstance(source_ids, (str, bytes)):
            raise ValueError("source_ids must be a list of Course source IDs")
        try:
            ids = list(source_ids)
        except TypeError as exc:
            raise ValueError("source_ids must be a list of Course source IDs") from exc
        if len(ids) > _MAX_SOURCES or len(set(ids)) != len(ids):
            raise ValueError("source_ids must be unique and bounded")
        if any(not isinstance(source_id, str) or not source_id.startswith("src_") for source_id in ids):
            raise ValueError("source_ids must be opaque Course source IDs")
        if not ids:
            return [], "[]"
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"""SELECT id, revision, content_sha256, state FROM course_sources
                WHERE course_id = ? AND id IN ({placeholders})""",
            [course_id, *ids],
        ).fetchall()
        by_id = {str(row["id"]): row for row in rows}
        if len(by_id) != len(ids) or any(str(by_id[item]["state"]) != "ready" for item in ids):
            raise self._not_found()
        receipts = [
            PracticeSourceReceipt(
                source_id=source_id,
                source_revision=int(by_id[source_id]["revision"]),
                content_sha256=str(by_id[source_id]["content_sha256"]),
            )
            for source_id in ids
        ]
        return receipts, json.dumps([item.model_dump() for item in receipts], separators=(",", ":"))

    def create_practice_set(
        self,
        course_id: str,
        *,
        title: str,
        mode: PracticeMode = "manual",
        expected_course_write_epoch: int,
    ) -> PracticeSet:
        if mode != "manual":
            raise ValueError("Generated Practice is not enabled in P4-02A")
        now = time.time()
        practice_set_id = _practice_set_id()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            conn.execute(
                """INSERT INTO practice_sets
                   (id, owner_user_id, course_id, title, mode, state, current_revision_id,
                    revision, write_epoch, created_at, updated_at, archived_at)
                   VALUES (?, ?, ?, ?, ?, 'draft', NULL, 1, 1, ?, ?, NULL)""",
                (practice_set_id, self.owner_user_id, course_id, self._clean_text(title, "Practice title", maximum=160), mode, now, now),
            )
            row = conn.execute("SELECT * FROM practice_sets WHERE id = ?", (practice_set_id,)).fetchone()
        assert row is not None
        return self._set_from_row(row)

    def create_draft_revision(
        self,
        course_id: str,
        practice_set_id: str,
        *,
        source_ids: Iterable[str] = (),
        objective_ids: Iterable[str] = (),
        generation_receipt: dict[str, Any] | None = None,
        expected_course_write_epoch: int,
    ) -> PracticeSetRevision:
        objectives = self._objective_ids(objective_ids)
        if generation_receipt is not None:
            raise ValueError("Generation receipts require the P4-05 server operation")
        receipt_json = None
        now = time.time()
        revision_id = _practice_revision_id()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            practice_set = self._set_from_row(self._owned_set_row(conn, course_id, practice_set_id))
            if practice_set.state != "draft":
                raise CourseConflictError("archived Practice sets cannot be edited")
            if practice_set.mode == "generated":
                raise CourseConflictError("Generated Practice revisions are reserved for generation operations")
            snapshots, snapshot_json = self._source_snapshot(conn, course_id, source_ids)
            has_draft = conn.execute(
                "SELECT 1 FROM practice_set_revisions WHERE practice_set_id = ? AND state = 'draft'",
                (practice_set_id,),
            ).fetchone()
            if has_draft is not None:
                raise CourseConflictError("Practice set already has a draft revision")
            if practice_set.mode == "generated" and not snapshots:
                raise ValueError("Generated Practice requires ready Course sources")
            next_number = int(conn.execute(
                "SELECT COALESCE(MAX(revision_number), 0) + 1 FROM practice_set_revisions WHERE practice_set_id = ?",
                (practice_set_id,),
            ).fetchone()[0])
            conn.execute(
                """INSERT INTO practice_set_revisions
                   (id, practice_set_id, revision_number, state, source_snapshot_json,
                    objective_ids_json, generation_receipt_json, created_at, ready_at)
                   VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, NULL)""",
                (revision_id, practice_set_id, next_number, snapshot_json, json.dumps(objectives, separators=(",", ":")), receipt_json, now),
            )
            row = conn.execute("SELECT * FROM practice_set_revisions WHERE id = ?", (revision_id,)).fetchone()
        assert row is not None
        return self._revision_from_row(row)

    def create_successor_revision(self, course_id: str, practice_set_id: str, **kwargs: Any) -> PracticeSetRevision:
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            practice_set = self._set_from_row(self._owned_set_row(conn, course_id, practice_set_id))
            if practice_set.current_revision_id is None:
                raise CourseConflictError("Practice set has no ready revision to succeed")
        return self.create_draft_revision(course_id, practice_set_id, **kwargs)

    def add_question(
        self,
        course_id: str,
        practice_set_id: str,
        revision_id: str,
        *,
        question_type: str,
        prompt: str,
        answer_contract: dict[str, Any] | ExactAnswerContract,
        explanation: str = "",
        objective_ids: Iterable[str] = (),
        citations: Iterable[PracticeCitation | dict[str, Any]] = (),
        ordinal: int | None = None,
        expected_course_write_epoch: int,
    ) -> PracticeQuestion:
        try:
            contract = ExactAnswerContract.model_validate(answer_contract)
        except ValidationError as exc:
            raise ValueError("answer_contract must be a supported typed contract") from exc
        objectives = self._objective_ids(objective_ids)
        if isinstance(citations, (str, bytes)):
            raise ValueError("citations must be a list")
        try:
            raw_citations = list(citations)
        except TypeError as exc:
            raise ValueError("citations must be a list") from exc
        if len(raw_citations) > _MAX_CITATIONS:
            raise ValueError("too many citations")
        try:
            typed_citations = [PracticeCitation.model_validate(item) for item in raw_citations]
        except ValidationError as exc:
            raise ValueError("citations must be typed source receipts") from exc
        try:
            citation_json = json.dumps(
                [item.model_dump() for item in typed_citations],
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("citations must contain strict JSON values") from exc
        if len(citation_json.encode("utf-8")) > _MAX_JSON_BYTES:
            raise ValueError("citations are too large")
        now = time.time()
        question_id = _practice_question_id()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            practice_set = self._set_from_row(self._owned_set_row(conn, course_id, practice_set_id))
            if practice_set.state != "draft":
                raise CourseConflictError("archived Practice sets cannot be edited")
            if practice_set.mode == "generated":
                raise CourseConflictError("Generated Practice questions are reserved for generation operations")
            revision = self._revision_from_row(self._owned_revision_row(conn, course_id, practice_set_id, revision_id))
            if revision.state != "draft":
                raise CourseConflictError("ready Practice revisions are immutable")
            snapshot_keys = {(item.source_id, item.source_revision, item.content_sha256) for item in revision.source_snapshot}
            if any((item.source_id, item.source_revision, item.content_sha256) not in snapshot_keys for item in typed_citations):
                raise ValueError("citation must resolve to the revision source receipt")
            if practice_set.mode == "generated" and not typed_citations:
                raise ValueError("Generated Practice questions require citations")
            if ordinal is None:
                ordinal = int(conn.execute(
                    "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM practice_questions WHERE practice_set_revision_id = ?",
                    (revision_id,),
                ).fetchone()[0])
            if not isinstance(ordinal, int) or ordinal < 1:
                raise ValueError("ordinal must be a positive integer")
            try:
                conn.execute(
                    """INSERT INTO practice_questions
                       (id, practice_set_revision_id, question_type, prompt, answer_contract_json,
                        explanation, objective_ids_json, citation_json, ordinal, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (question_id, revision_id, self._clean_text(question_type, "Question type", maximum=80), self._clean_text(prompt, "Question prompt", maximum=12_000), json.dumps(contract.model_dump(), allow_nan=False, separators=(",", ":")), self._clean_text(explanation, "Question explanation", maximum=12_000, required=False), json.dumps(objectives, allow_nan=False, separators=(",", ":")), citation_json, ordinal, now),
                )
            except sqlite3.IntegrityError as exc:
                raise CourseConflictError("Practice question ordinal already exists") from exc
            row = conn.execute("SELECT * FROM practice_questions WHERE id = ?", (question_id,)).fetchone()
        assert row is not None
        return self._question_from_row(row)

    def ready_revision(self, course_id: str, practice_set_id: str, revision_id: str, *, expected_course_write_epoch: int) -> PracticeSetRevision:
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            practice_set = self._set_from_row(self._owned_set_row(conn, course_id, practice_set_id))
            if practice_set.state != "draft":
                raise CourseConflictError("Archived Practice sets cannot be edited")
            if practice_set.mode == "generated":
                raise CourseConflictError("Generated Practice publication is reserved for generation operations")
            revision = self._revision_from_row(self._owned_revision_row(conn, course_id, practice_set_id, revision_id))
            if revision.state != "draft":
                raise CourseConflictError("ready Practice revisions are immutable")
            if not conn.execute("SELECT 1 FROM practice_questions WHERE practice_set_revision_id = ?", (revision_id,)).fetchone():
                raise CourseConflictError("Practice revision needs at least one question")
            conn.execute(
                """UPDATE practice_set_revisions
                   SET state = 'superseded'
                   WHERE practice_set_id = ? AND id != ? AND state = 'ready'""",
                (practice_set_id, revision_id),
            )
            conn.execute("UPDATE practice_set_revisions SET state = 'ready', ready_at = ? WHERE id = ?", (now, revision_id))
            conn.execute("UPDATE practice_sets SET current_revision_id = ?, revision = revision + 1, write_epoch = write_epoch + 1, updated_at = ? WHERE id = ?", (revision_id, now, practice_set_id))
            row = conn.execute("SELECT * FROM practice_set_revisions WHERE id = ?", (revision_id,)).fetchone()
        assert row is not None
        return self._revision_from_row(row)

    def archive_practice_set(self, course_id: str, practice_set_id: str, *, expected_revision: int, expected_course_write_epoch: int) -> PracticeSet:
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            result = conn.execute(
                """UPDATE practice_sets SET state = 'archived', revision = revision + 1,
                   write_epoch = write_epoch + 1, archived_at = ?, updated_at = ?
                   WHERE id = ? AND course_id = ? AND owner_user_id = ? AND state = 'draft'
                     AND revision = ?""",
                (now, now, practice_set_id, course_id, self.owner_user_id, expected_revision),
            )
            if result.rowcount != 1:
                existing = self._owned_set_row(conn, course_id, practice_set_id)
                if str(existing["state"]) == "archived":
                    raise CourseConflictError("Practice set is already archived")
                raise CourseConflictError("Practice set revision is stale")
            row = conn.execute("SELECT * FROM practice_sets WHERE id = ?", (practice_set_id,)).fetchone()
        assert row is not None
        return self._set_from_row(row)

    def restore_practice_set(self, course_id: str, practice_set_id: str, *, expected_revision: int, expected_course_write_epoch: int) -> PracticeSet:
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            result = conn.execute(
                """UPDATE practice_sets SET state = 'draft', revision = revision + 1,
                   write_epoch = write_epoch + 1, archived_at = NULL, updated_at = ?
                   WHERE id = ? AND course_id = ? AND owner_user_id = ? AND state = 'archived'
                     AND revision = ?""",
                (now, practice_set_id, course_id, self.owner_user_id, expected_revision),
            )
            if result.rowcount != 1:
                self._owned_set_row(conn, course_id, practice_set_id)
                raise CourseConflictError("Practice set is active or its revision is stale")
            row = conn.execute("SELECT * FROM practice_sets WHERE id = ?", (practice_set_id,)).fetchone()
        assert row is not None
        return self._set_from_row(row)

    def list_practice_sets(self, course_id: str, *, include_archived: bool = True) -> list[PracticeSet]:
        self.course_repository.get_course(course_id)
        sql = """SELECT practice_sets.* FROM practice_sets JOIN courses ON courses.id = practice_sets.course_id WHERE practice_sets.course_id = ? AND courses.owner_user_id = ?"""
        params: list[Any] = [course_id, self.owner_user_id]
        if not include_archived:
            sql += " AND practice_sets.state = 'draft'"
        sql += " ORDER BY practice_sets.updated_at DESC, practice_sets.id"
        with self.course_repository._connect() as conn:
            return [self._set_from_row(row) for row in conn.execute(sql, params).fetchall()]

    def get_practice_set(self, course_id: str, practice_set_id: str) -> PracticeSet:
        self.course_repository.get_course(course_id)
        with self.course_repository._connect() as conn:
            return self._set_from_row(self._owned_set_row(conn, course_id, practice_set_id))

    def get_revision(self, course_id: str, practice_set_id: str, revision_id: str) -> PracticeSetRevision:
        self.course_repository.get_course(course_id)
        with self.course_repository._connect() as conn:
            return self._revision_from_row(self._owned_revision_row(conn, course_id, practice_set_id, revision_id))

    def list_questions(self, course_id: str, practice_set_id: str, revision_id: str) -> list[PracticeQuestion]:
        self.course_repository.get_course(course_id)
        with self.course_repository._connect() as conn:
            self._owned_revision_row(conn, course_id, practice_set_id, revision_id)
            rows = conn.execute("SELECT * FROM practice_questions WHERE practice_set_revision_id = ? ORDER BY ordinal, id", (revision_id,)).fetchall()
        return [self._question_from_row(row) for row in rows]
