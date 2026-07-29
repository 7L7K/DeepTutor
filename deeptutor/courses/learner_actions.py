"""Server-owned decisions for bounded Course learner actions.

This module deliberately turns persisted learning evidence into opaque objective
IDs only.  It never reads chat text, source text, prompts, model settings, or
provider state, so a UI shortcut cannot become a second authority path.
"""

from __future__ import annotations

from collections.abc import Iterable

from deeptutor.learning import policy
from deeptutor.learning.models import LearningProgress

MAX_ACTION_SOURCES = 32
MAX_WEAK_OBJECTIVES = 16


def ready_current_source_ids(sources: Iterable[object]) -> list[str]:
    """Return the bounded, current ready-source authority for one Course.

    A replacement source supersedes the old source as soon as either record is
    ready or archived, matching the Course-chat resolver.  The final sort makes
    this server decision stable even if repository row ordering changes.
    """

    source_list = list(sources)
    superseded = {
        str(getattr(source, "supersedes_source_id"))
        for source in source_list
        if getattr(source, "supersedes_source_id", None)
        and getattr(source, "state", "") in {"ready", "archived"}
    }
    return sorted(
        str(getattr(source, "id"))
        for source in source_list
        if getattr(source, "state", "") == "ready"
        and str(getattr(source, "id")) not in superseded
    )[:MAX_ACTION_SOURCES]


def weak_objective_ids(progress: LearningProgress | None) -> list[str]:
    """Derive bounded weak objectives from committed learning evidence only.

    Priority is active error records, due review tasks, then objectives the
    learner has actually encountered but has not mastered.  Untouched
    objectives and any chat content are intentionally excluded.
    """

    if progress is None or not progress.modules:
        return []

    known = {
        point.id: point
        for module in sorted(progress.modules, key=lambda item: (item.order, item.id))
        for point in module.knowledge_points
    }
    ordered: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        if candidate in known and candidate not in seen and len(ordered) < MAX_WEAK_OBJECTIVES:
            ordered.append(candidate)
            seen.add(candidate)

    for error in sorted(progress.error_records, key=lambda item: (item.created_at, item.id)):
        if error.status in {"active", "retrying", "review"}:
            add(error.knowledge_point_id)

    for review in policy.due_reviews(progress):
        add(review.knowledge_point_id)

    encountered = {
        attempt.knowledge_point_id for attempt in progress.quiz_attempts
    } | set(progress.mastery_levels) | set(progress.qualitative_mastery)
    for module in sorted(progress.modules, key=lambda item: (item.order, item.id)):
        for point in module.knowledge_points:
            if point.id in encountered and not policy.is_mastered(progress, point):
                add(point.id)

    return ordered


def weak_objective_reason_code(progress: LearningProgress | None) -> str:
    """Return the bounded evidence category that selected weak objectives."""

    if progress is None:
        return "no_targets"
    if any(item.status in {"active", "retrying", "review"} for item in progress.error_records):
        return "active_error"
    if policy.due_reviews(progress):
        return "due_review"
    return "low_mastery"


def learner_safe_progress(progress: LearningProgress) -> dict:
    """Return the Course-learning view without answer or learner-text leakage."""

    payload = progress.model_dump(mode="json")
    payload["quiz_attempts"] = [
        {
            "question_id": item.question_id,
            "knowledge_point_id": item.knowledge_point_id,
            "module_id": item.module_id,
            "is_correct": item.is_correct,
            "error_type": item.error_type.value if item.error_type else None,
            "mastery_estimate": item.mastery_estimate,
            "timestamp": item.timestamp,
        }
        for item in progress.quiz_attempts
    ]
    payload["error_records"] = [
        {
            "id": item.id,
            "question_id": item.question_id,
            "knowledge_point_id": item.knowledge_point_id,
            "module_id": item.module_id,
            "error_type": item.error_type.value,
            "status": item.status,
            "created_at": item.created_at,
        }
        for item in progress.error_records
    ]
    if progress.pending_question is not None:
        pending = progress.pending_question
        payload["pending_question"] = {
            "question_id": pending.question_id,
            "knowledge_point_id": pending.knowledge_point_id,
            "module_id": pending.module_id,
            "question_type": pending.question_type,
            "created_at": pending.created_at,
        }
    payload.pop("feynman_explanations", None)
    payload.pop("stage_failure_notes", None)
    payload.pop("grading_evidence_receipts", None)
    return payload


def learner_safe_next(progress: LearningProgress | None) -> dict | None:
    """Expose next-step status without echoing a pending question's text."""

    if progress is None:
        return None
    payload = policy.next_objective(progress).to_dict()
    payload.pop("pending_prompt", None)
    return payload


__all__ = [
    "MAX_ACTION_SOURCES",
    "MAX_WEAK_OBJECTIVES",
    "learner_safe_next",
    "learner_safe_progress",
    "ready_current_source_ids",
    "weak_objective_reason_code",
    "weak_objective_ids",
]
