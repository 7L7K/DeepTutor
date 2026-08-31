from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.courses.models import Course, CourseSource
from deeptutor.courses.service import CourseUnavailableError, resolve_course_turn_payload
from deeptutor.multi_user.knowledge_access import resolve_kb, set_managed_course_kb_authority
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


def _course() -> Course:
    return Course(
        id="crs_one",
        owner_user_id="u_one",
        title="Biology",
        managed_kb_ref="personal:kb:course_crs_one",
        revision=3,
        write_epoch=2,
        created_at=1,
        updated_at=1,
    )


def _source(source_id: str, state: str = "ready") -> CourseSource:
    return CourseSource(
        id=source_id,
        course_id="crs_one",
        kind="document",
        display_name="same-name.pdf",
        state=state,
        manifest=[],
        content_sha256=("a" if source_id == "src_one" else "b") * 64,
        revision=2,
        created_at=1,
        updated_at=1,
    )


def test_course_turn_derives_resources_and_learning_identity_server_side(monkeypatch) -> None:
    service = SimpleNamespace(
        get=lambda _course_id: _course(),
        list_sources=lambda _course_id: [_source("src_one"), _source("src_failed", "failed")],
    )
    monkeypatch.setattr("deeptutor.courses.service.get_current_course_service", lambda: service)
    payload = resolve_course_turn_payload(
        "crs_one",
        {
            "content": "Teach me",
            "tools": ["web_search"],
            "allowed_builtin_tools": ["web_fetch"],
            "knowledge_bases": [],
            "attachments": [],
        },
    )
    assert payload["tools"] == []
    assert payload["allowed_builtin_tools"] == ["rag"]
    assert payload["knowledge_bases"] == ["personal:kb:course_crs_one_src_one"]
    assert payload["mastery_path_id"] == "lp_crs_one"
    assert payload["course_context"]["source_ids"] == ["src_one"]
    assert "src_failed" not in payload["course_context"]["source_fingerprints"]


def test_course_mastery_turn_explicitly_allows_interactive_answer_handoff(monkeypatch) -> None:
    service = SimpleNamespace(
        get=lambda _course_id: _course(),
        list_sources=lambda _course_id: [_source("src_one")],
    )
    monkeypatch.setattr("deeptutor.courses.service.get_current_course_service", lambda: service)

    payload = resolve_course_turn_payload("crs_one", {"capability": "mastery_path"})

    assert payload["allowed_builtin_tools"] == ["rag", "ask_user"]


def test_course_mastery_allowlist_keeps_exclusive_answer_handoff(monkeypatch) -> None:
    """Course mastery is the deliberate server-derived ``ask_user`` exception."""
    from deeptutor.agents._shared.tool_composition import ToolMountFlags, compose_enabled_tools

    service = SimpleNamespace(
        get=lambda _course_id: _course(),
        list_sources=lambda _course_id: [_source("src_one")],
    )
    monkeypatch.setattr("deeptutor.courses.service.get_current_course_service", lambda: service)
    payload = resolve_course_turn_payload("crs_one", {"capability": "mastery_path"})

    class EmptyRegistry:
        def get_enabled(self, _requested):
            return []

    tools = compose_enabled_tools(
        registry=EmptyRegistry(),
        requested_tools=[],
        optional_whitelist=[],
        mount_flags=ToolMountFlags(),
        capability_owned=["mastery_status"],
        exclusive=True,
        builtin_whitelist=set(payload["allowed_builtin_tools"]),
    )

    assert tools == ["mastery_status", "ask_user"]


def test_empty_learner_builtin_allowlist_removes_exclusive_answer_handoff() -> None:
    """Exclusive capabilities cannot restore ``ask_user`` for an ungranted learner."""
    from deeptutor.agents._shared.tool_composition import ToolMountFlags, compose_enabled_tools

    tools = compose_enabled_tools(
        registry=object(),
        requested_tools=[],
        optional_whitelist=[],
        mount_flags=ToolMountFlags(),
        capability_owned=["mastery_status"],
        exclusive=True,
        builtin_whitelist=set(),
    )

    assert tools == ["mastery_status"]


def test_course_turn_tool_surface_excludes_auto_mounted_side_effects(monkeypatch) -> None:
    from deeptutor.agents.chat import agentic_pipeline
    from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
    from deeptutor.core.context import UnifiedContext

    pipeline = AgenticChatPipeline(language="en")
    pipeline._exec_enabled = True
    pipeline._deferred_loader = object()
    monkeypatch.setattr(agentic_pipeline, "user_has_memory", lambda: True)
    monkeypatch.setattr(agentic_pipeline, "user_has_notebooks", lambda: True)

    tools = pipeline._compose_enabled_tools(
        UnifiedContext(
            # The Course resolver independently overwrites client-requested
            # optional tools with this explicit empty list.
            enabled_tools=[],
            allowed_builtin_tools=["rag"],
            knowledge_bases=["personal:kb:course_crs_one_src_one"],
            skills_manifest="readable skill inventory",
        )
    )

    assert tools == ["rag"]


