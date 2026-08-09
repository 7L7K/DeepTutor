"""Authenticated service seam for Course-owned Practice authoring."""

from __future__ import annotations

from typing import Any, Iterable

from .practice_models import (
    PracticeAnswerContract,
    PracticeCitation,
    PracticeQuestion,
    PracticeSet,
    PracticeSetRevision,
    SingleChoiceOption,
)
from .practice_repository import CoursePracticeRepository


class CoursePracticeService:
    """Expose only Course-rooted Practice operations to future API adapters."""

    def __init__(self, repository: CoursePracticeRepository) -> None:
        self.repository = repository

    def create_practice_set(self, course_id: str, **kwargs: Any) -> PracticeSet:
        return self.repository.create_practice_set(course_id, **kwargs)

    def create_draft_revision(self, course_id: str, practice_set_id: str, **kwargs: Any) -> PracticeSetRevision:
        return self.repository.create_draft_revision(course_id, practice_set_id, **kwargs)

    def create_successor_revision(self, course_id: str, practice_set_id: str, **kwargs: Any) -> PracticeSetRevision:
        return self.repository.create_successor_revision(course_id, practice_set_id, **kwargs)

    def add_question(
        self,
        course_id: str,
        practice_set_id: str,
        revision_id: str,
        *,
        question_type: str,
        prompt: str,
        answer_contract: dict[str, Any] | PracticeAnswerContract,
        options: Iterable[SingleChoiceOption | dict[str, Any]] = (),
        explanation: str = "",
        objective_ids: Iterable[str] = (),
        citations: Iterable[PracticeCitation | dict[str, Any]] = (),
        ordinal: int | None = None,
        expected_course_write_epoch: int,
    ) -> PracticeQuestion:
        return self.repository.add_question(
            course_id,
            practice_set_id,
            revision_id,
            question_type=question_type,
            prompt=prompt,
            answer_contract=answer_contract,
            options=options,
            explanation=explanation,
            objective_ids=objective_ids,
            citations=citations,
            ordinal=ordinal,
            expected_course_write_epoch=expected_course_write_epoch,
        )

    def ready_revision(self, course_id: str, practice_set_id: str, revision_id: str, **kwargs: Any) -> PracticeSetRevision:
        return self.repository.ready_revision(course_id, practice_set_id, revision_id, **kwargs)

    def archive_practice_set(self, course_id: str, practice_set_id: str, **kwargs: Any) -> PracticeSet:
        return self.repository.archive_practice_set(course_id, practice_set_id, **kwargs)

    def restore_practice_set(self, course_id: str, practice_set_id: str, **kwargs: Any) -> PracticeSet:
        return self.repository.restore_practice_set(course_id, practice_set_id, **kwargs)

    def list_practice_sets(self, course_id: str, **kwargs: Any) -> list[PracticeSet]:
        return self.repository.list_practice_sets(course_id, **kwargs)

    def get_practice_set(self, course_id: str, practice_set_id: str) -> PracticeSet:
        return self.repository.get_practice_set(course_id, practice_set_id)

    def get_revision(self, course_id: str, practice_set_id: str, revision_id: str) -> PracticeSetRevision:
        return self.repository.get_revision(course_id, practice_set_id, revision_id)

    def list_questions(self, course_id: str, practice_set_id: str, revision_id: str) -> list[PracticeQuestion]:
        return self.repository.list_questions(course_id, practice_set_id, revision_id)
