"""Bounded Course content-quality report and correction service."""

from __future__ import annotations

from deeptutor.learning.storage import LearningStore
from deeptutor.multi_user.paths import get_personal_path_service

from .content_quality_repository import CourseContentQualityRepository
from .mastery_adapter import CourseMasteryAdapter


class CourseContentQualityService:
    def __init__(self, repository: CourseContentQualityRepository) -> None:
        self.repository = repository

    def report_question(self, course_id: str, practice_set_id: str, revision_id: str, question_id: str, *, reason: str):
        return self.repository.report_question(
            course_id, practice_set_id, revision_id, question_id, reason=reason
        )

    def resolve_report(self, course_id: str, report_id: str, *, decision: str, reviewer_user_id: str, note: str):
        report, evidence_ids = self.repository.resolve_report(
            course_id,
            report_id,
            decision=decision,
            reviewer_user_id=reviewer_user_id,
            note=note,
        )
        if decision == "invalidate":
            self._reconcile_learning(course_id, evidence_ids)
        return report, evidence_ids

    def effective_result(self, course_id: str, practice_set_id: str, attempt_view):
        invalidated = self.repository.invalidated_for_attempt(
            course_id, practice_set_id, attempt_view.attempt.id
        )
        valid_items = [
            item for item in attempt_view.items
            if item.question_id not in set(invalidated["question_ids"])
        ]
        correct = sum(
            1 for item in valid_items
            if isinstance(item.grading, dict) and item.grading.get("is_correct") is True
        )
        total = len(valid_items)
        return {
            "score": {"correct": correct, "total": total, "fraction": correct / total if total else 0.0},
            "invalidated_question_ids": invalidated["question_ids"],
            "invalidated_evidence_ids": invalidated["evidence_ids"],
            "evidence_status": "adjusted_for_invalidated_question" if invalidated["question_ids"] else "valid",
        }

    def _reconcile_learning(self, course_id: str, evidence_ids: list[str]) -> None:
        """Remove invalidated effects from the local projection, preserving valid receipts."""
        if not evidence_ids:
            return
        repository = self.repository.course_repository
        adapter = CourseMasteryAdapter(
            # The Course adapter stores only the private learning projection.
            # It is intentionally not used as an authority for the correction.
            LearningStore(
                root=get_personal_path_service(repository.owner_user_id).get_workspace_dir() / "learning"
            )
        )
        progress = adapter.service.get_or_create(f"lp_{course_id}")
        evidence_set = set(evidence_ids)
        invalidated_questions = set()
        with repository._connect() as conn:
            rows = conn.execute(
                "SELECT question_id FROM quiz_item_grading_evidence WHERE id IN (%s)"
                % ",".join("?" for _ in evidence_ids),
                evidence_ids,
            ).fetchall()
            invalidated_questions = {str(row["question_id"]) for row in rows}
        progress.quiz_attempts = [
            item for item in progress.quiz_attempts if item.question_id not in invalidated_questions
        ]
        progress.error_records = [
            item for item in progress.error_records if item.question_id not in invalidated_questions
        ]
        progress.grading_evidence_receipts = {
            key: value for key, value in progress.grading_evidence_receipts.items()
            if key not in evidence_set
        }
        for knowledge_point_id in list(progress.mastery_levels):
            progress.mastery_levels[knowledge_point_id] = adapter.service.calculate_mastery(
                progress, knowledge_point_id
            )
        progress.review_queue = adapter.scheduler.build_review_queue(progress)
        adapter.service.save(progress)


__all__ = ["CourseContentQualityService"]
