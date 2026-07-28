"""Single-process delivery of frozen Course grading evidence to LearningProgress."""

from __future__ import annotations

from collections.abc import Iterable

from deeptutor.learning.models import KnowledgeType
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore

from .grading_models import GradingEvidence


class CourseMasteryAdapter:
    """Project only SQLite-pending evidence; SQLite remains grade authority."""

    def __init__(self, store: LearningStore) -> None:
        self.service = LearningService(store)
        self.scheduler = SpacedRepetitionScheduler()

    def resolve_objectives(self, course_id: str, objective_ids: Iterable[str]) -> dict[str, tuple[str, str] | None]:
        """Freeze the current Course objective map before the SQLite grade commit."""
        progress = self.service.get_or_create(f"lp_{course_id}")
        known = {
            point.id: (point.module_id, point.type.value)
            for module in progress.modules
            for point in module.knowledge_points
        }
        return {objective_id: known.get(objective_id) for objective_id in set(objective_ids) if objective_id}

    def apply_pending(self, evidence: Iterable[GradingEvidence]) -> list[GradingEvidence]:
        records = [item for item in evidence if item.state == "pending"]
        if not records:
            return []
        course_ids = {item.course_id for item in records}
        if len(course_ids) != 1:
            raise ValueError("grading effects must belong to one Course")
        progress = self.service.get_or_create(f"lp_{records[0].course_id}")
        for item in records:
            if not item.objective_id or not item.module_id or not item.knowledge_type:
                continue
            response = item.response
            answer = response["answer"] if isinstance(response, dict) and set(response) == {"answer"} else ""
            self.service.record_course_grading_evidence(
                progress,
                evidence_id=item.id,
                payload_sha256=item.payload_sha256,
                question_id=item.question_id,
                knowledge_point_id=item.objective_id,
                module_id=item.module_id,
                is_correct=item.is_correct,
                user_answer=answer if isinstance(answer, str) else "",
                knowledge_type=KnowledgeType(item.knowledge_type),
                scheduler=self.scheduler,
            )
        return records


__all__ = ["CourseMasteryAdapter"]
