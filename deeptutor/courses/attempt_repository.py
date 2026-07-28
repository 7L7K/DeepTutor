"""Course-rooted persistence for resumable immutable-revision quiz attempts."""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
import sqlite3
import time
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from .attempt_models import (
    AttemptItemPresentation,
    QuizAttempt,
    QuizAttemptAnswer,
    QuizAttemptItem,
    QuizAttemptView,
)
from .models import Course
from .practice_models import PracticeQuestion, PracticeSet
from .repository import CourseConflictError, CourseNotFoundError, CourseRepository

_MAX_JSON_BYTES = 16_384
_MAX_ITEMS = 256


def _attempt_id() -> str:
    return f"att_{uuid4().hex}"


def _attempt_item_id() -> str:
    return f"ati_{uuid4().hex}"


class CourseAssessmentRepository:
    """Persist attempts using the parent Course repository's DB and lock."""

    def __init__(self, course_repository: CourseRepository) -> None:
        self.course_repository = course_repository

    @property
    def owner_user_id(self) -> str:
        return self.course_repository.owner_user_id

    @staticmethod
    def _not_found() -> CourseNotFoundError:
        return CourseNotFoundError("Assessment resource not found")

    @staticmethod
    def _json(value: Any, *, field: str, maximum: int = _MAX_JSON_BYTES) -> str:
        try:
            encoded = json.dumps(
                value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must contain strict JSON values") from exc
        if len(encoded.encode("utf-8")) > maximum:
            raise ValueError(f"{field} is too large")
        return encoded

    @staticmethod
    def _attempt_from_row(row: sqlite3.Row) -> QuizAttempt:
        payload = dict(row)
        score_json = payload.pop("score_json")
        payload["score"] = json.loads(score_json) if score_json else None
        return QuizAttempt.model_validate(payload)

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> QuizAttemptItem:
        payload = dict(row)
        for column, field in (
            ("option_order_json", "option_order"),
            ("randomized_values_json", "randomized_values"),
            ("grading_json", "grading"),
        ):
            raw_value = payload.pop(column)
            payload[field] = json.loads(raw_value) if raw_value else None
        return QuizAttemptItem.model_validate(payload)

    @staticmethod
    def _answer_from_row(row: sqlite3.Row) -> QuizAttemptAnswer:
        payload = dict(row)
        response_json = payload.pop("response_json")
        payload["response"] = json.loads(response_json) if response_json else None
        return QuizAttemptAnswer.model_validate(payload)

    def _course_for_write(
        self, conn: sqlite3.Connection, course_id: str, expected_course_write_epoch: int
    ) -> Course:
        row = conn.execute(
            "SELECT * FROM courses WHERE id = ? AND owner_user_id = ?",
            (course_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        course = Course.model_validate(dict(row))
        if course.state != "active":
            raise CourseConflictError("Archived courses cannot change attempts")
        if course.write_epoch != expected_course_write_epoch:
            raise CourseConflictError("Course write epoch is stale")
        return course

    def _set_for_write(
        self,
        conn: sqlite3.Connection,
        course_id: str,
        practice_set_id: str,
        expected_practice_set_write_epoch: int,
    ) -> PracticeSet:
        row = conn.execute(
            """SELECT practice_sets.* FROM practice_sets
               JOIN courses ON courses.id = practice_sets.course_id
               WHERE practice_sets.id = ? AND practice_sets.course_id = ?
                 AND courses.owner_user_id = ?""",
            (practice_set_id, course_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        practice_set = PracticeSet.model_validate(dict(row))
        if practice_set.state != "draft":
            raise CourseConflictError("Archived Practice sets cannot change attempts")
        if practice_set.write_epoch != expected_practice_set_write_epoch:
            raise CourseConflictError("Practice write epoch is stale")
        return practice_set

    def _attempt_row(
        self, conn: sqlite3.Connection, course_id: str, practice_set_id: str, attempt_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            """SELECT attempts.* FROM quiz_attempts AS attempts
               JOIN courses ON courses.id = attempts.course_id
               WHERE attempts.id = ? AND attempts.course_id = ?
                 AND attempts.practice_set_id = ? AND attempts.owner_user_id = ?
                 AND courses.owner_user_id = ?""",
            (attempt_id, course_id, practice_set_id, self.owner_user_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        return row

    def _write_attempt(
        self,
        conn: sqlite3.Connection,
        course_id: str,
        practice_set_id: str,
        attempt_id: str,
        *,
        expected_course_write_epoch: int,
        expected_practice_set_write_epoch: int,
    ) -> QuizAttempt:
        attempt = self._attempt_from_row(
            self._attempt_row(conn, course_id, practice_set_id, attempt_id)
        )
        self._course_for_write(conn, course_id, expected_course_write_epoch)
        self._set_for_write(conn, course_id, practice_set_id, expected_practice_set_write_epoch)
        if (
            attempt.course_write_epoch != expected_course_write_epoch
            or attempt.practice_set_write_epoch != expected_practice_set_write_epoch
        ):
            raise CourseConflictError("Attempt authority epoch is stale")
        return attempt

    @staticmethod
    def _presentations(
        questions: list[PracticeQuestion], item_presentations: Iterable[AttemptItemPresentation | dict[str, Any]]
    ) -> list[AttemptItemPresentation]:
        if isinstance(item_presentations, (str, bytes)):
            raise ValueError("item_presentations must be a list")
        try:
            supplied = list(item_presentations)
        except TypeError as exc:
            raise ValueError("item_presentations must be a list") from exc
        if len(questions) > _MAX_ITEMS:
            raise ValueError("Practice revision has too many questions")
        if not supplied:
            return [AttemptItemPresentation(question_id=item.id, display_ordinal=index) for index, item in enumerate(questions, 1)]
        if len(supplied) != len(questions):
            raise ValueError("item_presentations must cover each revision question exactly once")
        try:
            presentations = [AttemptItemPresentation.model_validate(item) for item in supplied]
        except ValidationError as exc:
            raise ValueError("item_presentations are invalid") from exc
        question_ids = {item.id for item in questions}
        if {item.question_id for item in presentations} != question_ids or len({item.question_id for item in presentations}) != len(presentations):
            raise ValueError("item_presentations must only describe server-derived revision questions")
        authoritative_ordinals = {question.id: question.ordinal for question in questions}
        # A client may enumerate rendering metadata in any order, but it cannot
        # choose the attempt order.  Store metadata under the immutable server
        # question identity and restore the revision's ordinal below.
        presentations = [
            presentation.model_copy(
                update={"display_ordinal": authoritative_ordinals[presentation.question_id]}
            )
            for presentation in presentations
        ]
        for presentation in presentations:
            if presentation.option_order is not None:
                if len(presentation.option_order) > _MAX_ITEMS or any(not value or len(value) > 500 for value in presentation.option_order):
                    raise ValueError("option_order is invalid")
                CourseAssessmentRepository._json(presentation.option_order, field="option_order")
            if presentation.randomized_values is not None:
                CourseAssessmentRepository._json(presentation.randomized_values, field="randomized_values")
        return presentations

    def _view(self, conn: sqlite3.Connection, attempt: QuizAttempt) -> QuizAttemptView:
        items = [self._item_from_row(row) for row in conn.execute(
            "SELECT * FROM quiz_attempt_items WHERE attempt_id = ? ORDER BY display_ordinal, id", (attempt.id,)
        ).fetchall()]
        answers = [self._answer_from_row(row) for row in conn.execute(
            """SELECT answers.* FROM quiz_attempt_answers AS answers
               JOIN quiz_attempt_items AS items ON items.id = answers.attempt_item_id
               WHERE items.attempt_id = ? ORDER BY items.display_ordinal, items.id""",
            (attempt.id,),
        ).fetchall()]
        return QuizAttemptView(attempt=attempt, items=items, answers=answers)

    @staticmethod
    def _question_from_row(row: sqlite3.Row) -> PracticeQuestion:
        payload = dict(row)
        payload["answer_contract"] = json.loads(payload.pop("answer_contract_json"))
        payload["objective_ids"] = json.loads(payload.pop("objective_ids_json") or "[]")
        payload["citations"] = json.loads(payload.pop("citation_json") or "[]")
        return PracticeQuestion.model_validate(payload)

    def start_or_resume_attempt(
        self,
        course_id: str,
        practice_set_id: str,
        practice_set_revision_id: str,
        *,
        expected_course_write_epoch: int,
        expected_practice_set_write_epoch: int,
        item_presentations: Iterable[AttemptItemPresentation | dict[str, Any]] = (),
    ) -> QuizAttemptView:
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            practice_set = self._set_for_write(conn, course_id, practice_set_id, expected_practice_set_write_epoch)
            if practice_set.current_revision_id != practice_set_revision_id:
                raise self._not_found()
            revision = conn.execute(
                """SELECT id, state FROM practice_set_revisions
                   WHERE id = ? AND practice_set_id = ?""",
                (practice_set_revision_id, practice_set_id),
            ).fetchone()
            if revision is None or str(revision["state"]) != "ready":
                raise self._not_found()
            existing = conn.execute(
                """SELECT * FROM quiz_attempts WHERE owner_user_id = ?
                   AND practice_set_revision_id = ? AND state = 'in_progress'""",
                (self.owner_user_id, practice_set_revision_id),
            ).fetchone()
            if existing is not None:
                attempt = self._attempt_from_row(existing)
                if attempt.course_id != course_id or attempt.practice_set_id != practice_set_id:
                    raise self._not_found()
                if (
                    attempt.course_write_epoch != expected_course_write_epoch
                    or attempt.practice_set_write_epoch != expected_practice_set_write_epoch
                ):
                    raise CourseConflictError("Attempt authority epoch is stale")
                return self._view(conn, attempt)
            rows = conn.execute(
                "SELECT * FROM practice_questions WHERE practice_set_revision_id = ? ORDER BY ordinal, id",
                (practice_set_revision_id,),
            ).fetchall()
            questions = [self._question_from_row(row) for row in rows]
            if not questions:
                raise CourseConflictError("Ready Practice revision has no questions")
            presentations = self._presentations(questions, item_presentations)
            attempt_id = _attempt_id()
            conn.execute(
                """INSERT INTO quiz_attempts
                   (id, owner_user_id, course_id, practice_set_id, practice_set_revision_id,
                    state, score_json, revision, course_write_epoch, practice_set_write_epoch,
                    started_at, submitted_at, graded_at, archived_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'in_progress', NULL, 1, ?, ?, ?, NULL, NULL, NULL, ?)""",
                (attempt_id, self.owner_user_id, course_id, practice_set_id, practice_set_revision_id,
                 expected_course_write_epoch, expected_practice_set_write_epoch, now, now),
            )
            for presentation in presentations:
                item_id = _attempt_item_id()
                option_order_json = self._json(presentation.option_order, field="option_order") if presentation.option_order is not None else None
                values_json = self._json(presentation.randomized_values, field="randomized_values") if presentation.randomized_values is not None else None
                conn.execute(
                    """INSERT INTO quiz_attempt_items
                       (id, attempt_id, question_id, display_ordinal, option_order_json,
                        randomized_values_json, grading_json, error_type, graded_at)
                       VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL)""",
                    (item_id, attempt_id, presentation.question_id, presentation.display_ordinal, option_order_json, values_json),
                )
                conn.execute(
                    """INSERT INTO quiz_attempt_answers
                       (attempt_item_id, response_json, revision, answered_at)
                       VALUES (?, NULL, 1, NULL)""", (item_id,)
                )
            row = conn.execute("SELECT * FROM quiz_attempts WHERE id = ?", (attempt_id,)).fetchone()
            assert row is not None
            return self._view(conn, self._attempt_from_row(row))

    def get_attempt(self, course_id: str, practice_set_id: str, attempt_id: str) -> QuizAttemptView:
        with self.course_repository._connect() as conn:
            return self._view(conn, self._attempt_from_row(self._attempt_row(conn, course_id, practice_set_id, attempt_id)))

    def list_attempts(self, course_id: str, practice_set_id: str, *, include_archived: bool = True) -> list[QuizAttempt]:
        with self.course_repository._connect() as conn:
            self._attempt_row_or_set(conn, course_id, practice_set_id)
            sql = "SELECT * FROM quiz_attempts WHERE course_id = ? AND practice_set_id = ? AND owner_user_id = ?"
            params: list[Any] = [course_id, practice_set_id, self.owner_user_id]
            if not include_archived:
                sql += " AND state != 'archived'"
            sql += " ORDER BY updated_at DESC, id"
            return [self._attempt_from_row(row) for row in conn.execute(sql, params).fetchall()]

    def _attempt_row_or_set(self, conn: sqlite3.Connection, course_id: str, practice_set_id: str) -> None:
        row = conn.execute(
            """SELECT 1 FROM practice_sets JOIN courses ON courses.id = practice_sets.course_id
               WHERE practice_sets.id = ? AND practice_sets.course_id = ? AND courses.owner_user_id = ?""",
            (practice_set_id, course_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()

    def autosave_answer(
        self,
        course_id: str,
        practice_set_id: str,
        attempt_id: str,
        attempt_item_id: str,
        *,
        response: Any,
        expected_answer_revision: int,
        idempotency_token: str,
        expected_course_write_epoch: int,
        expected_practice_set_write_epoch: int,
    ) -> QuizAttemptAnswer:
        if not isinstance(idempotency_token, str) or not idempotency_token.strip() or len(idempotency_token) > 160:
            raise ValueError("idempotency_token is required and bounded")
        response_json = self._json(response, field="response")
        payload_sha256 = hashlib.sha256(
            self._json({"attempt_item_id": attempt_item_id, "response": response, "expected_answer_revision": expected_answer_revision}, field="autosave payload").encode()
        ).hexdigest()
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            attempt = self._write_attempt(conn, course_id, practice_set_id, attempt_id,
                expected_course_write_epoch=expected_course_write_epoch,
                expected_practice_set_write_epoch=expected_practice_set_write_epoch)
            receipt = conn.execute(
                """SELECT * FROM quiz_attempt_autosave_receipts
                   WHERE attempt_id = ? AND idempotency_token = ?""", (attempt_id, idempotency_token)
            ).fetchone()
            if receipt is not None:
                if str(receipt["attempt_item_id"]) != attempt_item_id or str(receipt["payload_sha256"]) != payload_sha256:
                    raise CourseConflictError("Autosave idempotency token payload conflicts")
                return QuizAttemptAnswer(
                    attempt_item_id=attempt_item_id,
                    response=json.loads(str(receipt["response_json"])),
                    revision=int(receipt["answer_revision"]),
                    answered_at=float(receipt["answered_at"]),
                )
            if attempt.state != "in_progress":
                raise CourseConflictError("Quiz attempt answers are frozen")
            item = conn.execute(
                "SELECT * FROM quiz_attempt_items WHERE id = ? AND attempt_id = ?", (attempt_item_id, attempt_id)
            ).fetchone()
            if item is None:
                raise self._not_found()
            result = conn.execute(
                """UPDATE quiz_attempt_answers SET response_json = ?, revision = revision + 1, answered_at = ?
                   WHERE attempt_item_id = ? AND revision = ?""",
                (response_json, now, attempt_item_id, expected_answer_revision),
            )
            if result.rowcount != 1:
                raise CourseConflictError("Answer revision is stale")
            row = conn.execute("SELECT * FROM quiz_attempt_answers WHERE attempt_item_id = ?", (attempt_item_id,)).fetchone()
            assert row is not None
            answer = self._answer_from_row(row)
            conn.execute(
                """INSERT INTO quiz_attempt_autosave_receipts
                   (attempt_id, idempotency_token, attempt_item_id, payload_sha256,
                    response_json, answer_revision, answered_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    attempt_id,
                    idempotency_token,
                    attempt_item_id,
                    payload_sha256,
                    response_json,
                    answer.revision,
                    answer.answered_at,
                    now,
                ),
            )
            conn.execute("UPDATE quiz_attempts SET revision = revision + 1, updated_at = ? WHERE id = ?", (now, attempt_id))
            return answer

    def submit_attempt(self, course_id: str, practice_set_id: str, attempt_id: str, *, expected_course_write_epoch: int, expected_practice_set_write_epoch: int) -> QuizAttempt:
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            attempt = self._write_attempt(conn, course_id, practice_set_id, attempt_id,
                expected_course_write_epoch=expected_course_write_epoch,
                expected_practice_set_write_epoch=expected_practice_set_write_epoch)
            if attempt.state == "submitted":
                return attempt
            if attempt.state != "in_progress":
                raise CourseConflictError("Quiz attempt is terminal")
            conn.execute(
                """UPDATE quiz_attempts SET state = 'submitted', submitted_at = ?, revision = revision + 1, updated_at = ?
                   WHERE id = ? AND state = 'in_progress'""", (now, now, attempt_id)
            )
            row = conn.execute("SELECT * FROM quiz_attempts WHERE id = ?", (attempt_id,)).fetchone()
            assert row is not None
            return self._attempt_from_row(row)

    def abandon_attempt(self, course_id: str, practice_set_id: str, attempt_id: str, *, expected_course_write_epoch: int, expected_practice_set_write_epoch: int) -> QuizAttempt:
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            attempt = self._write_attempt(conn, course_id, practice_set_id, attempt_id,
                expected_course_write_epoch=expected_course_write_epoch,
                expected_practice_set_write_epoch=expected_practice_set_write_epoch)
            if attempt.state == "abandoned":
                return attempt
            if attempt.state != "in_progress":
                raise CourseConflictError("Quiz attempt is terminal")
            conn.execute(
                "UPDATE quiz_attempts SET state = 'abandoned', revision = revision + 1, updated_at = ? WHERE id = ?",
                (now, attempt_id),
            )
            row = conn.execute("SELECT * FROM quiz_attempts WHERE id = ?", (attempt_id,)).fetchone()
            assert row is not None
            return self._attempt_from_row(row)
