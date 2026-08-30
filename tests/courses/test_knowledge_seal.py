from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import HTTPException
from starlette.websockets import WebSocketDisconnect
import pytest

from deeptutor.api.routers import knowledge
from deeptutor.api.utils.progress_broadcaster import (
    ProgressBroadcaster,
    progress_subscription_key,
)
from deeptutor.api.utils.task_id_manager import TaskIDManager
from deeptutor.api.utils.task_log_stream import KnowledgeTaskStreamManager
from deeptutor.multi_user import knowledge_access
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, KnowledgeResource
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


@pytest.mark.asyncio
async def test_foreign_or_unknown_task_stream_is_rejected_without_allocating_subscribers(
    tmp_path,
) -> None:
    """SSE task logs must never turn a caller-supplied ID into global state."""
    original_task_manager = TaskIDManager._instance
    original_stream_manager = KnowledgeTaskStreamManager._instance
    task_manager = TaskIDManager()
    stream_manager = KnowledgeTaskStreamManager()
    TaskIDManager._instance = task_manager
    KnowledgeTaskStreamManager._instance = stream_manager
    foreign_task = task_manager.generate_task_id("kb_upload", "owner-notes")
    task_manager.update_task_status(foreign_task, "running", owner_user_id="usr_owner")
    user = CurrentUser(
        id="usr_other",
        username="other",
        role="user",
        scope=UserScope(kind="user", user_id="usr_other", root=tmp_path),
    )
    token = set_current_user(user)
    try:
        for task_id in (foreign_task, "kb_upload_unknown_deadbeef"):
            with pytest.raises(HTTPException) as denied:
                await knowledge.stream_task_logs(task_id)
            assert denied.value.status_code == 404
            assert task_id not in stream_manager._buffers
            assert task_id not in stream_manager._subscribers
    finally:
        reset_current_user(token)
        TaskIDManager._instance = original_task_manager
        KnowledgeTaskStreamManager._instance = original_stream_manager


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


@pytest.mark.asyncio
async def test_progress_websocket_rejects_unresolved_kb_before_creating_room(monkeypatch) -> None:
    original_broadcaster = ProgressBroadcaster._instance
    broadcaster = ProgressBroadcaster()
    broadcaster._connections.clear()
    ProgressBroadcaster._instance = broadcaster

    class FakeWebSocket:
        def __init__(self) -> None:
            self.accepted = False
            self.closed_code: int | None = None

        async def accept(self) -> None:
            self.accepted = True

        async def close(self, code: int = 1000) -> None:
            self.closed_code = code

    async def allow_auth(_websocket):
        return None

    def deny_unknown(_name: str):
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    monkeypatch.setattr("deeptutor.api.routers.auth.ws_require_auth", allow_auth)
    monkeypatch.setattr(knowledge, "resolve_kb", deny_unknown)
    websocket = FakeWebSocket()
    try:
        await knowledge.websocket_progress(websocket, "missing")
        assert websocket.accepted is False
        assert websocket.closed_code == 4404
        assert broadcaster._connections == {}
    finally:
        ProgressBroadcaster._instance = original_broadcaster


@pytest.mark.asyncio
async def test_same_named_kbs_do_not_share_progress_websocket_room(monkeypatch, tmp_path) -> None:
    """The physical user workspace, not a display name, scopes progress fan-out."""
    original_broadcaster = ProgressBroadcaster._instance
    broadcaster = ProgressBroadcaster()
    broadcaster._connections.clear()
    ProgressBroadcaster._instance = broadcaster

    class FakeWebSocket:
        query_params = {"task_id": "active-task"}

        def __init__(self, user_id: str) -> None:
            self.user_id = user_id
            self.accepted = asyncio.Event()
            self.release = asyncio.Event()
            self.closed_code: int | None = None
            self.messages: list[dict] = []

        async def accept(self) -> None:
            self.accepted.set()

        async def close(self, code: int = 1000) -> None:
            self.closed_code = code

        async def send_json(self, value: dict) -> None:
            self.messages.append(value)

        async def receive_text(self) -> str:
            await self.release.wait()
            raise WebSocketDisconnect()

    users = {
        "usr_one": CurrentUser(
            id="usr_one",
            username="one",
            role="user",
            scope=UserScope(kind="user", user_id="usr_one", root=tmp_path / "users" / "usr_one"),
        ),
        "usr_two": CurrentUser(
            id="usr_two",
            username="two",
            role="user",
            scope=UserScope(kind="user", user_id="usr_two", root=tmp_path / "users" / "usr_two"),
        ),
    }

    async def authenticate(websocket: FakeWebSocket):
        return set_current_user(users[websocket.user_id])

    def resolve_for_current_user(name: str) -> KnowledgeResource:
        user = knowledge.get_current_user()
        base_dir = user.scope.root / "knowledge_bases"
        base_dir.mkdir(parents=True, exist_ok=True)
        return KnowledgeResource(
            id=f"user:kb:{name}",
            name=name,
            base_dir=base_dir,
            source="user",
        )

    monkeypatch.setattr("deeptutor.api.routers.auth.ws_require_auth", authenticate)
    monkeypatch.setattr(knowledge, "resolve_kb", resolve_for_current_user)
    first = FakeWebSocket("usr_one")
    second = FakeWebSocket("usr_two")
    first_task = asyncio.create_task(knowledge.websocket_progress(first, "notes"))
    second_task = asyncio.create_task(knowledge.websocket_progress(second, "notes"))
    try:
        await asyncio.wait_for(
            asyncio.gather(first.accepted.wait(), second.accepted.wait()), timeout=2
        )
        first_key = progress_subscription_key(
            "notes", users["usr_one"].scope.root / "knowledge_bases"
        )
        second_key = progress_subscription_key(
            "notes", users["usr_two"].scope.root / "knowledge_bases"
        )
        assert first_key != second_key

        await broadcaster.broadcast(first_key, {"task_id": "active-task", "percent": 50})
        await asyncio.sleep(0)

        assert first.messages == [
            {"type": "progress", "data": {"task_id": "active-task", "percent": 50}}
        ]
        assert second.messages == []
    finally:
        first.release.set()
        second.release.set()
        await asyncio.gather(first_task, second_task)
        broadcaster._connections.clear()
        ProgressBroadcaster._instance = original_broadcaster
