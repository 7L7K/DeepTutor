from __future__ import annotations

import asyncio
import json

import pytest

from deeptutor.api.routers.unified_ws import (
    _MAX_UNIFIED_CONFIG_BYTES,
    _MAX_UNIFIED_CONTENT_CHARS,
    _MAX_UNIFIED_INVALID_MESSAGES,
    _MAX_UNIFIED_WS_MESSAGE_BYTES,
    _decode_bounded_unified_ws_text,
    _fits_utf8_byte_limit,
    _receive_bounded_unified_ws_message,
    _UnifiedWsFrameTooLarge,
    _validate_unified_ws_message,
)


def test_start_turn_rejects_oversized_content_before_runtime_dispatch() -> None:
    with pytest.raises(ValueError, match="content"):
        _validate_unified_ws_message(
            {"type": "start_turn", "content": "x" * (_MAX_UNIFIED_CONTENT_CHARS + 1)}
        )


def test_start_turn_bounds_nested_config_and_references() -> None:
    with pytest.raises(ValueError, match="config"):
        _validate_unified_ws_message(
            {
                "type": "start_turn",
                "content": "hello",
                "config": {"prompt": "x" * _MAX_UNIFIED_CONFIG_BYTES},
            }
        )
    with pytest.raises(ValueError, match="attachments"):
        _validate_unified_ws_message(
            {"type": "start_turn", "content": "hello", "attachments": [{}] * 11}
        )


def test_submit_user_reply_bounds_each_answer() -> None:
    with pytest.raises(ValueError, match="answer text"):
        _validate_unified_ws_message(
            {
                "type": "submit_user_reply",
                "turn_id": "turn-1",
                "answers": [{"questionId": "q1", "text": "x" * 12_001}],
            }
        )


@pytest.mark.parametrize("field", ["after_seq", "seq"])
def test_replay_offsets_are_bounded_integers(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        _validate_unified_ws_message({"type": "subscribe_turn", "turn_id": "t1", field: "1"})
    with pytest.raises(ValueError, match=field):
        _validate_unified_ws_message({"type": "subscribe_turn", "turn_id": "t1", field: 10_000_001})


def test_transport_ceiling_is_fixed_and_independent_of_attachment_setting() -> None:
    assert _MAX_UNIFIED_WS_MESSAGE_BYTES == 64 * 1024 * 1024
    # The helper itself accepts a normal attachment envelope; the runtime's
    # attachment validator remains the authority for exact file bytes/types.
    _validate_unified_ws_message(
        {
            "type": "start_turn",
            "content": "hello",
            "attachments": [
                {
                    "type": "file",
                    "filename": "notes.txt",
                    "mime_type": "text/plain",
                    "base64": "aGVsbG8=",
                }
            ],
        }
    )
    assert len(json.dumps({"type": "ping"})) < _MAX_UNIFIED_WS_MESSAGE_BYTES


def test_transport_limit_uses_utf8_bytes_without_encoding_a_duplicate_frame() -> None:
    assert _fits_utf8_byte_limit("abcd", 4) is True
    assert _fits_utf8_byte_limit("éé", 3) is False


def test_oversized_frame_is_rejected_before_json_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    import deeptutor.api.routers.unified_ws as unified_ws

    monkeypatch.setattr(unified_ws, "_MAX_UNIFIED_WS_MESSAGE_BYTES", 4)

    def _json_loads_must_not_run(_value: str) -> object:
        raise AssertionError("JSON parsing must not run for an oversized frame")

    monkeypatch.setattr(unified_ws.json, "loads", _json_loads_must_not_run)
    with pytest.raises(_UnifiedWsFrameTooLarge):
        _decode_bounded_unified_ws_text("12345")


def test_non_text_frame_is_invalid_before_json_parser() -> None:
    class FakeWebSocket:
        async def receive(self) -> dict:
            return {"type": "websocket.receive", "bytes": b"{}"}

    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )

    token = set_current_user(user_from_token_payload(None))
    try:
        with pytest.raises(ValueError, match="text"):
            asyncio.run(_receive_bounded_unified_ws_message(FakeWebSocket(), timeout_s=1))
    finally:
        reset_current_user(token)


def test_idle_unified_socket_cannot_hold_all_receive_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    import deeptutor.api.routers.unified_ws as unified_ws
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )
    from deeptutor.services.sandbox.quota import QuotaExceeded, UserExecQuota

    monkeypatch.setattr(
        unified_ws,
        "_UNIFIED_WS_RECEIVE_USER_QUOTA",
        UserExecQuota(max_concurrent=1, max_per_minute=10),
    )
    monkeypatch.setattr(
        unified_ws,
        "_UNIFIED_WS_RECEIVE_GLOBAL_QUOTA",
        UserExecQuota(max_concurrent=2, max_per_minute=10),
    )

    class IdleWebSocket:
        def __init__(self) -> None:
            self.receive_started = asyncio.Event()
            self.release_receive = asyncio.Event()

        async def receive(self) -> dict:
            self.receive_started.set()
            await self.release_receive.wait()
            return {"type": "websocket.receive", "text": '{"type":"ping"}'}

    async def _exercise() -> None:
        token = set_current_user(user_from_token_payload(None))
        first = IdleWebSocket()
        try:
            first_task = asyncio.create_task(
                _receive_bounded_unified_ws_message(first, timeout_s=1)
            )
            await asyncio.wait_for(first.receive_started.wait(), timeout=1)
            with pytest.raises(QuotaExceeded):
                await _receive_bounded_unified_ws_message(IdleWebSocket(), timeout_s=1)
            first.release_receive.set()
            assert await first_task == {"type": "ping"}
        finally:
            reset_current_user(token)

    asyncio.run(_exercise())


def test_unified_first_frame_has_a_bounded_timeout() -> None:
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )

    class IdleWebSocket:
        async def receive(self) -> dict:
            await asyncio.sleep(1)
            return {"type": "websocket.receive", "text": '{"type":"ping"}'}

    token = set_current_user(user_from_token_payload(None))
    try:
        with pytest.raises(TimeoutError):
            asyncio.run(_receive_bounded_unified_ws_message(IdleWebSocket(), timeout_s=0.01))
    finally:
        reset_current_user(token)


def test_invalid_protocol_frames_close_after_one_generic_error() -> None:
    assert _MAX_UNIFIED_INVALID_MESSAGES == 1