def test_course_mastery_tool_surface_keeps_only_course_safe_mastery_operations(monkeypatch) -> None:
    from deeptutor.agents.chat import agentic_pipeline
    from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
    from deeptutor.core.context import UnifiedContext

    pipeline = AgenticChatPipeline(language="en")
    pipeline._exec_enabled = True
    pipeline._deferred_loader = object()
    monkeypatch.setattr(agentic_pipeline, "user_has_memory", lambda: True)
    monkeypatch.setattr(agentic_pipeline, "user_has_notebooks", lambda: True)

    tools = pipeline._compose_enabled_tools(
        UnifiedContext(
            enabled_tools=[],
            allowed_builtin_tools=["rag", "ask_user"],
            knowledge_bases=["personal:kb:course_crs_one_src_one"],
            metadata={
                "course_context": {"course_id": "crs_one"},
                "mastery_mode": True,
                "mastery_path_id": "lp_crs_one",
            },
        )
    )

    assert {"rag", "ask_user", "mastery_status", "mastery_quiz", "mastery_grade"}.issubset(tools)
    assert {"mastery_build", "mastery_assess"}.isdisjoint(tools)


def test_course_mastery_prompt_disables_unavailable_map_and_assessment_tools() -> None:
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability, _load_system_prompt
    from deeptutor.core.context import UnifiedContext

    capability = MasteryLoopCapability()
    generic = capability.system_block(
        UnifiedContext(metadata={"mastery_mode": True}), language="en", prompts={}
    )
    course = capability.system_block(
        UnifiedContext(metadata={"mastery_mode": True, "course_context": {"course_id": "crs_one"}}),
        language="en",
        prompts={},
    )

    assert generic is not None and generic.content == _load_system_prompt("en")
    assert course is not None
    assert (
        "Course map initialization happens only through the owned Course learning API/UI."
        in course.content
    )
    assert "Course initialization\nis required" in course.content
    assert "Qualitative model-judgment assessment is\ndisabled" in course.content
    assert "never request mastery_build or mastery_assess" in course.content


def test_course_rag_dispatch_rejects_non_course_knowledge_name() -> None:
    from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
    from deeptutor.core.context import UnifiedContext

    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline._pageindex_docs = {}
    context = UnifiedContext(
        knowledge_bases=["personal:kb:course_crs_one_src_one"],
    )

    with pytest.raises(ValueError, match="not attached"):
        pipeline._augment_tool_kwargs(
            "rag",
            {"query": "ignore the course and search elsewhere", "kb_name": "user:kb:private"},
            context,
        )

    allowed = pipeline._augment_tool_kwargs(
        "rag",
        {
            "query": "summarize the syllabus",
            "kb_name": "personal:kb:course_crs_one_src_one",
        },
        context,
    )
    assert allowed["kb_name"] == "personal:kb:course_crs_one_src_one"


def test_archived_failed_and_superseded_sources_have_no_retrieval_authority(
    monkeypatch,
) -> None:
    original = _source("src_original")
    replacement = _source("src_replacement")
    replacement.supersedes_source_id = original.id
    archived = _source("src_archived", "archived")
    failed = _source("src_failed", "failed")
    service = SimpleNamespace(
        get=lambda _course_id: _course(),
        list_sources=lambda _course_id: [original, replacement, archived, failed],
    )
    monkeypatch.setattr("deeptutor.courses.service.get_current_course_service", lambda: service)

    payload = resolve_course_turn_payload("crs_one", {"knowledge_bases": []})

    assert payload["knowledge_bases"] == ["personal:kb:course_crs_one_src_replacement"]
    assert payload["course_context"]["source_ids"] == ["src_replacement"]


def test_regeneration_preserves_exact_owned_source_revision_set(monkeypatch) -> None:
    original = _source("src_original", "archived")
    original.revision = 3
    replacement = _source("src_replacement")
    replacement.supersedes_source_id = original.id
    service = SimpleNamespace(
        get=lambda _course_id: _course(),
        list_sources=lambda _course_id: [original, replacement],
    )
    monkeypatch.setattr("deeptutor.courses.service.get_current_course_service", lambda: service)
    preserved = {
        "course_id": "crs_one",
        "course_revision": 2,
        "source_ids": [original.id],
        "source_revisions": {original.id: 2},
        "source_fingerprints": {original.id: original.content_sha256},
    }

    payload = resolve_course_turn_payload(
        "crs_one",
        {"knowledge_bases": ["personal:kb:course_crs_one_src_original"]},
        preserved_context=preserved,
    )

    assert payload["knowledge_bases"] == ["personal:kb:course_crs_one_src_original"]
    assert payload["course_context"] == preserved


