"""SQLite-authoritative deterministic grading and recoverable projection outbox."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any
import unicodedata
from uuid import uuid4

from .attempt_models import QuizAttempt
from .attempt_repository import CourseAssessmentRepository
from .grading_models import GradingEvidence
from .practice_models import ExactAnswerContract
from .repository import CourseConflictError, CourseNotFoundError, CourseRepository

_MAX_EVIDENCE_RECORDS_PER_ATTEMPT = 4_096
_MAX_EVIDENCE_BYTES_PER_ATTEMPT = 2 * 1024 * 1024


def _evidence_id() -> str:
    return f"grd_{uuid4().hex}"


class CourseGradingRepository:
    """Finalize a submitted attempt and enqueue immutable delivery evidence together."""

    def __init__(self, course_repository: CourseRepository) -> None:
        self.course_repository = course_repository
        self._attempts = CourseAssessmentRepository(course_repository)

    @property
    def owner_user_id(self) -> str:
        return self.course_repository.owner_user_id

    @staticmethod
    def _not_found() -> CourseNotFoundError:
        return CourseNotFoundError("Assessment resource not found")

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _digest(cls, value: dict[str, Any]) -> str:
        return hashlib.sha256(cls._json(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _response(value: Any) -> str:
        if not (isinstance(value, dict) and set(value) == {"answer"} and isinstance(value["answer"], str)):
            raise ValueError("Exact-answer response must be exactly {'answer': string}")
        if len(value["answer"]) > 4_000:
            raise ValueError("Exact-answer response is too large")
        return value["answer"]

    @staticmethod
    def _exact(answer: str, expected: str) -> bool:
        def normalize(value: str) -> str:
            return unicodedata.normalize("NFC", value).strip().casefold()

        return normalize(answer) == normalize(expected)

    @staticmethod
    def _evidence_from_row(row: sqlite3.Row) -> GradingEvidence:
        payload = dict(row)
        payload["is_correct"] = bool(payload["is_correct"])
        payload["grading"] = json.loads(payload.pop("grading_json"))
        response_json = payload.pop("response_json", None)
        payload["response"] = json.loads(response_json) if response_json else None
        return GradingEvidence.model_validate(payload)

    def _attempt_for_grade(
        self, conn: sqlite3.Connection, course_id: str, practice_set_id: str, attempt_id: str,
        *, expected_course_write_epoch: int, expected_practice_set_write_epoch: int,
    ) -> QuizAttempt:
        attempt = self._attempts._write_attempt(
            conn, course_id, practice_set_id, attempt_id,
            expected_course_write_epoch=expected_course_write_epoch,
            expected_practice_set_write_epoch=expected_practice_set_write_epoch,
        )
        if attempt.state not in {"submitted", "graded"}:
            raise CourseConflictError("Only submitted quiz attempts can be graded")
        return attempt

    def collect_objective_ids(
        self, course_id: str, practice_set_id: str, attempt_id: str,
        *, expected_course_write_epoch: int, expected_practice_set_write_epoch: int,
    ) -> set[str]:
        with self.course_repository._connect() as conn:
            self._attempt_for_grade(
                conn, course_id, practice_set_id, attempt_id,
                expected_course_write_epoch=expected_course_write_epoch,
                expected_practice_set_write_epoch=expected_practice_set_write_epoch,
            )
            rows = conn.execute(
                """SELECT questions.objective_ids_json
                   FROM quiz_attempt_items AS items
                   JOIN practice_questions AS questions ON questions.id = items.question_id
                   WHERE items.attempt_id = ?""", (attempt_id,)
            ).fetchall()
        return {item for row in rows for item in json.loads(row["objective_ids_json"] or "[]")}

    def grade(
        self, course_id: str, practice_set_id: str, attempt_id: str,
        *, objective_mapping: dict[str, tuple[str, str] | None],
        expected_course_write_epoch: int, expected_practice_set_write_epoch: int,
    ) -> tuple[QuizAttempt, list[GradingEvidence]]:
        """Atomically seal evidence, item results, score, and attempt state in SQLite."""
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            attempt = self._attempt_for_grade(
                conn, course_id, practice_set_id, attempt_id,
                expected_course_write_epoch=expected_course_write_epoch,
                expected_practice_set_write_epoch=expected_practice_set_write_epoch,
            )
            if attempt.state == "graded":
                return attempt, self._records(conn, attempt_id)
            rows = conn.execute(
                """SELECT items.id AS attempt_item_id, items.question_id, items.display_ordinal,
                          answers.response_json, questions.answer_contract_json,
                          questions.objective_ids_json
                   FROM quiz_attempt_items AS items
                   JOIN quiz_attempt_answers AS answers ON answers.attempt_item_id = items.id
                   JOIN practice_questions AS questions ON questions.id = items.question_id
                   WHERE items.attempt_id = ? ORDER BY items.display_ordinal, items.id""",
                (attempt_id,),
            ).fetchall()
            if not rows or any(row["response_json"] is None for row in rows):
                raise CourseConflictError("Submitted quiz attempts require every answer before grading")
            # Build and bound the complete evidence plan before inserting any
            # evidence.  Attempts are immutable history, so admission control
            # must reject an oversized aggregate rather than relying on later
            # deletion or a partially-written grade.
            planned_evidence: list[
                tuple[str, dict[str, Any], str, bool, str | None, str | None, str, str]
            ] = []
            item_results: list[tuple[str, bool, str | None, list[str]]] = []
            planned_bytes = 0
            for row in rows:
                contract = ExactAnswerContract.model_validate(json.loads(row["answer_contract_json"]))
                raw_response = json.loads(row["response_json"])
                response = self._response(raw_response)
                is_correct = self._exact(response, contract.answer)
                error_type = None if is_correct else ("metacognitive" if not response.strip() else "application")
                contract_sha = self._digest(contract.model_dump())
                response_sha = self._digest(raw_response)
                objectives = sorted(json.loads(row["objective_ids_json"] or "[]") or [""])
                evidence_ids: list[str] = []
                for objective_id in objectives:
                    mapping = objective_mapping.get(objective_id) if objective_id else None
                    module_id, knowledge_type = mapping if mapping else (None, None)
                    state = "pending" if mapping else "unmapped"
                    payload = {
                        "algorithm": "exact-v1", "attempt_id": attempt_id,
                        "attempt_item_id": row["attempt_item_id"], "question_id": row["question_id"],
                        "objective_id": objective_id, "module_id": module_id,
                        "knowledge_type": knowledge_type, "contract_sha256": contract_sha,
                        "response_sha256": response_sha, "is_correct": is_correct,
                        "error_type": error_type,
                    }
                    evidence_id = _evidence_id()
                    grading_json = self._json(payload)
                    planned_evidence.append((
                        evidence_id, payload, grading_json, is_correct, error_type,
                        module_id, knowledge_type, state,
                    ))
                    planned_bytes += len(grading_json.encode("utf-8"))
                    evidence_ids.append(evidence_id)
                item_results.append((row["attempt_item_id"], is_correct, error_type, evidence_ids))
            retained_count, retained_bytes = conn.execute(
                """SELECT COUNT(*), COALESCE(SUM(length(CAST(grading_json AS BLOB))), 0)
                   FROM quiz_item_grading_evidence WHERE attempt_id = ?""",
                (attempt_id,),
            ).fetchone()
            if int(retained_count) + len(planned_evidence) > _MAX_EVIDENCE_RECORDS_PER_ATTEMPT:
                raise CourseConflictError("Quiz attempt exceeds its grading evidence record limit")
            if int(retained_bytes) + planned_bytes > _MAX_EVIDENCE_BYTES_PER_ATTEMPT:
                raise CourseConflictError("Quiz attempt exceeds its grading evidence byte limit")
            for (
                evidence_id,
                payload,
                grading_json,
                is_correct,
                error_type,
                module_id,
                knowledge_type,
                state,
            ) in planned_evidence:
                objective_id = str(payload["objective_id"])
                conn.execute(
                    """INSERT INTO quiz_item_grading_evidence
                       (id, owner_user_id, course_id, practice_set_id, attempt_id,
                        attempt_item_id, question_id, objective_id, module_id, knowledge_type,
                        algorithm, payload_sha256, is_correct, grading_json, error_type,
                        state, created_at, applied_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'exact-v1', ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        evidence_id, self.owner_user_id, course_id, practice_set_id, attempt_id,
                        payload["attempt_item_id"], payload["question_id"], objective_id, module_id,
                        knowledge_type, self._digest(payload), int(is_correct), grading_json,
                        error_type, state, now, now if state == "unmapped" else None,
                    ),
                )
            for item_id, is_correct, error_type, evidence_ids in item_results:
                conn.execute(
                    """UPDATE quiz_attempt_items SET grading_json = ?, error_type = ?, graded_at = ?
                       WHERE id = ? AND graded_at IS NULL""",
                    (self._json({"algorithm": "exact-v1", "is_correct": is_correct, "evidence_ids": evidence_ids}), error_type, now, item_id),
                )
            correct = sum(1 for _item_id, is_correct, _error, _ids in item_results if is_correct)
            score = {"correct": correct, "total": len(item_results), "fraction": correct / len(item_results)}
            conn.execute(
                """UPDATE quiz_attempts
                   SET state = 'graded', score_json = ?, graded_at = ?, revision = revision + 1, updated_at = ?
                   WHERE id = ? AND state = 'submitted'""",
                (self._json(score), now, now, attempt_id),
            )
            row = conn.execute("SELECT * FROM quiz_attempts WHERE id = ?", (attempt_id,)).fetchone()
            assert row is not None
            return self._attempts._attempt_from_row(row), self._records(conn, attempt_id)

    def prepare(self, course_id: str, practice_set_id: str, attempt_id: str, **kwargs: Any) -> list[GradingEvidence]:
        """Compatibility helper that seals grade authority without delivery.

        Public service callers always pass the learning map resolved before this
        SQLite transaction.  This low-level helper intentionally freezes any
        omitted mapping as unmapped rather than guessing a later projection.
        """
        objectives = self.collect_objective_ids(course_id, practice_set_id, attempt_id, **kwargs)
        _attempt, evidence = self.grade(
            course_id,
            practice_set_id,
            attempt_id,
            objective_mapping={objective: None for objective in objectives},
            **kwargs,
        )
        return evidence

    def _records(self, conn: sqlite3.Connection, attempt_id: str) -> list[GradingEvidence]:
        rows = conn.execute(
            """SELECT evidence.*, answers.response_json
               FROM quiz_item_grading_evidence AS evidence
               JOIN quiz_attempt_items AS items ON items.id = evidence.attempt_item_id
               JOIN quiz_attempt_answers AS answers ON answers.attempt_item_id = items.id
               WHERE evidence.attempt_id = ?
               ORDER BY items.display_ordinal, evidence.objective_id, evidence.id""", (attempt_id,)
        ).fetchall()
        return [self._evidence_from_row(row) for row in rows]

    def pending(self, course_id: str, practice_set_id: str, attempt_id: str) -> list[GradingEvidence]:
        with self.course_repository._connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM quiz_attempts
                   WHERE id = ? AND course_id = ? AND practice_set_id = ? AND owner_user_id = ?""",
                (attempt_id, course_id, practice_set_id, self.owner_user_id),
            ).fetchone()
            if row is None:
                raise self._not_found()
            return [item for item in self._records(conn, attempt_id) if item.state == "pending"]

    def remediation_scope(
        self, course_id: str, attempt_id: str
    ) -> tuple[str, list[str], list[str]]:
        """Resolve a graded attempt's missed objectives and source authority.

        The caller supplies only the opaque attempt ID. Ownership, Practice-set
        membership, grading state, missed items, and cited Course sources are
        all re-derived from the private Course database.
        """

        with self.course_repository._connect() as conn:
            attempt = conn.execute(
                """SELECT * FROM quiz_attempts
                   WHERE id = ? AND course_id = ? AND owner_user_id = ?""",
                (attempt_id, course_id, self.owner_user_id),
            ).fetchone()
            if attempt is None:
                raise self._not_found()
            if str(attempt["state"]) != "graded":
                raise CourseConflictError(
                    "Only graded quiz attempts can propose remediation flashcards"
                )
            rows = conn.execute(
                """SELECT evidence.objective_id, questions.citation_json
                   FROM quiz_item_grading_evidence AS evidence
                   JOIN practice_questions AS questions
                     ON questions.id = evidence.question_id
                   WHERE evidence.attempt_id = ? AND evidence.course_id = ?
                     AND evidence.owner_user_id = ? AND evidence.is_correct = 0
                   ORDER BY evidence.attempt_item_id, evidence.objective_id""",
                (attempt_id, course_id, self.owner_user_id),
            ).fetchall()
            if not rows:
                raise CourseConflictError(
                    "This quiz attempt has no missed answers to review"
                )
            objectives = sorted(
                {
                    str(row["objective_id"])
                    for row in rows
                    if str(row["objective_id"] or "").strip()
                }
            )
            source_ids: set[str] = set()
            for row in rows:
                for citation in json.loads(row["citation_json"] or "[]"):
                    source_id = citation.get("source_id")
                    if isinstance(source_id, str) and source_id.startswith("src_"):
                        source_ids.add(source_id)
            if not source_ids:
                revision = conn.execute(
                    """SELECT revisions.source_snapshot_json
                       FROM practice_set_revisions AS revisions
                       WHERE revisions.id = ? AND revisions.practice_set_id = ?""",
                    (
                        attempt["practice_set_revision_id"],
                        attempt["practice_set_id"],
                    ),
                ).fetchone()
                if revision is not None:
                    for receipt in json.loads(
                        revision["source_snapshot_json"] or "[]"
                    ):
                        source_id = receipt.get("source_id")
                        if isinstance(source_id, str) and source_id.startswith(
                            "src_"
                        ):
                            source_ids.add(source_id)
            if not source_ids:
                # Manual Practice questions predate citation authoring. They
                # may still propose remediation, but only from the Course's
                # current ready immutable sources resolved on the server.
                source_ids.update(
                    str(row["id"])
                    for row in conn.execute(
                        """SELECT id FROM course_sources
                           WHERE course_id = ? AND state = 'ready'
                           ORDER BY created_at, id""",
                        (course_id,),
                    ).fetchall()
                )
            if not source_ids:
                raise CourseConflictError(
                    "Missed answers have no grounded Course sources"
                )
            return str(attempt["practice_set_id"]), objectives, sorted(source_ids)

    def has_course_evidence(self, course_id: str) -> bool:
        """Return whether the owned Course has immutable grading history."""
        self.course_repository.get_course(course_id)
        with self.course_repository._connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM quiz_item_grading_evidence
                   WHERE course_id = ? AND owner_user_id = ? LIMIT 1""",
                (course_id, self.owner_user_id),
            ).fetchone()
        return row is not None

    def acknowledge_applied(
        self, course_id: str, practice_set_id: str, attempt_id: str, evidence_id: str,
        *, payload_sha256: str,
    ) -> GradingEvidence:
        """Ack post-commit delivery by immutable owner/evidence binding, even after archive."""
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT evidence.* FROM quiz_item_grading_evidence AS evidence
                   JOIN quiz_attempts AS attempts ON attempts.id = evidence.attempt_id
                   WHERE evidence.id = ? AND evidence.attempt_id = ? AND evidence.course_id = ?
                     AND evidence.practice_set_id = ? AND evidence.owner_user_id = ?
                     AND attempts.owner_user_id = ?""",
                (evidence_id, attempt_id, course_id, practice_set_id, self.owner_user_id, self.owner_user_id),
            ).fetchone()
            if row is None or str(row["payload_sha256"]) != payload_sha256:
                raise self._not_found()
            if row["state"] == "pending":
                conn.execute(
                    "UPDATE quiz_item_grading_evidence SET state = 'applied', applied_at = ? WHERE id = ?",
                    (now, evidence_id),
                )
                row = conn.execute("SELECT * FROM quiz_item_grading_evidence WHERE id = ?", (evidence_id,)).fetchone()
            assert row is not None
            return self._evidence_from_row(row)

    def acknowledge_applied_batch(
        self,
        course_id: str,
        practice_set_id: str,
        attempt_id: str,
        evidence_receipts: list[tuple[str, str]],
    ) -> list[GradingEvidence]:
        """Acknowledge one fully persisted learning projection atomically."""

        if not evidence_receipts:
            return []
        if len(evidence_receipts) > _MAX_EVIDENCE_RECORDS_PER_ATTEMPT:
            raise CourseConflictError("Quiz attempt exceeds its grading evidence record limit")
        if len({evidence_id for evidence_id, _digest in evidence_receipts}) != len(
            evidence_receipts
        ):
            raise CourseConflictError("Duplicate grading evidence acknowledgement")
        now = time.time()
        acknowledged: list[GradingEvidence] = []
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for evidence_id, payload_sha256 in evidence_receipts:
                row = conn.execute(
                    """SELECT evidence.* FROM quiz_item_grading_evidence AS evidence
                       JOIN quiz_attempts AS attempts ON attempts.id = evidence.attempt_id
                       WHERE evidence.id = ? AND evidence.attempt_id = ?
                         AND evidence.course_id = ? AND evidence.practice_set_id = ?
                         AND evidence.owner_user_id = ? AND attempts.owner_user_id = ?""",
                    (
                        evidence_id,
                        attempt_id,
                        course_id,
                        practice_set_id,
                        self.owner_user_id,
                        self.owner_user_id,
                    ),
                ).fetchone()
                if row is None or str(row["payload_sha256"]) != payload_sha256:
                    raise self._not_found()
                if row["state"] == "pending":
                    conn.execute(
                        """UPDATE quiz_item_grading_evidence
                           SET state = 'applied', applied_at = ? WHERE id = ?""",
                        (now, evidence_id),
                    )
                    row = conn.execute(
                        "SELECT * FROM quiz_item_grading_evidence WHERE id = ?",
                        (evidence_id,),
                    ).fetchone()
                assert row is not None
                acknowledged.append(self._evidence_from_row(row))
        return acknowledged

    # Compatibility inspection helper; grading is already final when this returns.
    def finalize(self, course_id: str, practice_set_id: str, attempt_id: str, **_kwargs: Any) -> QuizAttempt:
        with self.course_repository._connect() as conn:
            row = conn.execute(
                """SELECT * FROM quiz_attempts WHERE id = ? AND course_id = ?
                   AND practice_set_id = ? AND owner_user_id = ?""",
                (attempt_id, course_id, practice_set_id, self.owner_user_id),
            ).fetchone()
            if row is None:
                raise self._not_found()
            return self._attempts._attempt_from_row(row)


__all__ = ["CourseGradingRepository"]
