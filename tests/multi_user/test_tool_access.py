"""Grant v2 tool/exec whitelists: normalization and runtime resolution."""

from __future__ import annotations

import pytest

from deeptutor.multi_user.grants import load_grant, normalize_grant, save_grant
from deeptutor.multi_user.tool_access import (
    allowed_mcp_tools,
    allowed_optional_tools,
    combine_whitelists,
    exec_override,
)
from deeptutor.services.sandbox.service import SandboxService
from deeptutor.services.sandbox.spec import ExecRequest, ExecResult, IsolationLevel


class _RecordingSandboxBackend:
    def __init__(self, level: IsolationLevel) -> None:
        self.level = level
        self.calls = 0

    async def health(self) -> tuple[bool, str]:
        return True, "healthy"

    async def exec(self, _request: ExecRequest) -> ExecResult:
        self.calls += 1
        return ExecResult(stdout="ran", exit_code=0)


def _sandbox_with_backend(level: IsolationLevel) -> tuple[SandboxService, _RecordingSandboxBackend]:
    backend = _RecordingSandboxBackend(level)
    service = SandboxService()
    service._backend = backend  # type: ignore[assignment]
    return service, backend


@pytest.fixture
def grantable_alice(mu_isolated_root, monkeypatch):
    """Make ``save_grant`` accept u_alice without a real identity record."""
    from deeptutor.multi_user import grants

    monkeypatch.setattr(
        grants,
        "get_user_by_id",
        lambda user_id: ("alice", {"role": "user"}) if user_id == "u_alice" else None,
    )
    return "u_alice"


def test_normalize_migrates_v1_to_v2():
    v1 = {
        "version": 1,
        "models": {
            "llm": [{"profile_id": "p", "model_ids": ["m"]}],
            "embedding": [{"profile_id": "e"}],
            "search": [{"profile_id": "s"}],
        },
        "knowledge_bases": [{"resource_id": "admin:kb:demo"}],
        "skills": [{"skill_id": "writer"}],
        "spaces": [{"space_id": "old"}],
    }
    grant = normalize_grant("u_alice", v1)
    assert grant["version"] == 2
    assert grant["models"] == {"llm": [{"profile_id": "p", "model_ids": ["m"]}]}
    assert "spaces" not in grant
    assert grant["knowledge_bases"] == [{"resource_id": "admin:kb:demo"}]
    assert grant["skills"] == [{"skill_id": "writer"}]
    # Absent v2 fields default to unrestricted.
    assert grant["enabled_tools"] is None
    assert grant["mcp_tools"] is None
    assert grant["exec_enabled"] is None


def test_normalize_tool_lists_and_exec():
    grant = normalize_grant(
        "u_alice",
        {
            "enabled_tools": ["web_search", "", "  reason  "],
            "mcp_tools": [],
            "exec_enabled": False,
        },
    )
    assert grant["enabled_tools"] == ["web_search", "reason"]
    assert grant["mcp_tools"] == []
    assert grant["exec_enabled"] is False
    # Non-bool values remain absent in storage and resolve deny-by-default for users.
    assert normalize_grant("u_alice", {"exec_enabled": "yes"})["exec_enabled"] is None


def test_admin_is_never_restricted(as_user):
    with as_user("u_admin", role="admin"):
        assert allowed_optional_tools() is None
        assert allowed_mcp_tools() is None
        assert exec_override() is None


def test_user_without_grant_keeps_builtins_unrestricted_but_denies_mcp_and_exec(
    as_user, mu_isolated_root
):
    with as_user("u_alice"):
        assert allowed_optional_tools() is None
        assert allowed_mcp_tools() == set()
        assert exec_override() is False


