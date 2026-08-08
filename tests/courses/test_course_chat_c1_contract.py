from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.courses.models import Course, CourseSource
from deeptutor.courses.repository import CourseNotFoundError, CourseRepository
from deeptutor.courses.service import CourseUnavailableError, resolve_course_turn_payload
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


def _course(
    course_id: str = "crs_biology",
    *,
    owner_user_id: str = "u_alice",
    title: str = "Biology 101",
    workspace_kind: str = "academic_course",
) -> Course:
    return Course(
        id=course_id,
        owner_user_id=owner_user_id,
        title=title,
        term="fall-2026",
        workspace_kind=workspace_kind,
        managed_kb_ref=f"personal:kb:course_{course_id}",
        revision=3,
        write_epoch=2,
        created_at=1,
        updated_at=1,
    )


def _source(
    source_id: str,
    *,
    course_id: str = "crs_biology",
    state: str = "ready",
    title: str | None = None,
    revision: int = 2,
    fingerprint: str | None = None,
    supersedes_source_id: str | None = None,
) -> CourseSource:
    return CourseSource(
        id=source_id,
        course_id=course_id,
        kind="document",
        display_name=title or f"{source_id}.pdf",
        state=state,
        manifest=[],
        content_sha256=fingerprint or (source_id[-1:] or "a") * 64,
        revision=revision,
        supersedes_source_id=supersedes_source_id,
        created_at=1,
        updated_at=1,
    )


def _readiness(sources: list[CourseSource]):
    from deeptutor.courses.chat_contract import classify_course_chat_sources

    return classify_course_chat_sources(sources)


def _course_context() -> dict:
    return {
        "course_id": "crs_biology",
        "course_revision": 3,
        "course_write_epoch": 2,
        "source_ids": ["src_bio"],
        "source_revisions": {"src_bio": 4},
        "source_fingerprints": {"src_bio": "a" * 64},
        "source_titles": {"src_bio": "Lecture 6.pdf"},
    }


def test_course_chat_readiness_classifies_zero_materials() -> None:
    readiness = _readiness([])

    assert readiness.state == "no_materials"
    assert readiness.counts == {
        "ready": 0,
        "processing": 0,
        "failed": 0,
        "unavailable": 0,
        "total": 0,
    }
    assert readiness.ready_sources == []


def test_course_chat_readiness_classifies_processing_only() -> None:
    readiness = _readiness([_source("src_processing", state="processing")])

    assert readiness.state == "processing"
    assert readiness.counts["processing"] == 1
    assert readiness.ready_sources == []


def test_course_chat_readiness_classifies_failed_only() -> None:
    readiness = _readiness([_source("src_failed", state="failed")])

    assert readiness.state == "failed"
    assert readiness.counts["failed"] == 1
    assert readiness.ready_sources == []


def test_course_chat_readiness_mixed_state_uses_only_current_ready_sources() -> None:
    original = _source("src_old", title="Lecture 5.pdf")
    replacement = _source(
        "src_new",
        title="Lecture 6.pdf",
        supersedes_source_id=original.id,
    )
    readiness = _readiness(
        [
            original,
            replacement,
            _source("src_second", title="Respiration Slides.pdf"),
            _source("src_processing", state="processing"),
            _source("src_failed", state="failed"),
            _source("src_archived", state="archived"),
        ]
    )

    assert readiness.state == "partial"
    assert [source.source_id for source in readiness.ready_sources] == [
        "src_new",
        "src_second",
    ]
    assert readiness.counts == {
        "ready": 2,
        "processing": 1,
        "failed": 1,
        "unavailable": 4,
        "total": 6,
    }


@pytest.mark.asyncio
async def test_zero_ready_sources_prevent_session_creation_and_provider_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    service = SimpleNamespace(
        get=lambda _course_id: _course(),
        list_sources=lambda _course_id: [],
    )
    monkeypatch.setattr("deeptutor.courses.service.get_current_course_service", lambda: service)
    monkeypatch.setattr(
        "deeptutor.multi_user.tool_access.allowed_optional_tools", lambda: None
    )
    provider_calls = 0

    async def provider_probe(_execution) -> None:
        nonlocal provider_calls
        provider_calls += 1

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    monkeypatch.setattr(runtime, "_run_turn", provider_probe)

    error: Exception | None = None
    try:
        await runtime.start_turn(
            {
                "course_id": "crs_biology",
                "content": "What produces ATP?",
                "tools": [],
                "knowledge_bases": [],
            }
        )
    except Exception as exc:  # expected C1 preflight rejection
        error = exc
    await asyncio.sleep(0)

    assert isinstance(error, CourseUnavailableError)
    assert "materials" in str(error).lower()
    assert provider_calls == 0
    assert await store.list_sessions() == []


def test_mixed_course_turn_resolves_only_biology_ready_sources(monkeypatch) -> None:
    service = SimpleNamespace(
        get=lambda _course_id: _course(),
        list_sources=lambda _course_id: [
            _source("src_bio"),
            _source("src_processing", state="processing"),
            _source("src_failed", state="failed"),
            _source("src_psych", course_id="crs_psychology"),
        ],
    )
    monkeypatch.setattr("deeptutor.courses.service.get_current_course_service", lambda: service)

    payload = resolve_course_turn_payload("crs_biology", {"knowledge_bases": []})

    assert payload["course_context"]["source_ids"] == ["src_bio"]
    assert payload["course_context"]["source_titles"] == {
        "src_bio": "src_bio.pdf"
    }
    assert payload["course_readiness"]["counts"] == {
        "ready": 1,
        "processing": 1,
        "failed": 1,
        "unavailable": 2,
        "total": 3,
    }


