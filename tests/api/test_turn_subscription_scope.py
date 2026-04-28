from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


@pytest.mark.asyncio
async def test_owner_tester_can_subscribe_to_turn_events(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.create_session(tester_id="tester-owner")
    turn = await store.create_turn(session["id"], capability="chat")
    execution = SimpleNamespace(
        turn_id=turn["id"],
        session_id=session["id"],
        capability="chat",
        subscribers=[],
    )

    await runtime._persist_and_publish(
        execution=execution,
        event=StreamEvent(
            type=StreamEventType.SESSION,
            source="turn_runtime",
            metadata={"session_id": session["id"], "turn_id": turn["id"]},
        ),
    )
    await runtime._persist_and_publish(
        execution=execution,
        event=StreamEvent(
            type=StreamEventType.DONE,
            source="chat",
            metadata={"status": "completed"},
        ),
    )
    await store.update_turn_status(turn["id"], "completed")

    owner_events = [
        event
        async for event in runtime.subscribe_turn(
            turn["id"],
            after_seq=0,
            tester_id="tester-owner",
        )
    ]
    other_tester_events = [
        event
        async for event in runtime.subscribe_turn(
            turn["id"],
            after_seq=0,
            tester_id="tester-other",
        )
    ]

    assert [event["type"] for event in owner_events] == ["session", "done"]
    assert owner_events[0]["session_id"] == session["id"]
    assert owner_events[0]["turn_id"] == turn["id"]
    assert other_tester_events == []
