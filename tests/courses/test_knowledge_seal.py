from __future__ import annotations

from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import knowledge
from deeptutor.multi_user import knowledge_access
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser
from deeptutor.multi_user.paths import UserScope


@pytest.mark.asyncio
async def test_generic_config_routes_hide_managed_course_indexes() -> None:
    name = "course_crs_one_src_one"
    with pytest.raises(HTTPException) as read_denied:
        await knowledge.get_kb_config(name)
    with pytest.raises(HTTPException) as write_denied:
        await knowledge.update_kb_config(name, {"search_mode": "hybrid"})
    assert read_denied.value.status_code == 404
    assert write_denied.value.status_code == 404


@pytest.mark.asyncio
async def test_generic_config_sync_skips_managed_course_indexes(
    monkeypatch, tmp_path
) -> None:
    (tmp_path / "general_kb").mkdir()
    (tmp_path / "course_crs_one_src_one").mkdir()
    seen: list[str] = []
    service = SimpleNamespace(
        sync_from_metadata=lambda name, _base: seen.append(name),
    )
    monkeypatch.setattr(knowledge, "_current_kb_base_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "deeptutor.services.config.get_kb_config_service", lambda: service
    )

    await knowledge.sync_configs_from_metadata()

    assert seen == ["general_kb"]


@pytest.mark.asyncio
async def test_generic_connect_cannot_preclaim_managed_course_name() -> None:
    with pytest.raises(HTTPException) as denied:
        await knowledge.connect_obsidian_vault(
            knowledge.ConnectObsidianRequest(
                name="course_crs_one_src_one",
                vault_path="/does/not/matter",
            )
        )
    assert denied.value.status_code == 400
    assert denied.value.detail == "Reserved knowledge base name"


@pytest.mark.asyncio
async def test_generic_task_stream_never_exposes_course_operation_namespace() -> None:
    with pytest.raises(HTTPException) as denied:
        await knowledge.stream_task_logs("course_source_20260720_deadbeef")
    assert denied.value.status_code == 404


def test_default_alias_cannot_resolve_managed_course_index(monkeypatch, tmp_path) -> None:
    name = "course_crs_one_src_one"
    manager = SimpleNamespace(
        list_knowledge_bases=lambda: [name],
        get_default=lambda: name,
    )
    monkeypatch.setattr(knowledge_access, "current_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_access, "current_kb_base_dir", lambda: tmp_path)
    user = CurrentUser(
        id="usr_one",
        username="one",
        role="user",
        scope=UserScope(kind="user", user_id="usr_one", root=tmp_path),
    )
    token = set_current_user(user)
    try:
        with pytest.raises(HTTPException) as denied:
            knowledge_access.resolve_kb("default")
        assert denied.value.status_code == 404
    finally:
        reset_current_user(token)


@pytest.mark.asyncio
async def test_default_endpoint_hides_managed_course_index(monkeypatch) -> None:
    monkeypatch.setattr(
        knowledge,
        "get_kb_manager",
        lambda: SimpleNamespace(get_default=lambda: "course_crs_one_src_one"),
    )
    assert await knowledge.get_default_kb() == {"default_kb": None}


@pytest.mark.asyncio
async def test_generic_progress_websocket_rejects_managed_course_index(
    monkeypatch,
) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.accepted = False
            self.closed_code = None

        async def accept(self) -> None:
            self.accepted = True

        async def close(self, code: int = 1000) -> None:
            self.closed_code = code

    async def allow_auth(_websocket):
        return None

    monkeypatch.setattr("deeptutor.api.routers.auth.ws_require_auth", allow_auth)
    websocket = FakeWebSocket()

    await knowledge.websocket_progress(websocket, "course_crs_one_src_one")

    assert websocket.accepted is False
    assert websocket.closed_code == 4404