def test_course_repository_foreign_owner_remains_not_found(tmp_path) -> None:
    db_path = tmp_path / "courses.db"
    alice = CourseRepository(db_path, "u_alice")
    biology = alice.create_course("Biology 101")
    bob = CourseRepository(db_path, "u_bob")

    with pytest.raises(CourseNotFoundError):
        bob.get_course(biology.id)


def test_course_session_route_never_rebinds_a_mismatched_session() -> None:
    from deeptutor.courses.chat_contract import assert_course_session_binding

    with pytest.raises(CourseUnavailableError, match="Session not found"):
        assert_course_session_binding(
            "crs_biology",
            {"session_id": "session_psychology", "course_id": "crs_psychology"},
        )


def test_validated_course_citation_preserves_identity_title_and_real_locator() -> None:
    from deeptutor.courses.chat_contract import build_validated_course_citations

    citations = build_validated_course_citations(
        _course_context(),
        [
            {
                "type": "rag",
                "kb_name": "personal:kb:course_crs_biology_src_bio",
                "title": "provider title must not replace the snapshot",
                "page": 12,
                "chunk_id": "chunk-18",
                "path": "/Users/alice/private/Lecture 6.pdf",
                "content": "raw retrieval content must not be serialized",
            }
        ],
    )

    assert citations == [
        {
            "schema_version": 1,
            "course_id": "crs_biology",
            "source_id": "src_bio",
            "source_revision": 4,
            "source_content_hash": "a" * 64,
            "source_title_snapshot": "Lecture 6.pdf",
            "locator_type": "page",
            "locator_value": "12",
            "retrieval_fragment_id": "chunk-18",
        }
    ]
    assert "/Users/alice" not in repr(citations)
    assert "raw retrieval content" not in repr(citations)


def test_foreign_course_source_cannot_become_a_citation() -> None:
    from deeptutor.courses.chat_contract import build_validated_course_citations

    citations = build_validated_course_citations(
        _course_context(),
        [
            {
                "type": "rag",
                "kb_name": "personal:kb:course_crs_psychology_src_psych",
                "page": 7,
            }
        ],
    )

    assert citations == []


def test_unsupported_course_answer_is_replaced_with_bounded_abstention() -> None:
    from deeptutor.courses.chat_contract import (
        COURSE_CHAT_UNSUPPORTED_MESSAGE,
        finalize_course_chat_events,
    )

    finalized = finalize_course_chat_events(
        _course_context(),
        [
            StreamEvent(
                type=StreamEventType.CONTENT,
                source="provider",
                content="Unsupported general-knowledge answer",
                metadata={"call_kind": "llm_final_response"},
            ),
            StreamEvent(type=StreamEventType.DONE, source="provider"),
        ],
    )

    content = [event for event in finalized if event.type == StreamEventType.CONTENT]
    assert [event.content for event in content] == [COURSE_CHAT_UNSUPPORTED_MESSAGE]
    assert content[0].metadata["course_grounding"] == "unsupported"
    assert "Unsupported general-knowledge answer" not in repr(finalized)


@pytest.mark.asyncio
async def test_course_citation_survives_session_reload_and_later_archive(tmp_path) -> None:
    from deeptutor.courses.chat_contract import (
        citation_version_available,
        finalize_course_chat_events,
    )

    finalized = finalize_course_chat_events(
        _course_context(),
        [
            StreamEvent(
                type=StreamEventType.SOURCES,
                source="rag",
                metadata={
                    "sources": [
                        {
                            "type": "rag",
                            "kb_name": "personal:kb:course_crs_biology_src_bio",
                            "section": "Electron Transport",
                        }
                    ]
                },
            ),
            StreamEvent(
                type=StreamEventType.CONTENT,
                source="provider",
                content="Oxygen is the final electron acceptor.",
                metadata={"call_kind": "llm_final_response"},
            ),
            StreamEvent(type=StreamEventType.DONE, source="provider"),
        ],
    )
    source_event = next(event for event in finalized if event.type == StreamEventType.SOURCES)
    citation = source_event.metadata["course_citations"][0]

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    session = await store.create_session(course_id="crs_biology")
    await store.add_message(session["id"], "user", "Why is oxygen necessary?")
    await store.add_message(
        session["id"],
        "assistant",
        "Oxygen is the final electron acceptor.",
        events=[event.to_dict() for event in finalized],
    )

    reopened = await store.get_session_with_messages(session["id"])
    assert reopened is not None
    persisted = next(
        event
        for event in reopened["messages"][-1]["events"]
        if event["type"] == "sources"
    )["metadata"]["course_citations"][0]
    assert persisted == citation
    assert persisted["source_title_snapshot"] == "Lecture 6.pdf"

    archived_readiness = _readiness(
        [
            _source(
                "src_bio",
                state="archived",
                title="Renamed after the answer.pdf",
                revision=5,
                fingerprint="a" * 64,
            )
        ]
    )
    assert citation_version_available(persisted, archived_readiness) is False
    assert persisted["source_title_snapshot"] == "Lecture 6.pdf"


def test_general_study_remains_outside_course_chat(monkeypatch) -> None:
    service = SimpleNamespace(
        get=lambda _course_id: _course(workspace_kind="general_study"),
        list_sources=lambda _course_id: [_source("src_general")],
    )
    monkeypatch.setattr("deeptutor.courses.service.get_current_course_service", lambda: service)

    with pytest.raises(CourseUnavailableError, match="General Study"):
        resolve_course_turn_payload("crs_biology", {"knowledge_bases": []})