def test_user_whitelists_resolve_from_grant(as_user, grantable_alice):
    save_grant(
        grantable_alice,
        {
            "enabled_tools": ["web_search"],
            "mcp_tools": ["mcp_demo_search", "mcp_demo_write"],
            "exec_enabled": False,
        },
    )
    with as_user(grantable_alice):
        assert allowed_optional_tools() == {"web_search"}
        assert allowed_mcp_tools() == {"mcp_demo_search", "mcp_demo_write"}
        assert exec_override() is False


def test_saved_grant_round_trips_v2(grantable_alice):
    save_grant(grantable_alice, {"enabled_tools": ["reason"], "exec_enabled": False})
    loaded = load_grant(grantable_alice)
    assert loaded["version"] == 2
    assert loaded["enabled_tools"] == ["reason"]
    assert loaded["mcp_tools"] is None
    assert loaded["exec_enabled"] is False


def test_combine_whitelists():
    assert combine_whitelists(None, None) is None
    assert combine_whitelists({"a"}, None) == {"a"}
    assert combine_whitelists(None, {"b"}) == {"b"}
    assert combine_whitelists({"a", "b"}, {"b", "c"}) == {"b"}


def test_enabled_optional_tools_filtered_by_grant(as_user, grantable_alice, monkeypatch):
    from deeptutor.api.routers import settings as settings_router

    monkeypatch.setattr(
        settings_router,
        "load_ui_settings",
        lambda: {"enabled_optional_tools": ["web_search", "reason", "brainstorm"]},
    )
    save_grant(grantable_alice, {"enabled_tools": ["reason"]})
    with as_user(grantable_alice):
        assert settings_router.get_enabled_optional_tools() == ["reason"]


@pytest.mark.asyncio
async def test_sandbox_denies_user_with_missing_exec_grant(as_user, mu_isolated_root) -> None:
    service, backend = _sandbox_with_backend(IsolationLevel.SYSTEM)

    with as_user("u_alice"):
        result = await service.run(ExecRequest(command="echo denied"), user_id="u_alice")

    assert not result.ok
    assert result.error
    assert backend.calls == 0


@pytest.mark.asyncio
async def test_sandbox_allows_explicit_user_grant_only_on_system_isolation(
    as_user, grantable_alice
) -> None:
    save_grant(grantable_alice, {"exec_enabled": True})

    system_service, system_backend = _sandbox_with_backend(IsolationLevel.SYSTEM)
    with as_user(grantable_alice):
        system_result = await system_service.run(
            ExecRequest(command="echo allowed"), user_id=grantable_alice
        )

    assert system_result.ok
    assert system_backend.calls == 1

    application_service, application_backend = _sandbox_with_backend(IsolationLevel.APPLICATION)
    with as_user(grantable_alice):
        application_result = await application_service.run(
            ExecRequest(command="echo denied"), user_id=grantable_alice
        )

    assert not application_result.ok
    assert application_result.error
    assert application_backend.calls == 0


@pytest.mark.asyncio
async def test_sandbox_preserves_admin_execution_on_application_backend(as_user) -> None:
    service, backend = _sandbox_with_backend(IsolationLevel.APPLICATION)

    with as_user("u_admin", role="admin"):
        result = await service.run(ExecRequest(command="echo admin"), user_id="u_admin")

    assert result.ok
    assert backend.calls == 1


@pytest.mark.asyncio
async def test_sandbox_quota_identity_comes_from_request_principal(as_user) -> None:
    """A private/model-authored hint cannot select a fresh quota bucket."""
    service, backend = _sandbox_with_backend(IsolationLevel.APPLICATION)
    captured: list[str] = []

    class _Lease:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    class _Quota:
        async def acquire(self, user_id: str):
            captured.append(user_id)
            return _Lease()

    service._quota = _Quota()  # type: ignore[assignment]

    with as_user("u_admin", role="admin"):
        result = await service.run(
            ExecRequest(command="echo admin"),
            user_id="model-chosen-fresh-bucket",
        )

    assert result.ok
    assert backend.calls == 1
    assert captured == ["u_admin"]
