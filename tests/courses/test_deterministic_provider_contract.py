from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEventType
from deeptutor.courses.deterministic_provider import (
    build_index,
    course_chat_events,
    delay_ingestion_for_runtime_proof,
    enabled,
)
from deeptutor.courses.ingestion import run_source_operation
from deeptutor.courses.repository import CourseRepository
from deeptutor.courses.service import CourseService, resolve_course_turn_payload, source_kb_name
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


@pytest.mark.asyncio
async def test_runtime_proof_ingestion_delay_is_explicit_and_bounded(
    monkeypatch,
) -> None:
    delays: list[float] = []

    async def capture_delay(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(
        "deeptutor.courses.deterministic_provider.asyncio.sleep",
        capture_delay,
    )
    monkeypatch.setenv("TEEECHR_TEST_DETERMINISTIC_INGESTION_DELAY_MS", "90000")

    await delay_ingestion_for_runtime_proof()
    assert delays == []

    monkeypatch.setenv("TEEECHR_TEST_DETERMINISTIC_PROVIDER", "1")
    await delay_ingestion_for_runtime_proof()
    assert delays == [30.0]


@pytest.mark.asyncio
async def test_explicit_deterministic_provider_is_local_and_course_scoped(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("TEEECHR_TEST_DETERMINISTIC_PROVIDER", "1")
    assert enabled() is True
    kb_root = tmp_path / "knowledge_bases"
    raw = tmp_path / "notes.txt"
    raw.write_text("Known local-only course fact.", encoding="utf-8")
    kb_dir = kb_root / "course_crs_owned_src_owned"
    assert build_index(kb_dir, [str(raw)]) is True
    assert (kb_dir / "deterministic-index.json").stat().st_mode & 0o777 == 0o600

    user = CurrentUser(
        id="u_browser",
        username="browser",
        role="admin",
        scope=UserScope(kind="user", user_id="u_browser", root=tmp_path),
    )
    monkeypatch.setattr(
        "deeptutor.courses.deterministic_provider.get_personal_path_service",
        lambda _owner: SimpleNamespace(get_knowledge_bases_root=lambda: kb_root),
    )
    token = set_current_user(user)
    try:
        events = [
            event
            async for event in course_chat_events(
                UnifiedContext(
                    knowledge_bases=["personal:kb:course_crs_owned_src_owned"]
                )
            )
        ]
    finally:
        reset_current_user(token)

    assert [event.type for event in events] == [
        StreamEventType.SOURCES,
        StreamEventType.CONTENT,
        StreamEventType.DONE,
    ]
    assert events[1].content == (
        "Deterministic course answer: Known local-only course fact."
    )


@pytest.mark.asyncio
async def test_deterministic_provider_can_prove_unavailable_runtime_state(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("TEEECHR_TEST_DETERMINISTIC_PROVIDER", "1")
    kb_root = tmp_path / "knowledge_bases"
    kb_dir = kb_root / "course_crs_offline_src_offline"
    kb_dir.mkdir(parents=True)
    (kb_dir / "deterministic-index.json").write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "text": "This content must not be returned.",
                        "provider_error": "Deterministic provider unavailable for C1 proof",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    user = CurrentUser(
        id="u_browser",
        username="browser",
        role="admin",
        scope=UserScope(kind="user", user_id="u_browser", root=tmp_path),
    )
    monkeypatch.setattr(
        "deeptutor.courses.deterministic_provider.get_personal_path_service",
        lambda _owner: SimpleNamespace(get_knowledge_bases_root=lambda: kb_root),
    )
    token = set_current_user(user)
    try:
        events = [
            event
            async for event in course_chat_events(
                UnifiedContext(
                    knowledge_bases=["personal:kb:course_crs_offline_src_offline"]
                )
            )
        ]
    finally:
        reset_current_user(token)

    assert [event.type for event in events] == [
        StreamEventType.ERROR,
        StreamEventType.DONE,
    ]
    assert events[0].content == "Deterministic provider unavailable for C1 proof"
    assert events[0].metadata == {"turn_terminal": True, "status": "failed"}


@pytest.mark.asyncio
async def test_course_source_initialization_builds_exact_text_index_and_preserves_provenance(
    monkeypatch, tmp_path
) -> None:
    owner = "u_deterministic"
    db_path = tmp_path / "courses.db"
    kb_root = tmp_path / "knowledge_bases"
    repo = CourseRepository(db_path, owner)
    course = repo.create_course("Biology")
    course = repo.ensure_managed_kb_ref(course.id, f"personal:kb:course_{course.id}")
    text = "Mitochondria produce ATP through cellular respiration."
    fingerprint = hashlib.sha256(text.encode()).hexdigest()
    uploaded = tmp_path / "notes.txt"
    uploaded.write_text(text, encoding="utf-8")
    source = repo.create_source(
        course.id,
        kind="document",
        display_name="notes.txt",
        manifest=[{"path": "notes.txt", "size": len(text), "sha256": fingerprint}],
        content_sha256=fingerprint,
        operation_id="op_deterministic",
    )
    user = CurrentUser(
        id=owner,
        username="deterministic",
        role="user",
        scope=UserScope(kind="user", user_id=owner, root=tmp_path),
    )

    async def deterministic_provider(initializer, _task_id, *, finalize_task):
        assert finalize_task is False
        return True

    monkeypatch.setattr(
        "deeptutor.courses.ingestion._current_personal_user", lambda _owner: user
    )
    monkeypatch.setattr(
        "deeptutor.api.routers.knowledge.run_initialization_task", deterministic_provider
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.get_personal_path_service",
        lambda _owner: SimpleNamespace(get_courses_db=lambda: db_path),
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.TaskIDManager.get_instance",
        lambda: SimpleNamespace(
            get_task_metadata=lambda _task_id: {"status": "running"},
            update_task_status=lambda *_args, **_kwargs: None,
        ),
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.get_task_stream_manager",
        lambda: SimpleNamespace(
            emit_complete=lambda *_args, **_kwargs: None,
            emit_failed=lambda *_args, **_kwargs: None,
        ),
    )

    await run_source_operation(
        {
            "owner_user_id": owner,
            "course_id": course.id,
            "course_revision": course.revision,
            "course_write_epoch": course.write_epoch,
            "source_id": source.id,
            "source_revision": source.revision,
            "operation_id": source.operation_id,
            "kb_name": source_kb_name(course.id, source.id),
            "base_dir": str(kb_root),
            "uploaded_paths": [str(uploaded)],
            "rag_provider": "llamaindex",
            "initialize": True,
        }
    )
    assert repo.get_source(course.id, source.id).state == "ready"

    service = CourseService(repo)
    monkeypatch.setattr(
        "deeptutor.courses.service.get_current_course_service", lambda: service
    )
    resolved = resolve_course_turn_payload(course.id, {"knowledge_bases": []})
    assert resolved["course_context"]["source_fingerprints"] == {
        source.id: fingerprint
    }

    index = json.loads(
        (kb_root / source_kb_name(course.id, source.id) / "deterministic-index.json").read_text()
    )
    retrieved = index["chunks"][0]["text"]
    response = f"Grounded answer: {retrieved}"
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    session = await store.create_session(course_id=course.id)
    await store.add_message(
        session["id"],
        "user",
        "What produces ATP?",
        metadata={"request_snapshot": resolved["course_context"]},
    )
    await store.add_message(session["id"], "assistant", response)

    detail = await store.get_session_with_messages(session["id"])
    assert detail is not None
    assert detail["messages"][0]["metadata"]["request_snapshot"]["source_ids"] == [
        source.id
    ]
    assert detail["messages"][1]["content"] == (
        "Grounded answer: Mitochondria produce ATP through cellular respiration."
    )
