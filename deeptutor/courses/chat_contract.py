"""Fail-closed Course Chat readiness and session identity contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import CourseSource

CourseChatReadinessState = Literal[
    "no_materials",
    "processing",
    "failed",
    "partial",
    "ready",
]


class CourseChatReadySource(BaseModel):
    """Browser-safe identity for one source authorized to ground a new turn."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    revision: int = Field(ge=1)
    content_sha256: str


class CourseChatReadiness(BaseModel):
    """Server-derived readiness projection for one authenticated Course."""

    model_config = ConfigDict(extra="forbid")

    state: CourseChatReadinessState
    counts: dict[str, int]
    ready_sources: list[CourseChatReadySource]


def classify_course_chat_sources(
    sources: Iterable[CourseSource],
    *,
    course_id: str | None = None,
) -> CourseChatReadiness:
    """Classify source lifecycle without granting retrieval authority.

    The repository already owner-scopes normal reads.  The explicit Course-ID
    comparison here is a second fence at the provider boundary: a malformed
    service fixture or future repository regression cannot smuggle a foreign
    Course source into Chat.
    """

    source_list = list(sources)
    expected_course_id = str(course_id or "").strip()
    if not expected_course_id and source_list:
        expected_course_id = str(source_list[0].course_id or "").strip()

    same_course = [
        source
        for source in source_list
        if not expected_course_id or str(source.course_id) == expected_course_id
    ]
    superseded_ids = {
        str(source.supersedes_source_id)
        for source in same_course
        if source.supersedes_source_id and source.state in {"ready", "archived"}
    }
    ready = [
        source
        for source in same_course
        if source.state == "ready" and source.id not in superseded_ids
    ]
    processing_count = sum(source.state == "processing" for source in same_course)
    failed_count = sum(source.state == "failed" for source in same_course)
    unavailable_count = len(same_course) - len(ready)

    if ready:
        state: CourseChatReadinessState = "partial" if unavailable_count else "ready"
    elif not same_course or (processing_count == 0 and failed_count == 0):
        state = "no_materials"
    elif processing_count:
        state = "processing"
    else:
        state = "failed"

    return CourseChatReadiness(
        state=state,
        counts={
            "ready": len(ready),
            "processing": processing_count,
            "failed": failed_count,
            "unavailable": unavailable_count,
            "total": len(same_course),
        },
        ready_sources=[
            CourseChatReadySource(
                source_id=source.id,
                title=source.display_name,
                revision=source.revision,
                content_sha256=source.content_sha256,
            )
            for source in ready
        ],
    )


def assert_course_session_binding(
    course_id: str,
    session: Mapping[str, Any] | None,
) -> None:
    """Reject missing or mismatched Course sessions with one bounded outcome."""

    from .service import CourseUnavailableError

    requested = str(course_id or "").strip()
    persisted = str((session or {}).get("course_id") or "").strip()
    if not requested or persisted != requested:
        raise CourseUnavailableError("Session not found")


def readiness_error_message(readiness: CourseChatReadiness) -> str:
    if readiness.state == "processing":
        return "Course materials are still processing"
    if readiness.state == "failed":
        return "Course materials could not be prepared for Chat"
    return "Course has no ready materials for Chat"


__all__ = [
    "CourseChatReadiness",
    "CourseChatReadinessState",
    "CourseChatReadySource",
    "assert_course_session_binding",
    "classify_course_chat_sources",
    "readiness_error_message",
]
