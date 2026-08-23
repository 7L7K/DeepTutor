"""Tests for the subagent capability: binding, activation, tool budget/streaming.

The capability is the connected-agent twin of Obsidian — selecting a
``type: subagent`` KB runs the turn exclusively on ``consult_subagent``. These
tests stub the KB metadata resolver and the backend, so nothing spawns a real
CLI; they verify the wiring (binding, exclusivity, injected spec) and the tool's
authoritative consult-budget + session continuity + event streaming.
"""

from __future__ import annotations

import pytest

from deeptutor.agents._shared.tool_composition import ToolMountFlags, compose_enabled_tools
from deeptutor.capabilities import any_exclusive_capability_active
from deeptutor.capabilities.subagent import (
    SUBAGENT_TOOL_NAMES,
    ConsultSubagentTool,
    SubagentCapability,
    connection_for_turn,
)
from deeptutor.capabilities.subagent import binding as subagent_binding
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.registry.tool_registry import get_tool_registry
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.types import ConsultResult, SubagentEvent


def _bind(
    monkeypatch,
    *,
    kind: str = "claude_code",
    cwd: str = "",
    name: str = "myagent",
    partner_id: str = "",
) -> None:
    """Make ``resolve_kb_metadata`` report ``name`` as a connected subagent."""
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
        lambda ref: (
            {
                "name": ref,
                "type": "subagent",
                "agent_kind": kind,
                "cwd": cwd,
                "partner_id": partner_id,
            }
            if ref == name
            else {"name": ref, "type": None}
        ),
    )


# ---- binding & activation ----------------------------------------------------


def test_inactive_without_subagent_kb(monkeypatch) -> None:
    _bind(monkeypatch)
    cap = SubagentCapability()
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["plain-kb"])
    assert cap.is_active(ctx) is False
    assert cap.system_block(ctx, language="en", prompts={}) is None


def test_active_injects_spec_and_min_rounds(monkeypatch) -> None:
    _bind(monkeypatch, kind="codex", cwd="/tmp/proj")
    cap = SubagentCapability()
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["myagent"])
    assert cap.is_active(ctx) is True
    assert tuple(cap.owned_tools) == SUBAGENT_TOOL_NAMES

    block = cap.system_block(ctx, language="en", prompts={})
    assert block is not None and "myagent" in block.content
    # The loop budget floor is lifted so the full consult budget + a finish
    # round always fit.
    assert ctx.metadata.get("_min_loop_rounds", 0) >= 2

    spec = cap.augment_kwargs("consult_subagent", {"question": "q"}, ctx)["_subagent"]
    assert spec["kind"] == "codex"
    assert spec["cwd"] == "/tmp/proj"
    assert spec["budget"] >= 1
    assert isinstance(spec["config"], BackendConfig)
    assert spec["state"] == {"count": 0, "session_id": None, "name": "myagent"}
    # Never injected for a non-owned tool.
    assert "_subagent" not in cap.augment_kwargs("rag", {}, ctx)


def test_consult_budget_override_from_config(monkeypatch) -> None:
    _bind(monkeypatch)
    cap = SubagentCapability()
    # Per-turn override from the composer (request config) wins over the default.
    ctx = UnifiedContext(
        user_message="hi",
        knowledge_bases=["myagent"],
        config_overrides={"subagent_consult_budget": 3},
    )
    assert (
        cap.augment_kwargs("consult_subagent", {"question": "q"}, ctx)["_subagent"]["budget"] == 3
    )
    # Out-of-range values are clamped, not trusted.
    ctx_hi = UnifiedContext(
        user_message="hi",
        knowledge_bases=["myagent"],
        config_overrides={"subagent_consult_budget": 999},
    )
    assert (
        cap.augment_kwargs("consult_subagent", {"question": "q"}, ctx_hi)["_subagent"]["budget"]
        == 12
    )


def test_binding_cached(monkeypatch) -> None:
    calls = {"n": 0}

    def fake(ref):
        calls["n"] += 1
        return {"name": ref, "type": "subagent", "agent_kind": "claude_code", "cwd": ""}

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_kb_metadata", fake)
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["a"])
    subagent_binding.connection_for_turn(ctx)
    subagent_binding.connection_for_turn(ctx)
    assert calls["n"] == 1  # second call hits the per-turn cache


