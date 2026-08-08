"""Fail-closed Course Chat readiness and session identity contracts."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from deeptutor.core.stream import StreamEvent, StreamEventType

from .models import CourseSource

COURSE_CHAT_UNSUPPORTED_MESSAGE = (
    "I could not find support for that answer in the available Course materials."
)

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


def _bounded_scalar(value: Any, *, limit: int = 240) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def _source_id_for_proposal(
    course_id: str,
    authorized_ids: set[str],
    proposal: Mapping[str, Any],
) -> str | None:
    direct = _bounded_scalar(proposal.get("source_id"))
    if direct in authorized_ids:
        proposed_course = _bounded_scalar(proposal.get("course_id"))
        if proposed_course is None or proposed_course == course_id:
            return direct

    proposed_kb = _bounded_scalar(
        proposal.get("kb_name")
        or proposal.get("knowledge_base")
        or proposal.get("name")
    )
    for source_id in authorized_ids:
        physical_name = f"course_{course_id}_{source_id}"
        if proposed_kb in {physical_name, f"personal:kb:{physical_name}"}:
            return source_id
    return None


def _citation_locator(proposal: Mapping[str, Any]) -> tuple[str | None, str | None]:
    for locator_type, keys in (
        ("page", ("page", "page_number")),
        ("slide", ("slide", "slide_number")),
        ("timestamp", ("timestamp",)),
        ("section", ("section",)),
    ):
        for key in keys:
            value = _bounded_scalar(proposal.get(key))
            if value is not None:
                return locator_type, value
    return None, None


def build_validated_course_citations(
    course_context: Mapping[str, Any],
    proposed_sources: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Reduce provider provenance to the frozen, authorized Course snapshot."""

    course_id = _bounded_scalar(course_context.get("course_id")) or ""
    source_ids = {
        str(source_id)
        for source_id in course_context.get("source_ids") or []
        if str(source_id)
    }
    revisions = dict(course_context.get("source_revisions") or {})
    fingerprints = dict(course_context.get("source_fingerprints") or {})
    titles = dict(course_context.get("source_titles") or {})
    if not course_id or not source_ids:
        return []

    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    for proposal in proposed_sources:
        if not isinstance(proposal, Mapping):
            continue
        source_id = _source_id_for_proposal(course_id, source_ids, proposal)
        if source_id is None:
            continue
        try:
            revision = int(revisions.get(source_id) or 0)
        except (TypeError, ValueError):
            continue
        fingerprint = _bounded_scalar(fingerprints.get(source_id), limit=128)
        title = _bounded_scalar(titles.get(source_id), limit=500)
        if revision < 1 or not fingerprint or not title:
            continue
        locator_type, locator_value = _citation_locator(proposal)
        fragment_id = _bounded_scalar(
            proposal.get("chunk_id") or proposal.get("fragment_id")
        )
        dedupe_key = (source_id, locator_type, locator_value, fragment_id)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        citations.append(
            {
                "schema_version": 1,
                "course_id": course_id,
                "source_id": source_id,
                "source_revision": revision,
                "source_content_hash": fingerprint,
                "source_title_snapshot": title,
                "locator_type": locator_type,
                "locator_value": locator_value,
                "retrieval_fragment_id": fragment_id,
            }
        )
    return citations


def finalize_course_chat_events(
    course_context: Mapping[str, Any],
    events: Iterable[StreamEvent],
) -> list[StreamEvent]:
    """Emit only citation-validated Course answers and provenance."""

    event_list = list(events)
    if any(event.type == StreamEventType.ERROR for event in event_list):
        return [
            event
            for event in event_list
            if event.type not in {StreamEventType.CONTENT, StreamEventType.SOURCES}
        ]

    proposed_sources: list[Mapping[str, Any]] = []
    for event in event_list:
        if event.type != StreamEventType.SOURCES:
            continue
        proposed_sources.extend(
            source
            for source in (event.metadata or {}).get("sources") or []
            if isinstance(source, Mapping)
        )
    citations = build_validated_course_citations(course_context, proposed_sources)

    retained = [event for event in event_list if event.type != StreamEventType.SOURCES]
    if not citations:
        retained = [event for event in retained if event.type != StreamEventType.CONTENT]
        done_events = [event for event in retained if event.type == StreamEventType.DONE]
        retained = [event for event in retained if event.type != StreamEventType.DONE]
        retained.append(
            StreamEvent(
                type=StreamEventType.CONTENT,
                source="course_grounding",
                content=COURSE_CHAT_UNSUPPORTED_MESSAGE,
                metadata={
                    "call_kind": "llm_final_response",
                    "course_grounding": "unsupported",
                },
            )
        )
        retained.extend(
            done_events
            or [
                StreamEvent(
                    type=StreamEventType.DONE,
                    source="course_grounding",
                    metadata={"status": "completed"},
                )
            ]
        )
        return retained

    citation_event = StreamEvent(
        type=StreamEventType.SOURCES,
        source="course_grounding",
        metadata={
            "trace_kind": "course_citations",
            "course_citations": citations,
        },
    )
    insert_at = next(
        (
            index
            for index, event in enumerate(retained)
            if event.type == StreamEventType.CONTENT
        ),
        len(retained),
    )
    retained.insert(insert_at, citation_event)
    return retained


async def finalize_course_chat_stream(
    course_context: Mapping[str, Any],
    events: AsyncIterable[StreamEvent],
) -> AsyncIterator[StreamEvent]:
    """Buffer one Course turn so unvalidated output is never published live."""

    buffered = [event async for event in events]
    for event in finalize_course_chat_events(course_context, buffered):
        yield event


def citation_version_available(
    citation: Mapping[str, Any],
    readiness: CourseChatReadiness,
) -> bool:
    """Return whether the exact cited immutable source version is still ready."""

    for source in readiness.ready_sources:
        if (
            source.source_id == str(citation.get("source_id") or "")
            and source.revision == int(citation.get("source_revision") or 0)
            and source.content_sha256
            == str(citation.get("source_content_hash") or "")
        ):
            return True
    return False


__all__ = [
    "CourseChatReadiness",
    "CourseChatReadinessState",
    "CourseChatReadySource",
    "COURSE_CHAT_UNSUPPORTED_MESSAGE",
    "assert_course_session_binding",
    "build_validated_course_citations",
    "citation_version_available",
    "classify_course_chat_sources",
    "finalize_course_chat_events",
    "finalize_course_chat_stream",
    "readiness_error_message",
]
