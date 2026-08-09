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
            self.reconcile_pending(course_id)
        return report, evidence_ids

    def effective_result(self, course_id: str, practice_set_id: str, attempt_view):
        # Results is a durable replay boundary. If LearningStore repair fails,
        # do not present a corrected score while stale mastery remains active.
        self.reconcile_pending(course_id)
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

    def reconcile_pending(self, course_id: str) -> bool:
        """Replay all durable invalidations into the private learning projection.

        SQLite and ``LearningStore`` cannot share a transaction. The immutable
        invalidation ledger therefore remains the outbox, and this operation is
        idempotent for retry, startup, and Results boundaries.
        """
        invalidated = self.repository.invalidation_projection(course_id)
        if not invalidated["knowledge_point_ids"]:
            return False
        return self._reconcile_learning(course_id, invalidated)

    def _reconcile_learning(
        self, course_id: str, invalidated: dict[str, set[str]]
    ) -> bool:
        """Remove invalidated effects while preserving retained valid events."""
        repository = self.repository.course_repository
        adapter = CourseMasteryAdapter(
            # The Course adapter stores only the private learning projection.
            # It is intentionally not used as an authority for the correction.
            LearningStore(
                root=get_personal_path_service(repository.owner_user_id).get_workspace_dir() / "learning"
            )
        )
        progress = adapter.service.get_or_create(f"lp_{course_id}")
        changed = adapter.service.reconcile_invalidated_course_evidence(
            progress,
            invalidated_evidence_ids=invalidated["evidence_ids"],
            invalidated_question_ids=invalidated["question_ids"],
            affected_knowledge_point_ids=invalidated["knowledge_point_ids"],
            scheduler=adapter.scheduler,
        )
        if changed:
            adapter.service.save(progress)
        return changed

    def invalidated_review_operation_ids(self, course_id: str, question_id: str) -> list[str]:
        return self.repository.invalidated_review_operation_ids(course_id, question_id)

    def invalidated_question_ids(self, course_id: str) -> set[str]:
        return self.repository.invalidated_question_ids(course_id)

    def invalidated_attempt_ids(
        self, course_id: str, practice_set_id: str
    ) -> set[str]:
        return self.repository.invalidated_attempt_ids(course_id, practice_set_id)


__all__ = ["CourseContentQualityService"]
