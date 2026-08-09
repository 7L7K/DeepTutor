"""Course-owned report and invalidation authority for C3 content quality."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any
from uuid import uuid4

from .repository import CourseConflictError, CourseNotFoundError, CourseRepository


def _report_id() -> str:
    return f"cqr_{uuid4().hex}"


def _invalidation_id() -> str:
    return f"cqi_{uuid4().hex}"


class CourseContentQualityRepository:
    """Persist append-only learner reports and their review decisions."""

    def __init__(self, course_repository: CourseRepository) -> None:
        self.course_repository = course_repository

    @property
    def owner_user_id(self) -> str:
        return self.course_repository.owner_user_id

    @staticmethod
    def _not_found() -> CourseNotFoundError:
        return CourseNotFoundError("Course content-quality resource not found")

    @staticmethod
    def _clean_reason(reason: str) -> str:
        cleaned = " ".join(str(reason or "").split())
        if not cleaned or len(cleaned) > 1_000:
            raise ValueError("A bounded quality report reason is required")
        return cleaned

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def report_question(
        self,
        course_id: str,
        practice_set_id: str,
        practice_set_revision_id: str,
        question_id: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        reason = self._clean_reason(reason)
        now = time.time()
        report_id = _report_id()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT questions.id FROM practice_questions AS questions
                   JOIN practice_set_revisions AS revisions ON revisions.id = questions.practice_set_revision_id
                   JOIN practice_sets AS sets ON sets.id = revisions.practice_set_id
                   JOIN courses ON courses.id = sets.course_id
                   WHERE questions.id = ? AND revisions.id = ? AND sets.id = ?
                     AND courses.id = ? AND courses.owner_user_id = ?
                     AND sets.owner_user_id = ?""",
                (question_id, practice_set_revision_id, practice_set_id, course_id,
                 self.owner_user_id, self.owner_user_id),
            ).fetchone()
            if row is None:
                raise self._not_found()
            already = conn.execute(
                """SELECT 1 FROM practice_question_invalidations
                   WHERE course_id = ? AND practice_set_id = ? AND question_id = ?""",
                (course_id, practice_set_id, question_id),
            ).fetchone()
            if already is not None:
                raise CourseConflictError("This question has already been invalidated")
            conn.execute(
                """INSERT INTO practice_question_quality_reports
                   (id, owner_user_id, course_id, practice_set_id, practice_set_revision_id,
                    question_id, reporter_user_id, reason, state, reviewer_user_id,
                    review_note, created_at, reviewed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reported', NULL, NULL, ?, NULL)""",
                (report_id, self.owner_user_id, course_id, practice_set_id,
                 practice_set_revision_id, question_id, self.owner_user_id, reason, now),
            )
            report = conn.execute(
                "SELECT * FROM practice_question_quality_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
        assert report is not None
        return self._row(report)

    def resolve_report(
        self,
        course_id: str,
        report_id: str,
        *,
        decision: str,
        reviewer_user_id: str,
        note: str,
    ) -> tuple[dict[str, Any], list[str]]:
        if decision not in {"reject", "invalidate"}:
            raise ValueError("quality decision must be reject or invalidate")
        note = self._clean_reason(note)
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            report = conn.execute(
                """SELECT * FROM practice_question_quality_reports
                   WHERE id = ? AND course_id = ? AND owner_user_id = ?""",
                (report_id, course_id, self.owner_user_id),
            ).fetchone()
            if report is None:
                raise self._not_found()
            if str(report["state"]) != "reported":
                raise CourseConflictError("Quality report has already been reviewed")
            reviewed = "rejected" if decision == "reject" else "reviewed"
            conn.execute(
                """UPDATE practice_question_quality_reports
                   SET state = 'reviewed', reviewer_user_id = ?, review_note = ?, reviewed_at = ?
                   WHERE id = ? AND state = 'reported'""",
                (reviewer_user_id, note, now, report_id),
            )
            invalidation_evidence_ids: list[str] = []
            if decision == "invalidate":
                conn.execute(
                    """UPDATE practice_question_quality_reports
                       SET state = 'invalidated' WHERE id = ? AND state = 'reviewed'""",
                    (report_id,),
                )
                evidence_rows = conn.execute(
                    """SELECT id FROM quiz_item_grading_evidence
                       WHERE course_id = ? AND practice_set_id = ? AND question_id = ?
                       ORDER BY id""",
                    (course_id, report["practice_set_id"], report["question_id"]),
                ).fetchall()
                evidence_ids = [str(item["id"]) for item in evidence_rows]
                conn.execute(
                    """INSERT INTO practice_question_invalidations
                       (id, owner_user_id, course_id, practice_set_id, practice_set_revision_id,
                        question_id, report_id, evidence_id, reason, invalidated_by, invalidated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)""",
                    (_invalidation_id(), self.owner_user_id, course_id, report["practice_set_id"],
                     report["practice_set_revision_id"], report["question_id"], report_id,
                     note, reviewer_user_id, now),
                )
                for evidence_id in evidence_ids:
                    conn.execute(
                        """INSERT INTO practice_question_invalidations
                           (id, owner_user_id, course_id, practice_set_id, practice_set_revision_id,
                            question_id, report_id, evidence_id, reason, invalidated_by, invalidated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (_invalidation_id(), self.owner_user_id, course_id, report["practice_set_id"],
                         report["practice_set_revision_id"], report["question_id"], report_id,
                         evidence_id, note, reviewer_user_id, now),
                    )
                invalidation_evidence_ids = evidence_ids
            else:
                conn.execute(
                    """UPDATE practice_question_quality_reports
                       SET state = ?, reviewed_at = ? WHERE id = ? AND state = 'reviewed'""",
                    (reviewed, now, report_id),
                )
            updated = conn.execute(
                "SELECT * FROM practice_question_quality_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
        assert updated is not None
        return self._row(updated), invalidation_evidence_ids

    def invalidated_for_attempt(
        self, course_id: str, practice_set_id: str, attempt_id: str
    ) -> dict[str, list[str]]:
        with self.course_repository._connect() as conn:
            rows = conn.execute(
                """SELECT invalidations.question_id, invalidations.evidence_id
                   FROM practice_question_invalidations AS invalidations
                   LEFT JOIN quiz_item_grading_evidence AS evidence
                     ON evidence.id = invalidations.evidence_id
                   WHERE invalidations.course_id = ? AND invalidations.practice_set_id = ?
                     AND (invalidations.evidence_id IS NULL OR evidence.attempt_id = ?)
                   ORDER BY invalidations.question_id, invalidations.evidence_id""",
                (course_id, practice_set_id, attempt_id),
            ).fetchall()
        return {
            "question_ids": sorted({str(row["question_id"]) for row in rows}),
            "evidence_ids": sorted({str(row["evidence_id"]) for row in rows if row["evidence_id"]}),
        }

    def invalidated_question_ids(self, course_id: str) -> set[str]:
        with self.course_repository._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT question_id FROM practice_question_invalidations WHERE course_id = ?",
                (course_id,),
            ).fetchall()
        return {str(row["question_id"]) for row in rows}


__all__ = ["CourseContentQualityRepository"]