def test_cached_admin_local_connection_cannot_replay_for_learner(
    monkeypatch,
    tmp_path,
) -> None:
    """A cached binding is data, not authority across principal changes."""
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    _bind(monkeypatch, kind="claude_code", name="AdminClaude", cwd="/admin/workspace")
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["AdminClaude"])
    admin = CurrentUser(
        id="u_admin",
        username="admin",
        role="admin",
        scope=UserScope(kind="admin", user_id="u_admin", root=tmp_path / "admin"),
    )
    learner = CurrentUser(
        id="u_learner",
        username="learner",
        role="user",
        scope=UserScope(kind="user", user_id="u_learner", root=tmp_path / "learner"),
    )

    admin_token = set_current_user(admin)
    try:
        assert subagent_binding.connection_for_turn(ctx) is not None
    finally:
        reset_current_user(admin_token)

    learner_token = set_current_user(learner)
    try:
        assert subagent_binding.connection_for_turn(ctx) is None
        assert SubagentCapability().is_active(ctx) is False
    finally:
        reset_current_user(learner_token)


def test_cached_admin_local_connection_cannot_replay_without_auth_context(
    monkeypatch,
    tmp_path,
) -> None:
    from deeptutor.multi_user import context as user_context
    from deeptutor.multi_user.models import CurrentUser, UserScope
    from deeptutor.services import auth as auth_service

    _bind(monkeypatch, kind="claude_code", name="AdminClaude", cwd="/admin/workspace")
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["AdminClaude"])
    admin = CurrentUser(
        id="u_admin",
        username="admin",
        role="admin",
        scope=UserScope(kind="admin", user_id="u_admin", root=tmp_path / "admin"),
    )
    admin_token = user_context.set_current_user(admin)
    try:
        assert subagent_binding.connection_for_turn(ctx) is not None
    finally:
        user_context.reset_current_user(admin_token)

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    empty_token = user_context._current_user.set(None)
    try:
        assert subagent_binding.connection_for_turn(ctx) is None
        assert SubagentCapability().is_active(ctx) is False
    finally:
        user_context.reset_current_user(empty_token)


def test_local_subagent_binding_is_reserved_for_admins(monkeypatch, tmp_path) -> None:
    """Assigned metadata cannot let a learner activate a host CLI."""
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    _bind(monkeypatch, kind="claude_code", name="AdminClaude", cwd="/admin/workspace")
    cap = SubagentCapability()

    learner = CurrentUser(
        id="u_learner",
        username="learner",
        role="user",
        scope=UserScope(kind="user", user_id="u_learner", root=tmp_path / "learner"),
    )
    learner_token = set_current_user(learner)
    try:
        learner_turn = UnifiedContext(user_message="hi", knowledge_bases=["AdminClaude"])
        assert subagent_binding.connection_for_turn(learner_turn) is None
        assert cap.is_active(learner_turn) is False
        assert subagent_binding.subagent_refs(learner_turn) == set()
    finally:
        reset_current_user(learner_token)

    admin = CurrentUser(
        id="u_admin",
        username="admin",
        role="admin",
        scope=UserScope(kind="admin", user_id="u_admin", root=tmp_path / "admin"),
    )
    admin_token = set_current_user(admin)
    try:
        admin_turn = UnifiedContext(user_message="hi", knowledge_bases=["AdminClaude"])
        assert cap.is_active(admin_turn) is True
        assert subagent_binding.connection_for_turn(admin_turn) == {
            "name": "AdminClaude",
            "kind": "claude_code",
            "cwd": "/admin/workspace",
            "partner_id": "",
        }
    finally:
        reset_current_user(admin_token)


