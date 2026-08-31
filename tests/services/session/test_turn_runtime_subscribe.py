from __future__ import annotations

import asyncio

import pytest

from deeptutor.services.sandbox.quota import UserExecQuota
from deeptutor.services.session import turn_runtime as turn_runtime_module
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager, _TurnExecution


@pytest.mark.asyncio
async def test_subscribe_turn_does_not_synthesize_done_for_running_turn(tmp_path) -> None:
    """A paused/replaced subscription must not make the UI think the turn ended."""

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")
    execution = _TurnExecution(
        turn_id=turn["id"],
        session_id=session["id"],
        capability="chat",
        payload={},
    )
    runtime._executions[turn["id"]] = execution

    events: list[dict] = []

    async def _collect() -> None:
        async for event in runtime.subscribe_turn(turn["id"], after_seq=0):
            events.append(event)

    task = asyncio.create_task(_collect())
    for _ in range(200):
        if execution.subscribers:
            break
        await asyncio.sleep(0.01)

    assert execution.subscribers
    await execution.subscribers[0].queue.put(None)
    await asyncio.wait_for(task, timeout=1)

    assert events == []
    persisted = await store.get_turn(turn["id"])
    assert persisted is not None
    assert persisted["status"] == "running"


@pytest.mark.asyncio
async def test_subscribe_turn_marks_orphan_running_turn_failed(tmp_path) -> None:
    """A DB-running turn with no in-process execution is stale after restart."""

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")

    events: list[dict] = []
    async for event in runtime.subscribe_turn(turn["id"], after_seq=0):
        events.append(event)

    persisted = await store.get_turn(turn["id"])
    assert persisted is not None
    assert persisted["status"] == "failed"
    assert "restart" in persisted["error"].lower()
    assert [event["type"] for event in events] == ["error", "done"]
    assert events[-1]["metadata"]["status"] == "failed"


@pytest.mark.asyncio
async def test_start_turn_clears_orphan_running_turn_before_create(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A stale active turn should not block the next user message after restart."""

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    stale = await store.create_turn(session["id"], capability="chat")

    async def _noop_run_turn(_execution):
        return None

    monkeypatch.setattr(runtime, "_run_turn", _noop_run_turn)

    _, new_turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "session_id": session["id"],
            "capability": "chat",
            "content": "hello",
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {},
        }
    )

    assert new_turn["id"] != stale["id"]
    persisted = await store.get_turn(stale["id"])
    assert persisted is not None
    assert persisted["status"] == "failed"


@pytest.mark.asyncio
async def test_start_turn_admission_blocks_fresh_sessions_until_first_finishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A learner cannot bypass the provider bulkhead by changing session IDs."""

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    gate = asyncio.Event()

    async def _hold_run(_execution):
        await gate.wait()

    monkeypatch.setattr(runtime, "_run_turn", _hold_run)
    monkeypatch.setattr(
        turn_runtime_module,
        "_TURN_REQUEST_QUOTA",
        UserExecQuota(max_concurrent=1, max_per_minute=10),
    )
    payload = {
        "type": "start_turn",
        "session_id": None,
        "capability": "chat",
        "content": "hello",
        "tools": [],
        "knowledge_bases": [],
        "attachments": [],
        "language": "en",
        "config": {},
    }

    _session, first_turn = await runtime.start_turn(payload)
    with pytest.raises(RuntimeError, match="capacity"):
        await runtime.start_turn({**payload, "session_id": None})

    gate.set()
    first_task = runtime._executions[first_turn["id"]].task
    assert first_task is not None
    await asyncio.wait_for(first_task, timeout=1)
    await asyncio.sleep(0)
