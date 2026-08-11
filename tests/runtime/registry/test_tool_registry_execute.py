"""ToolRegistry.execute: tool-name arg must not collide with a tool's own params.

Regression for the ``read_skill(name=...)`` dispatch bug: the registry takes
the tool *name* as its first parameter, which collided with any tool whose
schema declares a ``name`` argument (read_skill, and potentially MCP tools).
The fix makes the tool-name parameter positional-only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.runtime.registry.tool_registry import ToolRegistry


@pytest.fixture(autouse=True)
def _disable_local_auth_for_registry_unit_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ordinary dispatch tests independent of local auth settings."""
    monkeypatch.setattr("deeptutor.services.auth.AUTH_ENABLED", False)


class _NameParamTool(BaseTool):
    """A tool whose own argument is literally called ``name``."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="thing_reader",
            description="reads a thing by name",
            parameters=[ToolParameter(name="name", type="string")],
        )

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(content=f"read:{kwargs.get('name')}")


@pytest.mark.asyncio
async def test_execute_passes_name_argument_without_collision() -> None:
    reg = ToolRegistry()
    reg.register(_NameParamTool())
    # Tool name positional, tool's own ``name`` arg as keyword — must not
    # raise "got multiple values for argument 'name'".
    result = await reg.execute("thing_reader", name="widget")
    assert result.content == "read:widget"


@pytest.mark.asyncio
async def test_execute_forwards_event_sink_alongside_name() -> None:
    reg = ToolRegistry()
    reg.register(_NameParamTool())
    # Mirrors the dispatcher, which always passes event_sink plus tool args.
    result = await reg.execute("thing_reader", event_sink=None, name="gadget")
    assert result.content == "read:gadget"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "record",
    [
        {"id": "usr_one", "role": "admin", "disabled": True},
        {"id": "usr_one", "role": "user", "disabled": False},
    ],
)
async def test_tool_execution_revalidates_account_before_side_effect(
    monkeypatch,
    tmp_path: Path,
    record: dict[str, object],
) -> None:
    from deeptutor.services import auth as auth_service

    calls: list[dict[str, object]] = []

    class SideEffectTool(_NameParamTool):
        async def execute(self, **kwargs: object) -> ToolResult:
            calls.append(kwargs)
            return ToolResult(content="unexpected")

    registry = ToolRegistry()
    registry.register(SideEffectTool())
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "_load_users", lambda: {"one": record})
    token = set_current_user(
        CurrentUser(
            id="usr_one",
            username="one",
            role="admin",
            scope=UserScope(kind="user", user_id="usr_one", root=tmp_path),
        )
    )
    try:
        with pytest.raises(PermissionError, match="authorization changed"):
            await registry.execute("thing_reader", name="blocked")
        assert calls == []
    finally:
        reset_current_user(token)