def test_revoked_partner_binding_is_inert_before_the_consult_tool(monkeypatch) -> None:
    """A persisted Partner KB is not sufficient after its grant is revoked."""
    from fastapi import HTTPException
    from deeptutor.multi_user import partner_access

    allowed = {"value": True}

    def recheck_assignment(partner_id: str) -> None:
        assert partner_id == "paul"
        if not allowed["value"]:
            raise HTTPException(status_code=403, detail="Partner is not assigned to you")

    monkeypatch.setattr(partner_access, "assert_partner_allowed", recheck_assignment)
    _bind(monkeypatch, kind="partner", name="Paul", partner_id="paul")
    cap = SubagentCapability()

    partner_turn = UnifiedContext(user_message="hi", knowledge_bases=["Paul"])
    assert cap.is_active(partner_turn) is True

    allowed["value"] = False
    # Reusing the exact context must not replay the cached, formerly-authorized
    # Partner connection after its grant changes.
    assert subagent_binding.connection_for_turn(partner_turn) is None
    assert cap.is_active(partner_turn) is False
    revoked_turn = UnifiedContext(user_message="hi", knowledge_bases=["Paul"])
    assert subagent_binding.connection_for_turn(revoked_turn) is None
    assert cap.is_active(revoked_turn) is False
    assert subagent_binding.subagent_refs(revoked_turn) == set()
    # Without a server-injected connection spec, the consult tool cannot invoke
    # a Partner for the revoked selection.
    assert cap.augment_kwargs("consult_subagent", {"question": "q"}, revoked_turn) == {
        "question": "q"
    }


# ---- exclusivity -------------------------------------------------------------


def test_exclusive_compose_drops_builtins_but_keeps_coexisting_rag() -> None:
    # Issue #650: the KB built-ins coexist when has_kb is set (a co-selected
    # real KB the capability does not own is both searchable and enumerable);
    # other built-ins/toggles stay dropped.
    composed = compose_enabled_tools(
        registry=get_tool_registry(),
        requested_tools=["web_search", "rag"],
        optional_whitelist=["web_search", "rag"],
        mount_flags=ToolMountFlags(has_kb=True, has_code=True, has_memory=True),
        capability_owned=["consult_subagent"],
        exclusive=True,
    )
    assert set(composed) == {"consult_subagent", "rag", "kb_files", "ask_user"}


def test_exclusive_compose_pure_subagent_mounts_no_rag() -> None:
    composed = compose_enabled_tools(
        registry=get_tool_registry(),
        requested_tools=["web_search"],
        optional_whitelist=["web_search"],
        mount_flags=ToolMountFlags(has_kb=False),
        capability_owned=["consult_subagent"],
        exclusive=True,
    )
    assert set(composed) == {"consult_subagent", "ask_user"}


def test_registry_flags_subagent_turn_as_exclusive(monkeypatch) -> None:
    _bind(monkeypatch)
    subagent_turn = UnifiedContext(user_message="hi", knowledge_bases=["myagent"])
    plain_turn = UnifiedContext(user_message="hi", knowledge_bases=["plain-kb"])
    assert any_exclusive_capability_active(subagent_turn) is True
    assert any_exclusive_capability_active(plain_turn) is False


def test_owned_kbs_reports_only_agent_ref(monkeypatch) -> None:
    # Issue #650: the agent ref is owned (consulted, not rag'd); a co-selected
    # LlamaIndex KB is not owned, so it keeps its rag surface.
    _bind(monkeypatch)  # only "myagent" resolves as a subagent
    cap = SubagentCapability()
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["myagent", "kb-plain"])
    assert cap.owned_kbs(ctx) == {"myagent"}
    assert subagent_binding.subagent_refs(ctx) == {"myagent"}


# ---- consult tool ------------------------------------------------------------


class _FakeBackend:
    kind = "claude_code"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.last_images: list[str] | None = None

    async def consult(
        self, question, *, on_event, cwd, session_id, config, images=None, partner_id=None
    ):
        self.calls.append((question, session_id))
        self.last_images = images
        await on_event(SubagentEvent(kind="tool", text="$ ls"))
        await on_event(SubagentEvent(kind="result", text=f"answer:{question}"))
        return ConsultResult(
            final_text=f"answer:{question}",
            session_id="sess-1",
            success=True,
            event_count=2,
        )


def _spec(state: dict, *, budget: int = 2) -> dict:
    return {
        "kind": "claude_code",
        "cwd": "",
        "name": "myagent",
        "budget": budget,
        "config": BackendConfig(),
        "state": state,
    }