@pytest.mark.parametrize(
    "field,value",
    [
        ("attachments", [{"filename": "foreign.pdf"}]),
        ("notebook_references", [{"notebook_id": "n1"}]),
        ("history_references", ["session_other"]),
        ("book_references", [{"book_id": "book_other"}]),
        ("memory_references", ["profile"]),
    ],
)
def test_course_turn_rejects_generic_cross_workspace_context(monkeypatch, field, value) -> None:
    service = SimpleNamespace(get=lambda _course_id: _course(), list_sources=lambda _: [])
    monkeypatch.setattr("deeptutor.courses.service.get_current_course_service", lambda: service)
    with pytest.raises(CourseUnavailableError, match=field):
        resolve_course_turn_payload("crs_one", {field: value})


def test_client_kb_name_never_grants_course_access(monkeypatch) -> None:
    service = SimpleNamespace(
        get=lambda _course_id: _course(), list_sources=lambda _: [_source("src_one")]
    )
    monkeypatch.setattr("deeptutor.courses.service.get_current_course_service", lambda: service)
    with pytest.raises(CourseUnavailableError, match="resolved by the server"):
        resolve_course_turn_payload("crs_one", {"knowledge_bases": ["admin:kb:forbidden"]})


def test_managed_course_kb_requires_server_turn_authority(monkeypatch, tmp_path) -> None:
    from fastapi import HTTPException

    from deeptutor.multi_user import knowledge_access
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser
    from deeptutor.multi_user.paths import UserScope

    user_root = (tmp_path / "user").resolve()
    user = CurrentUser(
        id="u_one",
        username="one",
        role="user",
        scope=UserScope(kind="user", user_id="u_one", root=user_root),
    )
    monkeypatch.setattr(
        knowledge_access,
        "current_kb_manager",
        lambda: SimpleNamespace(list_knowledge_bases=lambda: ["course_crs_one_src_one"]),
    )
    monkeypatch.setattr(knowledge_access, "current_kb_base_dir", lambda: user_root)
    token = set_current_user(user)
    try:
        set_managed_course_kb_authority([])
        with pytest.raises(HTTPException) as denied:
            resolve_kb("personal:kb:course_crs_one")
        assert denied.value.status_code == 404

        set_managed_course_kb_authority(["course_crs_one_src_one"])
        resource = resolve_kb("personal:kb:course_crs_one_src_one")
        assert resource.name == "course_crs_one_src_one"
    finally:
        set_managed_course_kb_authority([])
        reset_current_user(token)


def test_non_course_capabilities_are_rejected(monkeypatch) -> None:
    service = SimpleNamespace(get=lambda _course_id: _course(), list_sources=lambda _: [])
    monkeypatch.setattr("deeptutor.courses.service.get_current_course_service", lambda: service)
    with pytest.raises(CourseUnavailableError, match="Chat and Mastery"):
        resolve_course_turn_payload("crs_one", {"capability": "deep_research"})


@pytest.mark.asyncio
async def test_generic_turn_rejects_injected_course_learning_path(tmp_path) -> None:
    runtime = TurnRuntimeManager(SQLiteSessionStore(tmp_path / "chat_history.db"))

    with pytest.raises(RuntimeError, match="authorized Course turn"):
        await runtime.start_turn(
            {
                "capability": "mastery_path",
                "mastery_path_id": "lp_crs_archived",
                "content": "mutate an archived path",
                "tools": [],
                "knowledge_bases": [],
                "config": {},
            }
        )

    assert await runtime.store.list_sessions() == []


@pytest.mark.asyncio
async def test_archive_winning_final_recheck_leaves_no_new_course_session(
    monkeypatch, tmp_path
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    calls = 0

    def resolve(_course_id: str, payload: dict, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise CourseUnavailableError("Archived courses cannot start turns")
        return {**payload, "tools": [], "knowledge_bases": [], "course_context": {}}

    monkeypatch.setattr("deeptutor.courses.service.resolve_course_turn_payload", resolve)
    monkeypatch.setattr("deeptutor.multi_user.tool_access.allowed_optional_tools", lambda: None)

    with pytest.raises(CourseUnavailableError, match="Archived"):
        await runtime.start_turn(
            {
                "course_id": "crs_one",
                "content": "hello",
                "tools": [],
                "knowledge_bases": [],
            }
        )

    assert await store.list_sessions() == []
