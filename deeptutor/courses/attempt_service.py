"""Authenticated service seam for Course-owned quiz attempts."""

from __future__ import annotations

from typing import Any

from .attempt_models import QuizAttempt, QuizAttemptAnswer, QuizAttemptView
from .attempt_repository import CourseAssessmentRepository


class CourseAssessmentService:
    """Expose Course-rooted attempt operations to future API adapters."""

    def __init__(self, repository: CourseAssessmentRepository) -> None:
        self.repository = repository

    def start_or_resume_attempt(self, course_id: str, practice_set_id: str, practice_set_revision_id: str, **kwargs: Any) -> QuizAttemptView:
        return self.repository.start_or_resume_attempt(course_id, practice_set_id, practice_set_revision_id, **kwargs)

    def get_attempt(self, course_id: str, practice_set_id: str, attempt_id: str) -> QuizAttemptView:
        return self.repository.get_attempt(course_id, practice_set_id, attempt_id)

    def list_attempts(self, course_id: str, practice_set_id: str, **kwargs: Any) -> list[QuizAttempt]:
        return self.repository.list_attempts(course_id, practice_set_id, **kwargs)

    def autosave_answer(self, course_id: str, practice_set_id: str, attempt_id: str, attempt_item_id: str, **kwargs: Any) -> QuizAttemptAnswer:
        return self.repository.autosave_answer(course_id, practice_set_id, attempt_id, attempt_item_id, **kwargs)

    def submit_attempt(self, course_id: str, practice_set_id: str, attempt_id: str, **kwargs: Any) -> QuizAttempt:
        return self.repository.submit_attempt(course_id, practice_set_id, attempt_id, **kwargs)

    def abandon_attempt(self, course_id: str, practice_set_id: str, attempt_id: str, **kwargs: Any) -> QuizAttempt:
        return self.repository.abandon_attempt(course_id, practice_set_id, attempt_id, **kwargs)