@pytest.mark.asyncio
async def test_consult_streams_events_and_threads_session(monkeypatch) -> None:
    backend = _FakeBackend()
    monkeypatch.setattr("deeptutor.services.subagent.get_backend", lambda kind: backend)
    tool = ConsultSubagentTool()
    state: dict = {"count": 0, "session_id": None, "name": "myagent"}
    streamed: list[tuple[str, str, str]] = []

    async def sink(event_type, message, metadata=None):
        streamed.append((event_type, message, (metadata or {}).get("subagent_channel", "")))

    res1 = await tool.execute(question="Q1", _subagent=_spec(state), event_sink=sink)
    assert res1.success is True
    assert "answer:Q1" in res1.content
    assert state["count"] == 1
    assert state["session_id"] == "sess-1"  # captured for continuity
    # Every native event streamed out under the single subagent trace_kind.
    assert all(etype == "subagent_event" for etype, _, _ in streamed)
    channels = {chan for _, _, chan in streamed}
    assert "tool" in channels and "result" in channels

    # Second consult resumes the same backend session.
    await tool.execute(question="Q2", _subagent=_spec(state), event_sink=sink)
    assert backend.calls[1] == ("Q2", "sess-1")


@pytest.mark.asyncio
async def test_consult_budget_is_authoritative(monkeypatch) -> None:
    backend = _FakeBackend()
    monkeypatch.setattr("deeptutor.services.subagent.get_backend", lambda kind: backend)
    tool = ConsultSubagentTool()
    state: dict = {"count": 0, "session_id": None, "name": "myagent"}

    async def sink(*_a, **_k):
        return None

    await tool.execute(question="Q1", _subagent=_spec(state, budget=1), event_sink=sink)
    # Budget of 1 is spent → the second consult is refused without driving the backend.
    refused = await tool.execute(question="Q2", _subagent=_spec(state, budget=1), event_sink=sink)
    assert refused.success is False
    assert "budget" in refused.content.lower()
    assert len(backend.calls) == 1  # backend never invoked the second time


@pytest.mark.asyncio
async def test_learner_tool_refuses_local_spec_before_backend_or_budget(
    monkeypatch,
    tmp_path,
) -> None:
    """The execution seam rejects forged/stale local CLI specs without side effects."""
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    calls: list[str] = []

    def should_not_resolve_backend(kind: str):
        calls.append(kind)
        raise AssertionError("learner local CLI spec must not reach backend resolution")

    monkeypatch.setattr("deeptutor.services.subagent.get_backend", should_not_resolve_backend)
    learner = CurrentUser(
        id="u_learner",
        username="learner",
        role="user",
        scope=UserScope(kind="user", user_id="u_learner", root=tmp_path / "learner"),
    )
    token = set_current_user(learner)
    try:
        state = {"count": 0, "session_id": None, "name": "AdminClaude"}
        result = await ConsultSubagentTool().execute(
            question="hello",
            _subagent={
                "kind": "claude_code",
                "cwd": "/admin/workspace",
                "name": "AdminClaude",
                "budget": 2,
                "config": BackendConfig(),
                "state": state,
            },
        )
    finally:
        reset_current_user(token)

    assert result.success is False
    assert "administrator" in result.content.lower()
    assert calls == []
    assert state == {"count": 0, "session_id": None, "name": "AdminClaude"}


@pytest.mark.asyncio
async def test_missing_auth_context_refuses_spec_before_backend_or_budget(monkeypatch) -> None:
    """A lost auth ContextVar is denial, never implicit local-admin authority."""
    from deeptutor.multi_user import context as user_context
    from deeptutor.services import auth as auth_service

    calls: list[str] = []

    def should_not_resolve_backend(kind: str):
        calls.append(kind)
        raise AssertionError("missing authority must not reach backend resolution")

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr("deeptutor.services.subagent.get_backend", should_not_resolve_backend)
    token = user_context._current_user.set(None)
    state = {"count": 0, "session_id": None, "name": "AdminClaude"}
    try:
        result = await ConsultSubagentTool().execute(
            question="hello",
            _subagent={
                "kind": "claude_code",
                "cwd": "/admin/workspace",
                "name": "AdminClaude",
                "budget": 2,
                "config": BackendConfig(),
                "state": state,
            },
        )
    finally:
        user_context.reset_current_user(token)

    assert result.success is False
    assert "context is unavailable" in result.content.lower()
    assert calls == []
    assert state == {"count": 0, "session_id": None, "name": "AdminClaude"}


