from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEventType
from deeptutor.courses.deterministic_provider import build_index, course_chat_events, enabled
from deeptutor.courses.ingestion import run_source_operation
from deeptutor.courses.repository import CourseRepository
from deeptutor.courses.service import CourseService, resolve_course_turn_payload, source_kb_name
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def _embedding(text: str) -> list[int]:
    digest = hashlib.sha256(text.lower().encode()).digest()
    return [digest[0], digest[1], digest[2], digest[3]]


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
async def test_deterministic_course_provider_retrieval_and_provenance(
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
        initializer.kb_dir.mkdir(parents=True, exist_ok=True)
        (initializer.kb_dir / "deterministic-index.json").write_text(
            json.dumps({"chunks": [{"text": text, "embedding": _embedding(text)}]}),
            encoding="utf-8",
        )
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
            "uploaded_paths": [],
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
