"""Service orchestration for deterministic Course assessment grading."""

from __future__ import annotations

from .attempt_models import QuizAttempt
from .grading_repository import CourseGradingRepository
from .mastery_adapter import CourseMasteryAdapter


class CourseGradingService:
    def __init__(self, repository: CourseGradingRepository, adapter: CourseMasteryAdapter) -> None:
        self.repository = repository
        self.adapter = adapter

    def grade_attempt(self, course_id: str, practice_set_id: str, attempt_id: str, **kwargs: int) -> QuizAttempt:
        existing = self._finalize_attempt(course_id, practice_set_id, attempt_id)
        if existing.state == "graded":
            self._deliver_pending(course_id, practice_set_id, attempt_id)
            return existing

        objectives = self.repository.collect_objective_ids(
            course_id, practice_set_id, attempt_id, **kwargs
        )
        mapping = self.adapter.resolve_objectives(course_id, objectives)
        _attempt, evidence = self.repository.grade(
            course_id, practice_set_id, attempt_id, objective_mapping=mapping, **kwargs
        )
        self._deliver(course_id, practice_set_id, attempt_id, evidence)
        return self._finalize_attempt(course_id, practice_set_id, attempt_id)

    def _deliver_pending(
        self, course_id: str, practice_set_id: str, attempt_id: str
    ) -> None:
        evidence = self.repository.pending(course_id, practice_set_id, attempt_id)
        self._deliver(course_id, practice_set_id, attempt_id, evidence)

    def _deliver(self, course_id: str, practice_set_id: str, attempt_id: str, evidence) -> None:
        for record in self._apply_effect_to_learning(evidence):
            self._mark_effect_applied(
                course_id, practice_set_id, attempt_id, record.id,
                payload_sha256=record.payload_sha256,
            )

    def _apply_effect_to_learning(self, evidence):
        return self.adapter.apply_pending(evidence)

    def _mark_effect_applied(
        self, course_id: str, practice_set_id: str, attempt_id: str, evidence_id: str, **kwargs: str
    ):
        return self.repository.acknowledge_applied(
            course_id, practice_set_id, attempt_id, evidence_id, **kwargs
        )

    def _finalize_attempt(
        self, course_id: str, practice_set_id: str, attempt_id: str, **kwargs: int
    ) -> QuizAttempt:
        return self.repository.finalize(course_id, practice_set_id, attempt_id, **kwargs)


__all__ = ["CourseGradingService"]