@pytest.mark.asyncio
async def test_revoked_partner_spec_refuses_before_backend_or_budget(
    monkeypatch,
    tmp_path,
) -> None:
    from fastapi import HTTPException

    from deeptutor.multi_user import partner_access
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    calls: list[str] = []

    def deny(partner_id: str) -> None:
        assert partner_id == "paul"
        raise HTTPException(status_code=403, detail="Partner is not assigned to you")

    def should_not_resolve_backend(kind: str):
        calls.append(kind)
        raise AssertionError("revoked Partner spec must not reach backend resolution")

    monkeypatch.setattr(partner_access, "assert_partner_allowed", deny)
    monkeypatch.setattr("deeptutor.services.subagent.get_backend", should_not_resolve_backend)
    learner = CurrentUser(
        id="u_learner",
        username="learner",
        role="user",
        scope=UserScope(kind="user", user_id="u_learner", root=tmp_path / "learner"),
    )
    token = set_current_user(learner)
    state = {"count": 0, "session_id": None, "name": "Paul"}
    try:
        result = await ConsultSubagentTool().execute(
            question="hello",
            _subagent={
                "kind": "partner",
                "partner_id": "paul",
                "name": "Paul",
                "budget": 2,
                "config": BackendConfig(),
                "state": state,
            },
        )
    finally:
        reset_current_user(token)

    assert result.success is False
    assert result.content == "Partner is not assigned to you"
    assert calls == []
    assert state == {"count": 0, "session_id": None, "name": "Paul"}


@pytest.mark.asyncio
async def test_consult_without_spec_is_graceful() -> None:
    res = await ConsultSubagentTool().execute(question="hi")
    assert res.success is False and "no subagent" in res.content.lower()


@pytest.mark.asyncio
async def test_session_id_persists_across_turns(monkeypatch, tmp_path) -> None:
    # A backend session id captured in one turn is remembered (keyed by chat
    # session + connection) and resumed by the next turn's augment_kwargs — so
    # the local agent keeps context across DeepTutor's separate messages.
    from deeptutor.services.subagent import sessions as sess

    monkeypatch.setattr(sess, "_path", lambda: tmp_path / "subagent_sessions.json")
    _bind(monkeypatch)  # "myagent" → claude_code
    backend = _FakeBackend()
    monkeypatch.setattr("deeptutor.services.subagent.get_backend", lambda kind: backend)

    cap = SubagentCapability()
    tool = ConsultSubagentTool()

    async def sink(*_a, **_k):
        return None

    # Turn 1: nothing remembered yet → consult creates "sess-1", which persists.
    ctx1 = UnifiedContext(user_message="hi", knowledge_bases=["myagent"], session_id="chatA")
    spec1 = cap.augment_kwargs("consult_subagent", {"question": "Q1"}, ctx1)["_subagent"]
    assert spec1["state"]["session_id"] is None
    await tool.execute(question="Q1", _subagent=spec1, event_sink=sink)
    assert sess.get_session(sess.session_key("chatA", "myagent")) == "sess-1"

    # Turn 2 (fresh context): augment_kwargs seeds the remembered session.
    ctx2 = UnifiedContext(user_message="more", knowledge_bases=["myagent"], session_id="chatA")
    spec2 = cap.augment_kwargs("consult_subagent", {"question": "Q2"}, ctx2)["_subagent"]
    assert spec2["state"]["session_id"] == "sess-1"

    # A different chat session does not inherit the agent session.
    ctx3 = UnifiedContext(user_message="hi", knowledge_bases=["myagent"], session_id="chatB")
    spec3 = cap.augment_kwargs("consult_subagent", {"question": "Q"}, ctx3)["_subagent"]
    assert spec3["state"]["session_id"] is None
