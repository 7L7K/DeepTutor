"""Transactional authority for durable grounded Practice generation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any, Iterable
from uuid import uuid4

from .generation_governance import admit_generation_allocation
from .generation_models import (
    GeneratedPracticeOutput,
    PracticeDifficulty,
    PracticeGenerationOperation,
    PracticeGenerationPlan,
    PracticeGenerationPlanConfirmation,
    PracticeGenerationPlanOrigin,
    PracticeGenerationRequest,
    PracticeQualityProfile,
    PracticeTimingMode,
)
from .practice_models import (
    PracticeSet,
    PracticeSetRevision,
    PracticeSourceReceipt,
)
from .repository import CourseConflictError, CourseNotFoundError, CourseRepository

_MAX_OBJECTIVES = 64
_MAX_SOURCES = 64
_MAX_IDEMPOTENCY_KEY = 160
_MAX_TITLE = 160
_MAX_GENERATED_OUTPUT_BYTES = 48_000


def _operation_id() -> str:
    return f"opg_{uuid4().hex}"


def _practice_set_id() -> str:
    return f"prc_{uuid4().hex}"


def _revision_id() -> str:
    return f"prv_{uuid4().hex}"


def _question_id() -> str:
    return f"qst_{uuid4().hex}"


def _plan_id() -> str:
    return f"pln_{uuid4().hex}"


class CoursePracticeGenerationRepository:
    """Own one user's generation rows through the Course database aggregate."""

    def __init__(self, course_repository: CourseRepository) -> None:
        self.course_repository = course_repository

    @property
    def owner_user_id(self) -> str:
        return self.course_repository.owner_user_id

    @staticmethod
    def _not_found() -> CourseNotFoundError:
        return CourseNotFoundError("Practice generation resource not found")

    @staticmethod
    def _clean(value: str, field: str, maximum: int, *, required: bool = True) -> str:
        cleaned = " ".join(str(value or "").split())
        if required and not cleaned:
            raise ValueError(f"{field} is required")
        if len(cleaned) > maximum:
            raise ValueError(f"{field} must be {maximum} characters or fewer")
        return cleaned

    @classmethod
    def _objectives(cls, values: Iterable[str]) -> list[str]:
        if isinstance(values, (str, bytes)):
            raise ValueError("objective_ids must be a list")
        try:
            items = list(values)
        except TypeError as exc:
            raise ValueError("objective_ids must be a list") from exc
        if len(items) > _MAX_OBJECTIVES:
            raise ValueError("too many objective IDs")
        result = [cls._clean(value, "Objective ID", 160) for value in items]
        if len(set(result)) != len(result):
            raise ValueError("objective_ids must not contain duplicates")
        return result

    @classmethod
    def _source_ids(cls, values: Iterable[str]) -> list[str]:
        if isinstance(values, (str, bytes)):
            raise ValueError("source_ids must be a list")
        try:
            items = list(values)
        except TypeError as exc:
            raise ValueError("source_ids must be a list") from exc
        if not items or len(items) > _MAX_SOURCES or len(set(items)) != len(items):
            raise ValueError("source_ids must contain between one and 64 unique opaque IDs")
        if any(not isinstance(item, str) or not item.startswith("src_") or len(item) > 80 for item in items):
            raise ValueError("source_ids must be opaque Course source IDs")
        return items

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _fingerprint(
        cls,
        *,
        title: str,
        source_ids: list[str],
        objectives: list[str],
        item_limit: int,
        context_char_limit: int,
        focus: str = "Course review",
        difficulty: PracticeDifficulty = "mixed",
        timing_mode: PracticeTimingMode = "untimed",
        quality_profile: PracticeQualityProfile = "baseline-v1",
    ) -> str:
        return hashlib.sha256(cls._json({
            "title": title,
            "source_ids": source_ids,
            "objective_ids": objectives,
            "item_limit": item_limit,
            "context_char_limit": context_char_limit,
            "focus": focus,
            "difficulty": difficulty,
            "timing_mode": timing_mode,
            "quality_profile": quality_profile,
        }).encode("utf-8")).hexdigest()

    @staticmethod
    def _quality_profile(value: str) -> PracticeQualityProfile:
        if value not in {"baseline-v1", "c3-biology-v1"}:
            raise ValueError("quality_profile must be baseline-v1 or c3-biology-v1")
        return value  # type: ignore[return-value]

    @staticmethod
    def _set_from_row(row: sqlite3.Row) -> PracticeSet:
        return PracticeSet.model_validate(dict(row))

    @staticmethod
    def _revision_from_row(row: sqlite3.Row) -> PracticeSetRevision:
        payload = dict(row)
        payload["source_snapshot"] = json.loads(payload.pop("source_snapshot_json") or "[]")
        payload["objective_ids"] = json.loads(payload.pop("objective_ids_json") or "[]")
        raw_receipt = payload.pop("generation_receipt_json")
        payload["generation_receipt"] = json.loads(raw_receipt) if raw_receipt else None
        return PracticeSetRevision.model_validate(payload)

    @staticmethod
    def _operation_from_row(row: sqlite3.Row) -> PracticeGenerationOperation:
        payload = dict(row)
        payload["source_snapshot"] = json.loads(payload.pop("source_snapshot_json") or "[]")
        payload["objective_ids"] = json.loads(payload.pop("objective_ids_json") or "[]")
        return PracticeGenerationOperation.model_validate(payload)

    @staticmethod
    def _plan_from_row(row: sqlite3.Row) -> PracticeGenerationPlan:
        payload = dict(row)
        payload["source_snapshot"] = json.loads(payload.pop("source_snapshot_json") or "[]")
        payload["objective_ids"] = json.loads(payload.pop("objective_ids_json") or "[]")
        payload["origin"] = json.loads(payload.pop("origin_json") or "{}")
        payload.pop("creation_idempotency_key", None)
        payload.pop("creation_request_fingerprint", None)
        payload.pop("confirmation_idempotency_key", None)
        return PracticeGenerationPlan.model_validate(payload)

    @classmethod
    def _plan_fingerprint(
        cls,
        *,
        title: str,
        focus: str,
        source_ids: list[str],
        objective_ids: list[str],
        item_limit: int,
        difficulty: PracticeDifficulty,
        timing_mode: PracticeTimingMode,
        origin: PracticeGenerationPlanOrigin,
        quality_profile: PracticeQualityProfile = "baseline-v1",
    ) -> str:
        return hashlib.sha256(
            cls._json(
                {
                    "title": title,
                    "focus": focus,
                    "source_ids": source_ids,
                    "objective_ids": objective_ids,
                    "item_limit": item_limit,
                    "difficulty": difficulty,
                    "timing_mode": timing_mode,
                    "quality_profile": quality_profile,
                    "origin": origin.model_dump(mode="json"),
                }
            ).encode("utf-8")
        ).hexdigest()

    def _course_for_write(self, conn: sqlite3.Connection, course_id: str, epoch: int) -> None:
        row = conn.execute(
            "SELECT state, write_epoch FROM courses WHERE id = ? AND owner_user_id = ?",
            (course_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        if str(row["state"]) != "active" or int(row["write_epoch"]) != epoch:
            raise CourseConflictError("Course authority is stale or archived")

    def _owned_set_row(self, conn: sqlite3.Connection, course_id: str, practice_set_id: str) -> sqlite3.Row:
        row = conn.execute(
            """SELECT practice_sets.* FROM practice_sets JOIN courses ON courses.id = practice_sets.course_id
               WHERE practice_sets.id = ? AND practice_sets.course_id = ?
                 AND courses.owner_user_id = ?""",
            (practice_set_id, course_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        return row

    def _owned_operation_row(self, conn: sqlite3.Connection, course_id: str, operation_id: str) -> sqlite3.Row:
        row = conn.execute(
            """SELECT operations.* FROM practice_generation_operations AS operations
               JOIN courses ON courses.id = operations.course_id
               WHERE operations.id = ? AND operations.course_id = ?
                 AND operations.owner_user_id = ? AND courses.owner_user_id = ?""",
            (operation_id, course_id, self.owner_user_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        return row

    def _owned_plan_row(
        self, conn: sqlite3.Connection, course_id: str, plan_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            """SELECT plans.* FROM practice_generation_plans AS plans
               JOIN courses ON courses.id = plans.course_id
               WHERE plans.id = ? AND plans.course_id = ?
                 AND plans.owner_user_id = ? AND courses.owner_user_id = ?""",
            (plan_id, course_id, self.owner_user_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        return row

    def _snapshot_sources(self, conn: sqlite3.Connection, course_id: str, source_ids: list[str]) -> list[PracticeSourceReceipt]:
        placeholders = ",".join("?" for _ in source_ids)
        rows = conn.execute(
            f"""SELECT id, revision, content_sha256, state FROM course_sources
                WHERE course_id = ? AND id IN ({placeholders})""",
            [course_id, *source_ids],
        ).fetchall()
        by_id = {str(row["id"]): row for row in rows}
        if len(by_id) != len(source_ids) or any(str(by_id[item]["state"]) != "ready" for item in source_ids):
            raise self._not_found()
        return [PracticeSourceReceipt(
            source_id=item,
            source_revision=int(by_id[item]["revision"]),
            content_sha256=str(by_id[item]["content_sha256"]),
        ) for item in source_ids]

    def _verify_snapshot(self, conn: sqlite3.Connection, course_id: str, snapshot: list[PracticeSourceReceipt]) -> None:
        actual = self._snapshot_sources(conn, course_id, [item.source_id for item in snapshot])
        if [item.model_dump() for item in actual] != [item.model_dump() for item in snapshot]:
            raise CourseConflictError("Course sources changed during generation")

    @staticmethod
    def _plan_options(
        *,
        item_limit: int,
        difficulty: str,
        timing_mode: str,
    ) -> tuple[int, PracticeDifficulty, PracticeTimingMode]:
        if not isinstance(item_limit, int) or not 1 <= item_limit <= 12:
            raise ValueError("item_limit must be between 1 and 12")
        if difficulty not in {"foundation", "mixed", "challenge"}:
            raise ValueError("difficulty must be foundation, mixed, or challenge")
        if timing_mode not in {"untimed", "practice_timer"}:
            raise ValueError("timing_mode must be untimed or practice_timer")
        return item_limit, difficulty, timing_mode

    def _allocate_generated_practice(
        self,
        conn: sqlite3.Connection,
        course_id: str,
        *,
        title: str,
        source_ids: list[str],
        objectives: list[str],
        idempotency_key: str,
        expected_course_write_epoch: int,
        item_limit: int,
        context_char_limit: int,
        focus: str,
        difficulty: PracticeDifficulty,
        timing_mode: PracticeTimingMode,
        provider_available: bool,
        quality_profile: PracticeQualityProfile = "baseline-v1",
        expected_snapshot: list[PracticeSourceReceipt] | None = None,
    ) -> PracticeGenerationRequest:
        fingerprint = self._fingerprint(
            title=title,
            source_ids=source_ids,
            objectives=objectives,
            item_limit=item_limit,
            context_char_limit=context_char_limit,
            focus=focus,
            difficulty=difficulty,
            timing_mode=timing_mode,
            quality_profile=quality_profile,
        )
        prior = conn.execute(
            """SELECT * FROM practice_generation_operations
               WHERE course_id = ? AND idempotency_key = ?""",
            (course_id, idempotency_key),
        ).fetchone()
        if prior is not None:
            operation = self._operation_from_row(prior)
            if operation.request_fingerprint != fingerprint:
                raise CourseConflictError(
                    "Idempotency key was already used for another generation request"
                )
            return PracticeGenerationRequest(
                practice_set_id=operation.practice_set_id,
                practice_set_revision_id=operation.practice_set_revision_id,
                operation=operation,
            )
        if not provider_available:
            raise CourseConflictError("Generation provider is unavailable")
        admit_generation_allocation(conn, self.owner_user_id)
        snapshot = self._snapshot_sources(conn, course_id, source_ids)
        if expected_snapshot is not None and [
            item.model_dump() for item in snapshot
        ] != [item.model_dump() for item in expected_snapshot]:
            raise CourseConflictError("Course sources changed after plan review")
        snapshot_json = self._json([item.model_dump() for item in snapshot])
        objectives_json = self._json(objectives)
        now = time.time()
        set_id, revision_id, operation_id = (
            _practice_set_id(),
            _revision_id(),
            _operation_id(),
        )
        conn.execute(
            """INSERT INTO practice_sets
               (id, owner_user_id, course_id, title, mode, state, current_revision_id,
                revision, write_epoch, created_at, updated_at, archived_at)
               VALUES (?, ?, ?, ?, 'generated', 'draft', NULL, 1, 1, ?, ?, NULL)""",
            (set_id, self.owner_user_id, course_id, title, now, now),
        )
        conn.execute(
            """INSERT INTO practice_set_revisions
               (id, practice_set_id, revision_number, state, source_snapshot_json,
                objective_ids_json, generation_receipt_json, created_at, ready_at)
               VALUES (?, ?, 1, 'draft', ?, ?, NULL, ?, NULL)""",
            (revision_id, set_id, snapshot_json, objectives_json, now),
        )
        conn.execute(
            """INSERT INTO practice_generation_operations
               (id, owner_user_id, course_id, practice_set_id, practice_set_revision_id,
                idempotency_key, request_fingerprint, source_snapshot_json, objective_ids_json,
                course_write_epoch, practice_set_write_epoch, item_limit, context_char_limit,
                focus, difficulty, timing_mode,
                quality_profile,
                state, error_code, created_at, started_at, completed_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?,
                       'queued', NULL, ?, NULL, NULL, ?)""",
            (
                operation_id,
                self.owner_user_id,
                course_id,
                set_id,
                revision_id,
                idempotency_key,
                fingerprint,
                snapshot_json,
                objectives_json,
                expected_course_write_epoch,
                item_limit,
                context_char_limit,
                focus,
                difficulty,
                timing_mode,
                quality_profile,
                now,
                now,
            ),
        )
        operation_row = conn.execute(
            "SELECT * FROM practice_generation_operations WHERE id = ?",
            (operation_id,),
        ).fetchone()
        assert operation_row is not None
        return PracticeGenerationRequest(
            practice_set_id=set_id,
            practice_set_revision_id=revision_id,
            operation=self._operation_from_row(operation_row),
        )

    def create_plan(
        self,
        course_id: str,
        *,
        title: str,
        focus: str,
        source_ids: Iterable[str],
        objective_ids: Iterable[str] = (),
        expected_course_write_epoch: int,
        item_limit: int = 5,
        difficulty: str = "mixed",
        timing_mode: str = "untimed",
        quality_profile: str = "baseline-v1",
        origin: PracticeGenerationPlanOrigin | dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> PracticeGenerationPlan:
        title = self._clean(title, "Practice title", _MAX_TITLE)
        focus = self._clean(focus, "Practice focus", 4_000)
        sources = self._source_ids(source_ids)
        objectives = self._objectives(objective_ids)
        item_limit, difficulty, timing_mode = self._plan_options(
            item_limit=item_limit, difficulty=difficulty, timing_mode=timing_mode
        )
        quality_profile = self._quality_profile(quality_profile)
        origin_record = PracticeGenerationPlanOrigin.model_validate(
            origin or {"kind": "practice"}
        )
        if origin_record.kind == "practice" and (
            origin_record.session_id is not None
            or origin_record.assistant_message_id is not None
        ):
            raise ValueError("Practice origin cannot include Chat authority")
        if origin_record.kind == "course_chat" and (
            origin_record.session_id is None
            or origin_record.assistant_message_id is None
        ):
            raise ValueError("Course Chat origin requires its persisted message binding")
        if idempotency_key is not None:
            idempotency_key = self._clean(
                idempotency_key, "Idempotency key", _MAX_IDEMPOTENCY_KEY
            )
            if len(idempotency_key) < 8:
                raise ValueError("Idempotency key must contain at least 8 characters")
        request_fingerprint = self._plan_fingerprint(
            title=title,
            focus=focus,
            source_ids=sources,
            objective_ids=objectives,
            item_limit=item_limit,
            difficulty=difficulty,
            timing_mode=timing_mode,
            quality_profile=quality_profile,
            origin=origin_record,
        )
        now, plan_id = time.time(), _plan_id()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            if idempotency_key is not None:
                prior = conn.execute(
                    """SELECT * FROM practice_generation_plans
                       WHERE course_id = ? AND owner_user_id = ?
                         AND creation_idempotency_key = ?""",
                    (course_id, self.owner_user_id, idempotency_key),
                ).fetchone()
                if prior is not None:
                    if prior["creation_request_fingerprint"] != request_fingerprint:
                        raise CourseConflictError(
                            "Idempotency key was already used for another quiz plan"
                        )
                    return self._plan_from_row(prior)
            snapshot = self._snapshot_sources(conn, course_id, sources)
            conn.execute(
                """INSERT INTO practice_generation_plans
                   (id, owner_user_id, course_id, title, focus, source_snapshot_json,
                    objective_ids_json, item_limit, difficulty, timing_mode, quality_profile, origin_json,
                    course_write_epoch, revision, state, confirmed_operation_id,
                    creation_idempotency_key, creation_request_fingerprint,
                    confirmation_idempotency_key, created_at, updated_at, confirmed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'draft',
                           NULL, ?, ?, NULL, ?, ?, NULL)""",
                (
                    plan_id,
                    self.owner_user_id,
                    course_id,
                    title,
                    focus,
                    self._json([item.model_dump() for item in snapshot]),
                    self._json(objectives),
                    item_limit,
                    difficulty,
                    timing_mode,
                    quality_profile,
                    self._json(origin_record.model_dump(mode="json")),
                    expected_course_write_epoch,
                    idempotency_key,
                    request_fingerprint if idempotency_key is not None else None,
                    now,
                    now,
                ),
            )
            row = self._owned_plan_row(conn, course_id, plan_id)
        return self._plan_from_row(row)

    def get_plan(self, course_id: str, plan_id: str) -> PracticeGenerationPlan:
        self.course_repository.get_course(course_id)
        with self.course_repository._connect() as conn:
            return self._plan_from_row(self._owned_plan_row(conn, course_id, plan_id))

    def list_plans(self, course_id: str) -> list[PracticeGenerationPlan]:
        self.course_repository.get_course(course_id)
        with self.course_repository._connect() as conn:
            rows = conn.execute(
                """SELECT plans.* FROM practice_generation_plans AS plans
                   JOIN courses ON courses.id = plans.course_id
                   WHERE plans.course_id = ? AND plans.owner_user_id = ?
                     AND courses.owner_user_id = ?
                   ORDER BY plans.updated_at DESC, plans.id""",
                (course_id, self.owner_user_id, self.owner_user_id),
            ).fetchall()
            return [self._plan_from_row(row) for row in rows]

    def update_plan(
        self,
        course_id: str,
        plan_id: str,
        *,
        title: str,
        focus: str,
        source_ids: Iterable[str],
        objective_ids: Iterable[str],
        item_limit: int,
        difficulty: str,
        timing_mode: str,
        expected_revision: int,
    ) -> PracticeGenerationPlan:
        title = self._clean(title, "Practice title", _MAX_TITLE)
        focus = self._clean(focus, "Practice focus", 4_000)
        sources = self._source_ids(source_ids)
        objectives = self._objectives(objective_ids)
        item_limit, difficulty, timing_mode = self._plan_options(
            item_limit=item_limit, difficulty=difficulty, timing_mode=timing_mode
        )
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._plan_from_row(self._owned_plan_row(conn, course_id, plan_id))
            self._course_for_write(conn, course_id, current.course_write_epoch)
            if current.state != "draft" or current.revision != expected_revision:
                raise CourseConflictError("Practice generation plan is stale")
            snapshot = self._snapshot_sources(conn, course_id, sources)
            updated = conn.execute(
                """UPDATE practice_generation_plans
                   SET title = ?, focus = ?, source_snapshot_json = ?,
                       objective_ids_json = ?, item_limit = ?, difficulty = ?,
                       timing_mode = ?, revision = revision + 1, updated_at = ?
                   WHERE id = ? AND course_id = ? AND owner_user_id = ?
                     AND state = 'draft' AND revision = ?""",
                (
                    title,
                    focus,
                    self._json([item.model_dump() for item in snapshot]),
                    self._json(objectives),
                    item_limit,
                    difficulty,
                    timing_mode,
                    now,
                    plan_id,
                    course_id,
                    self.owner_user_id,
                    expected_revision,
                ),
            )
            if updated.rowcount != 1:
                raise CourseConflictError("Practice generation plan is stale")
            row = self._owned_plan_row(conn, course_id, plan_id)
        return self._plan_from_row(row)

    def confirm_plan(
        self,
        course_id: str,
        plan_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
        provider_available: bool,
        context_char_limit: int = 12_000,
    ) -> PracticeGenerationPlanConfirmation:
        idempotency_key = self._clean(
            idempotency_key, "Idempotency key", _MAX_IDEMPOTENCY_KEY
        )
        if not isinstance(context_char_limit, int) or not 1 <= context_char_limit <= 48_000:
            raise ValueError("context_char_limit must be between 1 and 48000")
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._owned_plan_row(conn, course_id, plan_id)
            plan = self._plan_from_row(row)
            stored_key = row["confirmation_idempotency_key"]
            if plan.state == "confirmed":
                if stored_key != idempotency_key or plan.confirmed_operation_id is None:
                    raise CourseConflictError("Practice generation plan is already confirmed")
                operation = self._operation_from_row(
                    self._owned_operation_row(
                        conn, course_id, plan.confirmed_operation_id
                    )
                )
                return PracticeGenerationPlanConfirmation(
                    plan=plan,
                    request=PracticeGenerationRequest(
                        practice_set_id=operation.practice_set_id,
                        practice_set_revision_id=operation.practice_set_revision_id,
                        operation=operation,
                    ),
                )
            conflicting_plan = conn.execute(
                """SELECT 1 FROM practice_generation_plans
                   WHERE course_id = ? AND owner_user_id = ?
                     AND confirmation_idempotency_key = ? AND id != ?""",
                (course_id, self.owner_user_id, idempotency_key, plan_id),
            ).fetchone()
            if conflicting_plan is not None:
                raise CourseConflictError(
                    "Confirmation key was already used for another quiz plan"
                )
            if plan.state != "draft" or plan.revision != expected_revision:
                raise CourseConflictError("Practice generation plan is stale")
            self._course_for_write(conn, course_id, plan.course_write_epoch)
            self._verify_snapshot(conn, course_id, plan.source_snapshot)
            operation_idempotency_key = hashlib.sha256(
                f"{plan.id}\0{idempotency_key}".encode("utf-8")
            ).hexdigest()
            request = self._allocate_generated_practice(
                conn,
                course_id,
                title=plan.title,
                source_ids=[item.source_id for item in plan.source_snapshot],
                objectives=plan.objective_ids,
                idempotency_key=operation_idempotency_key,
                expected_course_write_epoch=plan.course_write_epoch,
                item_limit=plan.item_limit,
                context_char_limit=context_char_limit,
                focus=plan.focus,
                difficulty=plan.difficulty,
                timing_mode=plan.timing_mode,
                quality_profile=plan.quality_profile,
                provider_available=provider_available,
                expected_snapshot=plan.source_snapshot,
            )
            now = time.time()
            conn.execute(
                """UPDATE practice_generation_plans
                   SET state = 'confirmed', confirmed_operation_id = ?,
                       confirmation_idempotency_key = ?, confirmed_at = ?, updated_at = ?
                   WHERE id = ? AND state = 'draft' AND revision = ?""",
                (
                    request.operation.id,
                    idempotency_key,
                    now,
                    now,
                    plan_id,
                    expected_revision,
                ),
            )
            confirmed = self._plan_from_row(
                self._owned_plan_row(conn, course_id, plan_id)
            )
        return PracticeGenerationPlanConfirmation(plan=confirmed, request=request)

    def create_generated_practice(
        self,
        course_id: str,
        *,
        title: str,
        source_ids: Iterable[str],
        objective_ids: Iterable[str] = (),
        idempotency_key: str,
        expected_course_write_epoch: int,
        item_limit: int = 8,
        context_char_limit: int = 24_000,
        focus: str = "Course review",
        difficulty: str = "mixed",
        timing_mode: str = "untimed",
        quality_profile: str = "baseline-v1",
        provider_available: bool = True,
    ) -> PracticeGenerationRequest:
        title = self._clean(title, "Practice title", _MAX_TITLE)
        focus = self._clean(focus, "Practice focus", 4_000)
        sources = self._source_ids(source_ids)
        objectives = self._objectives(objective_ids)
        idempotency_key = self._clean(idempotency_key, "Idempotency key", _MAX_IDEMPOTENCY_KEY)
        item_limit, difficulty, timing_mode = self._plan_options(
            item_limit=item_limit, difficulty=difficulty, timing_mode=timing_mode
        )
        quality_profile = self._quality_profile(quality_profile)
        if not isinstance(context_char_limit, int) or not 1 <= context_char_limit <= 48_000:
            raise ValueError("context_char_limit must be between 1 and 48000")
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            return self._allocate_generated_practice(
                conn,
                course_id,
                title=title,
                source_ids=sources,
                objectives=objectives,
                idempotency_key=idempotency_key,
                expected_course_write_epoch=expected_course_write_epoch,
                item_limit=item_limit,
                context_char_limit=context_char_limit,
                focus=focus,
                difficulty=difficulty,
                timing_mode=timing_mode,
                quality_profile=quality_profile,
                provider_available=provider_available,
            )

    def request_generation(
        self,
        course_id: str,
        practice_set_id: str,
        *,
        source_ids: Iterable[str],
        objective_ids: Iterable[str] = (),
        idempotency_key: str,
        expected_course_write_epoch: int,
        expected_practice_set_write_epoch: int,
        item_limit: int = 8,
        context_char_limit: int = 24_000,
        quality_profile: str = "baseline-v1",
        provider_available: bool = True,
    ) -> PracticeGenerationRequest:
        """Create a fenced generated successor revision for an owned generated set.

        This is intentionally separate from atomic new-set creation: a failed
        draft remains retained history and a later request creates a new
        revision rather than mutating or deleting it.
        """
        sources = self._source_ids(source_ids)
        objectives = self._objectives(objective_ids)
        idempotency_key = self._clean(idempotency_key, "Idempotency key", _MAX_IDEMPOTENCY_KEY)
        if not isinstance(item_limit, int) or not 1 <= item_limit <= 12:
            raise ValueError("item_limit must be between 1 and 12")
        if not isinstance(context_char_limit, int) or not 1 <= context_char_limit <= 48_000:
            raise ValueError("context_char_limit must be between 1 and 48000")
        quality_profile = self._quality_profile(quality_profile)
        now, revision_id, operation_id = time.time(), _revision_id(), _operation_id()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            set_record = self._set_from_row(self._owned_set_row(conn, course_id, practice_set_id))
            if (
                set_record.mode != "generated"
                or set_record.state != "draft"
                or set_record.write_epoch != expected_practice_set_write_epoch
            ):
                raise CourseConflictError("Practice generation authority is stale")
            fingerprint = self._fingerprint(
                title=set_record.title, source_ids=sources, objectives=objectives,
                item_limit=item_limit, context_char_limit=context_char_limit,
                quality_profile=quality_profile,
            )
            prior = conn.execute(
                """SELECT * FROM practice_generation_operations
                   WHERE course_id = ? AND idempotency_key = ?""", (course_id, idempotency_key)
            ).fetchone()
            if prior is not None:
                operation = self._operation_from_row(prior)
                if operation.request_fingerprint != fingerprint or operation.practice_set_id != practice_set_id:
                    raise CourseConflictError("Idempotency key was already used for another generation request")
                return PracticeGenerationRequest(
                    practice_set_id=operation.practice_set_id,
                    practice_set_revision_id=operation.practice_set_revision_id,
                    operation=operation,
                )
            if not provider_available:
                raise CourseConflictError("Generation provider is unavailable")
            admit_generation_allocation(conn, self.owner_user_id)
            snapshot = self._snapshot_sources(conn, course_id, sources)
            snapshot_json, objectives_json = self._json([item.model_dump() for item in snapshot]), self._json(objectives)
            next_revision = int(conn.execute(
                "SELECT COALESCE(MAX(revision_number), 0) + 1 FROM practice_set_revisions WHERE practice_set_id = ?",
                (practice_set_id,),
            ).fetchone()[0])
            conn.execute(
                """INSERT INTO practice_set_revisions
                   (id, practice_set_id, revision_number, state, source_snapshot_json,
                    objective_ids_json, generation_receipt_json, created_at, ready_at)
                   VALUES (?, ?, ?, 'draft', ?, ?, NULL, ?, NULL)""",
                (revision_id, practice_set_id, next_revision, snapshot_json, objectives_json, now),
            )
            conn.execute(
                """INSERT INTO practice_generation_operations
                   (id, owner_user_id, course_id, practice_set_id, practice_set_revision_id,
                    idempotency_key, request_fingerprint, source_snapshot_json, objective_ids_json,
                    course_write_epoch, practice_set_write_epoch, item_limit, context_char_limit,
                    quality_profile, state, error_code, created_at, started_at, completed_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', NULL, ?, NULL, NULL, ?)""",
                (operation_id, self.owner_user_id, course_id, practice_set_id, revision_id,
                 idempotency_key, fingerprint, snapshot_json, objectives_json,
                 expected_course_write_epoch, expected_practice_set_write_epoch,
                 item_limit, context_char_limit, quality_profile, now, now),
            )
            operation_row = conn.execute("SELECT * FROM practice_generation_operations WHERE id = ?", (operation_id,)).fetchone()
        assert operation_row is not None
        return PracticeGenerationRequest(
            practice_set_id=practice_set_id,
            practice_set_revision_id=revision_id,
            operation=self._operation_from_row(operation_row),
        )

    def get_operation(self, course_id: str, operation_id: str) -> PracticeGenerationOperation:
        self.course_repository.get_course(course_id)
        with self.course_repository._connect() as conn:
            return self._operation_from_row(self._owned_operation_row(conn, course_id, operation_id))

    def list_operations(self, course_id: str, *, practice_set_id: str | None = None) -> list[PracticeGenerationOperation]:
        self.course_repository.get_course(course_id)
        with self.course_repository._connect() as conn:
            params: list[Any] = [course_id, self.owner_user_id]
            query = """SELECT operations.* FROM practice_generation_operations AS operations
                       JOIN courses ON courses.id = operations.course_id
                       WHERE operations.course_id = ? AND operations.owner_user_id = ?
                         AND courses.owner_user_id = ?"""
            params.append(self.owner_user_id)
            if practice_set_id is not None:
                self._owned_set_row(conn, course_id, practice_set_id)
                query += " AND operations.practice_set_id = ?"
                params.append(practice_set_id)
            query += " ORDER BY operations.updated_at DESC, operations.id"
            return [self._operation_from_row(row) for row in conn.execute(query, params).fetchall()]

    def cancel_operation(
        self, course_id: str, operation_id: str
    ) -> PracticeGenerationOperation:
        """Request cancellation and terminalize work that has not started."""

        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            operation = self._operation_from_row(
                self._owned_operation_row(conn, course_id, operation_id)
            )
            if operation.state in {"completed", "failed"}:
                return operation
            if operation.state == "queued":
                conn.execute(
                    """UPDATE practice_generation_operations
                       SET state = 'failed', error_code = 'interrupted',
                           cancel_requested_at = ?, cancelled_at = ?,
                           completed_at = ?, updated_at = ?
                       WHERE id = ? AND state = 'queued'""",
                    (now, now, now, now, operation_id),
                )
            else:
                conn.execute(
                    """UPDATE practice_generation_operations
                       SET cancel_requested_at = COALESCE(cancel_requested_at, ?),
                           updated_at = ?
                       WHERE id = ? AND state = 'running'""",
                    (now, now, operation_id),
                )
            row = self._owned_operation_row(conn, course_id, operation_id)
        return self._operation_from_row(row)

    def claim_operation(self, course_id: str, operation_id: str) -> tuple[PracticeGenerationOperation, bool]:
        """Atomically claim queued work; another running worker never duplicates it."""
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._owned_operation_row(conn, course_id, operation_id)
            operation = self._operation_from_row(row)
            if operation.state != "queued":
                return operation, False
            result = conn.execute(
                """UPDATE practice_generation_operations
                   SET state = 'running', started_at = ?, updated_at = ?
                   WHERE id = ? AND state = 'queued'""", (now, now, operation_id)
            )
            if result.rowcount != 1:
                row = self._owned_operation_row(conn, course_id, operation_id)
                return self._operation_from_row(row), False
            row = self._owned_operation_row(conn, course_id, operation_id)
        return self._operation_from_row(row), True

    def complete_operation(
        self,
        course_id: str,
        operation_id: str,
        output: GeneratedPracticeOutput,
        *,
        account_active: bool,
        material_receipts: list[PracticeSourceReceipt],
    ) -> PracticeGenerationOperation:
        """Publish all generated questions and readiness in one SQLite transaction."""
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            operation = self._operation_from_row(self._owned_operation_row(conn, course_id, operation_id))
            if operation.state == "completed":
                return operation
            if operation.state != "running":
                raise CourseConflictError("Generation operation is not running")
            if operation.cancel_requested_at is not None:
                conn.execute(
                    """UPDATE practice_generation_operations
                       SET state = 'failed', error_code = 'interrupted',
                           cancelled_at = ?, completed_at = ?, updated_at = ?
                       WHERE id = ? AND state = 'running'""",
                    (now, now, now, operation.id),
                )
                row = self._owned_operation_row(conn, course_id, operation.id)
                return self._operation_from_row(row)
            if not account_active:
                raise CourseConflictError("Generation account authority is no longer active")
            self._course_for_write(conn, course_id, operation.course_write_epoch)
            set_record = self._set_from_row(self._owned_set_row(conn, course_id, operation.practice_set_id))
            if set_record.mode != "generated" or set_record.state != "draft" or set_record.write_epoch != operation.practice_set_write_epoch:
                raise CourseConflictError("Practice generation authority is stale")
            revision_row = conn.execute(
                """SELECT * FROM practice_set_revisions WHERE id = ? AND practice_set_id = ?""",
                (operation.practice_set_revision_id, operation.practice_set_id),
            ).fetchone()
            if revision_row is None:
                raise self._not_found()
            revision = self._revision_from_row(revision_row)
            if revision.state != "draft" or [item.model_dump() for item in revision.source_snapshot] != [item.model_dump() for item in operation.source_snapshot]:
                raise CourseConflictError("Practice generation revision is stale")
            self._verify_snapshot(conn, course_id, operation.source_snapshot)
            self._validate_output(operation, output, material_receipts=material_receipts)
            for ordinal, question in enumerate(output.questions, 1):
                conn.execute(
                    """INSERT INTO practice_questions
                       (id, practice_set_revision_id, question_type, prompt, answer_contract_json,
                        explanation, objective_ids_json, citation_json, ordinal, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (_question_id(), operation.practice_set_revision_id, question.question_type,
                     question.prompt, self._json(question.answer_contract.model_dump()), question.explanation,
                     self._json(question.objective_ids), self._json([item.model_dump() for item in question.citations]),
                     ordinal, now),
                )
            receipt = self._json({
                "operation_id": operation.id,
                "provider": output.provider_label,
                "request_contract_id": (
                    output.request_contract.request_contract_id
                    if output.request_contract is not None
                    else None
                ),
                "requested_objective_ids_json": (
                    self._json(output.request_contract.requested_objective_ids)
                    if output.request_contract is not None
                    else None
                ),
                "source_scope_hash": (
                    output.request_contract.source_scope_hash
                    if output.request_contract is not None
                    else None
                ),
                "generation_purpose": (
                    output.request_contract.generation_purpose
                    if output.request_contract is not None
                    else None
                ),
                "outcome": output.outcome,
                "abstain_reason": output.abstain_reason,
                "requested_model": output.requested_model,
                "actual_model": output.actual_model,
                "request_id": output.request_id,
                "input_tokens": output.input_tokens,
                "cached_input_tokens": output.cached_input_tokens,
                "output_tokens": output.output_tokens,
                "reasoning_output_tokens": output.reasoning_output_tokens,
                "estimated_cost_microusd": output.estimated_cost_microusd,
                "pricing_version": output.pricing_version,
                "prompt_version": output.prompt_version,
                "schema_version": output.schema_version,
                "reasoning_effort": output.reasoning_effort,
                "store": output.store,
                "response_status": output.response_status,
                "latency_ms": output.latency_ms,
                "quality_profile": operation.quality_profile,
                "content_quality": "passed" if operation.quality_profile == "c3-biology-v1" else "not-run",
                "source_count": len(operation.source_snapshot),
                "item_count": len(output.questions),
                "timing_mode": operation.timing_mode,
            })
            # The schema intentionally permits only one ready revision.  Move
            # the previous immutable authority to historical superseded state
            # before publishing this complete successor, all in one commit.
            conn.execute(
                """UPDATE practice_set_revisions
                   SET state = 'superseded'
                   WHERE practice_set_id = ? AND id != ? AND state = 'ready'""",
                (operation.practice_set_id, operation.practice_set_revision_id),
            )
            conn.execute(
                """UPDATE practice_set_revisions
                   SET generation_receipt_json = ?, state = 'ready', ready_at = ?
                   WHERE id = ? AND state = 'draft'""",
                (receipt, now, operation.practice_set_revision_id),
            )
            conn.execute(
                """UPDATE practice_sets
                   SET current_revision_id = ?, revision = revision + 1, write_epoch = write_epoch + 1,
                       updated_at = ? WHERE id = ? AND write_epoch = ? AND state = 'draft'""",
                (operation.practice_set_revision_id, now, operation.practice_set_id, operation.practice_set_write_epoch),
            )
            result = conn.execute(
                """UPDATE practice_generation_operations
                   SET state = 'completed', completed_at = ?, updated_at = ?
                   WHERE id = ? AND state = 'running'""", (now, now, operation.id)
            )
            if result.rowcount != 1:
                raise CourseConflictError("Generation operation is stale")
            row = self._owned_operation_row(conn, course_id, operation.id)
        return self._operation_from_row(row)

    @staticmethod
    def _validate_output(
        operation: PracticeGenerationOperation,
        output: GeneratedPracticeOutput,
        *,
        material_receipts: list[PracticeSourceReceipt],
    ) -> None:
        if len(CoursePracticeGenerationRepository._json(output.model_dump()).encode("utf-8")) > _MAX_GENERATED_OUTPUT_BYTES:
            raise ValueError("Generated output exceeds the aggregate limit")
        if not output.questions or len(output.questions) > operation.item_limit:
            raise ValueError("Generated question count is invalid")
        snapshot = {(item.source_id, item.source_revision, item.content_sha256) for item in operation.source_snapshot}
        material = {(item.source_id, item.source_revision, item.content_sha256) for item in material_receipts}
        if not material or not material.issubset(snapshot):
            raise ValueError("Generated source material does not resolve to the frozen snapshot")
        for question in output.questions:
            if not question.citations:
                raise ValueError("Generated Practice questions require citations")
            if any((item.source_id, item.source_revision, item.content_sha256) not in snapshot for item in question.citations):
                raise ValueError("Generated citation does not resolve to the frozen source snapshot")
            if any((item.source_id, item.source_revision, item.content_sha256) not in material for item in question.citations):
                raise ValueError("Generated citation does not resolve to retrieved source material")
            if any(item not in operation.objective_ids for item in question.objective_ids):
                raise ValueError("Generated objective does not resolve to the request")

    def fail_operation(self, course_id: str, operation_id: str, error_code: str) -> PracticeGenerationOperation:
        if error_code not in {
            "provider_unavailable", "provider_failed", "invalid_output",
            "source_changed", "authority_changed", "interrupted", "provider_timed_out",
        }:
            raise ValueError("invalid generation failure code")
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            operation = self._operation_from_row(self._owned_operation_row(conn, course_id, operation_id))
            if operation.state in {"completed", "failed"}:
                return operation
            cancelled = operation.cancel_requested_at is not None
            result = conn.execute(
                """UPDATE practice_generation_operations
                   SET state = 'failed', error_code = ?, completed_at = ?,
                       cancelled_at = CASE WHEN ? THEN ? ELSE cancelled_at END,
                       updated_at = ?
                   WHERE id = ? AND state IN ('queued', 'running')""",
                (
                    "interrupted" if cancelled else error_code,
                    now,
                    int(cancelled),
                    now,
                    now,
                    operation_id,
                ),
            )
            if result.rowcount != 1:
                raise CourseConflictError("Generation operation is stale")
            row = self._owned_operation_row(conn, course_id, operation_id)
        return self._operation_from_row(row)

    def reconcile_orphaned_operations(self, course_id: str, *, live_operation_ids: set[str]) -> int:
        """Terminalize restart-orphaned rows; SQLite state remains authoritative."""
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self.course_repository.get_course(course_id)
            rows = conn.execute(
                """SELECT id FROM practice_generation_operations
                   WHERE course_id = ? AND owner_user_id = ? AND state IN ('queued', 'running')""",
                (course_id, self.owner_user_id),
            ).fetchall()
            abandoned = [str(row["id"]) for row in rows if str(row["id"]) not in live_operation_ids]
            if not abandoned:
                return 0
            placeholders = ",".join("?" for _ in abandoned)
            now = time.time()
            conn.execute(
                f"""UPDATE practice_generation_operations
                    SET state = 'failed', error_code = 'interrupted', completed_at = ?, updated_at = ?
                    WHERE id IN ({placeholders}) AND state IN ('queued', 'running')""",
                [now, now, *abandoned],
            )
        return len(abandoned)
