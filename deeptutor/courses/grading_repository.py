"""SQLite-authoritative deterministic grading and recoverable projection outbox."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter

from .assessment_grading import grade_assessment_response
from .attempt_models import QuizAttempt
from .attempt_repository import CourseAssessmentRepository
from .grading_models import GradingEvidence
from .practice_models import (
    PracticeAnswerContract,
    SingleChoiceAnswerContract,
    SingleChoiceOption,
)
from .repository import CourseConflictError, CourseNotFoundError, CourseRepository

_MAX_EVIDENCE_RECORDS_PER_ATTEMPT = 4_096
_MAX_EVIDENCE_BYTES_PER_ATTEMPT = 2 * 1024 * 1024
_ANSWER_CONTRACT_ADAPTER = TypeAdapter(PracticeAnswerContract)


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
    def _digest(cls, value: Any) -> str:
        return hashlib.sha256(cls._json(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _evidence_from_row(row: sqlite3.Row) -> GradingEvidence:
        payload = dict(row)
        payload["is_correct"] = bool(payload["is_correct"])
        payload["grading"] = json.loads(payload.pop("grading_json"))
        response_json = payload.pop("response_json", None)
        payload["response"] = json.loads(response_json) if response_json else None
        return GradingEvidence.model_validate(payload)

    @staticmethod
    def _content_quality_ledger_available(conn: sqlite3.Connection) -> bool:
        """Keep historical pre-C3 fixtures readable without weakening C3 DBs."""
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'practice_question_invalidations'"
            ).fetchone()
            is not None
        )

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
        if (
            attempt.state == "submitted"
            and self._attempts._invalidated_question_ids_for_attempt(conn, attempt_id)
        ):
            raise CourseConflictError("Attempt contains withdrawn questions")
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
            question_columns = {
                str(item["name"])
                for item in conn.execute("PRAGMA table_info(practice_questions)").fetchall()
            }
            options_projection = (
                "questions.options_json" if "options_json" in question_columns else "'[]'"
            )
            rows = conn.execute(
                f"""SELECT items.id AS attempt_item_id, items.question_id, items.display_ordinal,
                          items.option_order_json, answers.response_json,
                          questions.answer_contract_json,
                          {options_projection} AS options_json,
                          questions.objective_ids_json
                   FROM quiz_attempt_items AS items
                   LEFT JOIN quiz_attempt_answers AS answers ON answers.attempt_item_id = items.id
                   JOIN practice_questions AS questions ON questions.id = items.question_id
                   WHERE items.attempt_id = ? ORDER BY items.display_ordinal, items.id""",
                (attempt_id,),
            ).fetchall()
            if not rows or any(row["response_json"] is None for row in rows):
                raise CourseConflictError("Submitted quiz attempts require every answer before grading")
            invalidated_question_ids: set[str] = set()
            if self._content_quality_ledger_available(conn):
                invalidated_question_ids = {
                    str(item["question_id"])
                    for item in conn.execute(
                        """SELECT DISTINCT question_id FROM practice_question_invalidations
                           WHERE course_id = ? AND practice_set_id = ?""",
                        (course_id, practice_set_id),
                    ).fetchall()
                }
            # Build and bound the complete evidence plan before inserting any
            # evidence.  Attempts are immutable history, so admission control
            # must reject an oversized aggregate rather than relying on later
            # deletion or a partially-written grade.
            planned_evidence: list[
                tuple[str, dict[str, Any], str, bool, str | None, str | None, str, str]
            ] = []
            item_results: list[tuple[str, str, bool, str | None, list[str]]] = []
            planned_bytes = 0
            for row in rows:
                contract = _ANSWER_CONTRACT_ADAPTER.validate_python(
                    json.loads(row["answer_contract_json"])
                )
                options = [
                    SingleChoiceOption.model_validate(item)
                    for item in json.loads(row["options_json"] or "[]")
                ]
                raw_response = json.loads(row["response_json"])
                decision = grade_assessment_response(
                    raw_response,
                    contract,
                    options,
                )
                algorithm = "exact-v1" if contract.kind == "exact" else contract.kind
                is_correct = decision.is_correct
                error_type = decision.error_type
                contract_sha = self._digest(contract.model_dump())
                response_sha = self._digest(raw_response)
                objectives = sorted(json.loads(row["objective_ids_json"] or "[]") or [""])
                evidence_ids: list[str] = []
                for objective_id in objectives:
                    mapping = objective_mapping.get(objective_id) if objective_id else None
                    module_id, knowledge_type = mapping if mapping else (None, None)
                    if str(row["question_id"]) in invalidated_question_ids:
                        module_id, knowledge_type = None, None
                        state = "unmapped"
                    else:
                        state = "pending" if mapping else "unmapped"
                    payload = {
                        "algorithm": algorithm, "attempt_id": attempt_id,
                        "attempt_item_id": row["attempt_item_id"], "question_id": row["question_id"],
                        "objective_id": objective_id, "module_id": module_id,
                        "knowledge_type": knowledge_type, "contract_sha256": contract_sha,
                        "response_sha256": response_sha, "is_correct": is_correct,
                        "error_type": error_type,
                    }
                    if algorithm == "bounded_short_answer_v1":
                        payload.update(
                            {
                                "answer_contract_kind": contract.kind,
                                "normalization_version": contract.normalization_version,
                                "raw_response": decision.raw_response,
                                "normalized_response": decision.normalized_response,
                            }
                        )
                    elif algorithm == "single_choice_v1":
                        if not isinstance(contract, SingleChoiceAnswerContract):
                            raise ValueError("Single-choice grading contract is invalid")
                        option_order = json.loads(row["option_order_json"] or "null")
                        if (
                            not isinstance(option_order, list)
                            or len(option_order) != len(set(option_order))
                            or set(option_order) != {
                                item.option_id for item in options
                            }
                        ):
                            raise ValueError("Single-choice option order is invalid")
                        payload.update(
                            {
                                "answer_contract_kind": contract.kind,
                                "selected_option_id": decision.raw_response,
                                "correct_option_id": contract.correct_option_id,
                                "options_sha256": self._digest(
                                    [item.model_dump(mode="json") for item in options]
                                ),
                                "option_order_sha256": self._digest(option_order),
                            }
                        )
                    evidence_id = _evidence_id()
                    grading_json = self._json(payload)
                    planned_evidence.append((
                        evidence_id, payload, grading_json, is_correct, error_type,
                        module_id, knowledge_type, state,
                    ))
                    planned_bytes += len(grading_json.encode("utf-8"))
                    evidence_ids.append(evidence_id)
                item_results.append((row["attempt_item_id"], algorithm, is_correct, error_type, evidence_ids))
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
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        evidence_id, self.owner_user_id, course_id, practice_set_id, attempt_id,
                        payload["attempt_item_id"], payload["question_id"], objective_id, module_id,
                        knowledge_type, payload["algorithm"], self._digest(payload), int(is_correct), grading_json,
                        error_type, state, now, now if state == "unmapped" else None,
                    ),
                )
            for item_id, algorithm, is_correct, error_type, evidence_ids in item_results:
                conn.execute(
                    """UPDATE quiz_attempt_items SET grading_json = ?, error_type = ?, graded_at = ?
                       WHERE id = ? AND graded_at IS NULL""",
                    (self._json({"algorithm": algorithm, "is_correct": is_correct, "evidence_ids": evidence_ids}), error_type, now, item_id),
                )
            correct = sum(1 for _item_id, _algorithm, is_correct, _error, _ids in item_results if is_correct)
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
            records = [
                item for item in self._records(conn, attempt_id)
                if item.state == "pending"
            ]
            if not records or not self._content_quality_ledger_available(conn):
                return records
            invalidations = conn.execute(
                """SELECT question_id, evidence_id
                   FROM practice_question_invalidations
                   WHERE course_id = ? AND practice_set_id = ?""",
                (course_id, practice_set_id),
            ).fetchall()
            invalidated_questions = {
                str(item["question_id"])
                for item in invalidations
                if item["evidence_id"] is None
            }
            invalidated_evidence = {
                str(item["evidence_id"])
                for item in invalidations
                if item["evidence_id"] is not None
            }
            return [
                item
                for item in records
                if item.question_id not in invalidated_questions
                and item.id not in invalidated_evidence
            ]

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
            if self._content_quality_ledger_available(conn):
                rows = conn.execute(
                    """SELECT evidence.objective_id, questions.citation_json
                       FROM quiz_item_grading_evidence AS evidence
                       JOIN practice_questions AS questions
                         ON questions.id = evidence.question_id
                       WHERE evidence.attempt_id = ? AND evidence.course_id = ?
                         AND evidence.owner_user_id = ? AND evidence.is_correct = 0
                         AND NOT EXISTS (
                             SELECT 1 FROM practice_question_invalidations AS invalidations
                             WHERE invalidations.course_id = evidence.course_id
                               AND invalidations.question_id = evidence.question_id
                         )
                       ORDER BY evidence.attempt_item_id, evidence.objective_id""",
                    (attempt_id, course_id, self.owner_user_id),
                ).fetchall()
            else:
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

    def remediation_provenance(
        self, course_id: str, attempt_id: str
    ) -> dict[str, Any]:
        """Return the immutable missed-item receipt for a Review proposal.

        The caller still receives the bounded source/objective scope from
        ``remediation_scope``.  This companion receipt adds only opaque
        Practice revision, question, and grading-evidence identities; it
        never exports the learner response or question text.
        """

        practice_set_id, objective_ids, source_ids = self.remediation_scope(
            course_id, attempt_id
        )
        with self.course_repository._connect() as conn:
            attempt = conn.execute(
                """SELECT attempts.practice_set_revision_id, revisions.generation_receipt_json
                   FROM quiz_attempts AS attempts
                   JOIN practice_set_revisions AS revisions
                     ON revisions.id = attempts.practice_set_revision_id
                   WHERE attempts.id = ? AND attempts.course_id = ? AND attempts.owner_user_id = ?""",
                (attempt_id, course_id, self.owner_user_id),
            ).fetchone()
            if self._content_quality_ledger_available(conn):
                rows = conn.execute(
                    """SELECT id, question_id
                       FROM quiz_item_grading_evidence
                       WHERE attempt_id = ? AND course_id = ?
                         AND owner_user_id = ? AND is_correct = 0
                         AND NOT EXISTS (
                             SELECT 1 FROM practice_question_invalidations AS invalidations
                             WHERE invalidations.course_id = quiz_item_grading_evidence.course_id
                               AND invalidations.question_id = quiz_item_grading_evidence.question_id
                         )
                       ORDER BY question_id, id""",
                    (attempt_id, course_id, self.owner_user_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, question_id
                       FROM quiz_item_grading_evidence
                       WHERE attempt_id = ? AND course_id = ?
                         AND owner_user_id = ? AND is_correct = 0
                       ORDER BY question_id, id""",
                    (attempt_id, course_id, self.owner_user_id),
                ).fetchall()
        if attempt is None or not rows:
            raise self._not_found()
        return {
            "practice_attempt_id": attempt_id,
            "practice_set_id": practice_set_id,
            "practice_set_revision_id": str(attempt["practice_set_revision_id"]),
            "practice_question_ids": sorted({str(row["question_id"]) for row in rows}),
            "grading_evidence_ids": [str(row["id"]) for row in rows],
            "objective_ids": objective_ids,
            "source_ids": source_ids,
            "quality_profile": (
                json.loads(attempt["generation_receipt_json"] or "{}").get(
                    "quality_profile", "baseline-v1"
                )
                if attempt["generation_receipt_json"]
                else "baseline-v1"
            ),
        }

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
