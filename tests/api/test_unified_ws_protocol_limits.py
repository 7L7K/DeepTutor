from __future__ import annotations

import asyncio
import json

import pytest

from deeptutor.api.routers.unified_ws import (
    _MAX_UNIFIED_ATTACHMENT_BASE64_CHARS,
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
    with pytest.raises(ValueError, match="history_references"):
        _validate_unified_ws_message(
            {
                "type": "start_turn",
                "content": "hello",
                "history_references": ["session"] * 101,
            }
        )


@pytest.mark.parametrize(
    "nested_payload",
    [
        {"attachments": [{"type": "file", "padding": "x"}]},
        {"notebook_references": [{"notebook_id": "n1", "record_ids": ["r1"], "padding": "x"}]},
        {"book_references": [{"book_id": "b1", "page_ids": ["p1"], "padding": "x"}]},
        {"llm_selection": {"profile_id": "p1", "model_id": "m1", "padding": "x"}},
    ],
)
def test_start_turn_rejects_unknown_nested_protocol_fields(
    nested_payload: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="unsupported fields"):
        _validate_unified_ws_message({"type": "start_turn", "content": "hello", **nested_payload})


def test_nested_attachment_padding_is_invalid_after_json_parse() -> None:
    raw = json.dumps(
        {
            "type": "start_turn",
            "content": "hello",
            "attachments": [{"type": "file", "padding": "x" * 1_000_000}],
        }
    )
    with pytest.raises(ValueError, match="Invalid message"):
        _decode_bounded_unified_ws_text(raw)


@pytest.mark.parametrize("message_type", ["start_turn", "message"])
def test_duplicate_top_level_fields_cannot_hide_padding(message_type: str) -> None:
    raw = f'{{"type":"{message_type}","content":"' + ("x" * 1_000_000) + '","content":"ok"}'
    with pytest.raises(ValueError, match="Invalid message"):
        _decode_bounded_unified_ws_text(raw)


def test_duplicate_nested_answer_fields_cannot_hide_padding() -> None:
    raw = (
        '{"type":"submit_user_reply","turn_id":"turn-1",'
        '"answers":[{"questionId":"q1","text":"' + ("x" * 1_000_000) + '","text":"ok"}]}'
    )
    with pytest.raises(ValueError, match="Invalid message"):
        _decode_bounded_unified_ws_text(raw)


def test_preparser_rejects_escaped_duplicate_and_unknown_nested_keys_before_json_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.api.routers.unified_ws as unified_ws

    def _json_loads_must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("json.loads must not run for a structurally invalid frame")

    monkeypatch.setattr(unified_ws.json, "loads", _json_loads_must_not_run)
    with pytest.raises(ValueError, match="Invalid message"):
        _decode_bounded_unified_ws_text(
            '{"type":"start_turn","content":"ok","c\\u006fntent":"duplicate"}'
        )
    with pytest.raises(ValueError, match="Invalid message"):
        _decode_bounded_unified_ws_text(
            '{"type":"start_turn","content":"ok","attachments":[{"type":"file","padding":"x"}]}'
        )


def test_preparser_rejects_depth_token_and_scalar_budgets_before_json_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.api.routers.unified_ws as unified_ws

    def _json_loads_must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("json.loads must not run after a pre-parser budget failure")

    monkeypatch.setattr(unified_ws.json, "loads", _json_loads_must_not_run)

    monkeypatch.setattr(unified_ws, "_MAX_UNIFIED_JSON_DEPTH", 3)
    with pytest.raises(ValueError, match="Invalid message"):
        _decode_bounded_unified_ws_text(
            '{"type":"start_turn","content":"ok","config":{"a":{"b":[]}}}'
        )

    monkeypatch.setattr(unified_ws, "_MAX_UNIFIED_JSON_DEPTH", 32)
    monkeypatch.setattr(unified_ws, "_MAX_UNIFIED_JSON_TOKENS", 6)
    with pytest.raises(ValueError, match="Invalid message"):
        _decode_bounded_unified_ws_text(
            '{"type":"start_turn","content":"ok","tools":["a","b","c"]}'
        )

    monkeypatch.setattr(unified_ws, "_MAX_UNIFIED_JSON_TOKENS", 50_000)
    monkeypatch.setattr(unified_ws, "_MAX_UNIFIED_CONTENT_CHARS", 4)
    with pytest.raises(ValueError, match="Invalid message"):
        _decode_bounded_unified_ws_text('{"type":"start_turn","content":"12345"}')


def test_preparser_applies_order_independent_reply_and_integer_types_before_json_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.api.routers.unified_ws as unified_ws

    def _json_loads_must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("known protocol scalar failures must precede json.loads")

    monkeypatch.setattr(unified_ws.json, "loads", _json_loads_must_not_run)
    with pytest.raises(ValueError, match="Invalid message"):
        _decode_bounded_unified_ws_text(
            '{"content":"' + ("x" * 12_001) + '","type":"user_input","turn_id":"t1"}'
        )

    invalid_integer_frames = [
        '{"type":"subscribe_turn","turn_id":"t1","after_seq":"' + ("1" * 1_000) + '"}',
        '{"type":"start_turn","content":"ok","parent_message_id":"1"}',
        '{"type":"start_turn","content":"ok","question_notebook_references":["1"]}',
    ]
    for raw in invalid_integer_frames:
        with pytest.raises(ValueError, match="Invalid message"):
            _decode_bounded_unified_ws_text(raw)


def test_preparser_preserves_type_order_and_exempts_only_attachment_base64(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.api.routers.unified_ws as unified_ws

    monkeypatch.setattr(unified_ws, "_MAX_UNIFIED_ORDINARY_MESSAGE_BYTES", 256)
    raw = (
        '{"content":"ok","attachments":[{"type":"file","base64":"'
        + ("a" * 1_024)
        + '"}],"type":"start_turn"}'
    )
    message = _decode_bounded_unified_ws_text(raw)
    assert list(message) == ["content", "attachments", "type"]

    escaped_raw = (
        '{"type":"start_turn","content":"ok",'
        '"attachments":[{"type":"file","base64":"' + ("\\u0061" * 200) + '"}]}'
    )
    escaped_message = _decode_bounded_unified_ws_text(escaped_raw)
    assert escaped_message["attachments"][0]["base64"] == "a" * 200

    with pytest.raises(ValueError, match="Invalid message"):
        _decode_bounded_unified_ws_text(
            '{"type":"start_turn","content":"' + ("x" * 300) + '","attachments":[]}'
        )
    with pytest.raises(ValueError, match="Invalid message"):
        _decode_bounded_unified_ws_text(
            '{"type":"start_turn","content":"ok","config":{"base64":"' + ("a" * 300) + '"}}'
        )
    with pytest.raises(ValueError, match="Invalid message"):
        _decode_bounded_unified_ws_text(
            '{"type":"start_turn","content":"ok",'
            '"attachments":[{"type":"file","base64":"' + ("=" * 300) + '"}]}'
        )


def test_config_and_overrides_size_checks_do_not_serialize_a_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.api.routers.unified_ws as unified_ws

    def _json_dumps_must_not_run(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("config size checks must not serialize a JSON copy")

    monkeypatch.setattr(unified_ws.json, "dumps", _json_dumps_must_not_run)
    config_message = {
        "type": "start_turn",
        "content": "hello",
        "config": {"confirmed_outline": [{"title": "Scope", "overview": "Intro"}]},
    }
    assert _validate_unified_ws_message(config_message) is config_message
    override_message = {
        "type": "regenerate",
        "session_id": "session-1",
        "overrides": {"config": {"mode": "comparison"}, "language": "en"},
    }
    assert _validate_unified_ws_message(override_message) is override_message

    with pytest.raises(ValueError, match="config is too large"):
        _validate_unified_ws_message(
            {
                "type": "start_turn",
                "content": "hello",
                "config": {"prompt": "x" * _MAX_UNIFIED_CONFIG_BYTES},
            }
        )


def test_start_turn_accepts_supported_nested_protocol_shapes() -> None:
    message = {
        "type": "start_turn",
        "content": "hello",
        "attachments": [
            {
                "type": "file",
                "url": "/api/attachments/s1/a1/notes.txt",
                "base64": "aGVsbG8=",
                "filename": "notes.txt",
                "mime_type": "text/plain",
            }
        ],
        "notebook_references": [{"notebook_id": "n1", "record_ids": ["r1"]}],
        "history_references": ["session-1"],
        "question_notebook_references": [1],
        "book_references": [{"book_id": "b1", "page_ids": ["p1"]}],
        "llm_selection": {"profile_id": "profile-1", "model_id": "model-1"},
        # Capability config is intentionally extensible; only its aggregate
        # serialized size is constrained at this transport boundary.
        "config": {"confirmed_outline": [{"title": "Scope", "overview": "Intro"}]},
    }

    assert _validate_unified_ws_message(message) is message


def test_attachment_base64_is_bounded_to_runtime_policy_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.api.routers.unified_ws as unified_ws

    assert _MAX_UNIFIED_ATTACHMENT_BASE64_CHARS < _MAX_UNIFIED_WS_MESSAGE_BYTES
    monkeypatch.setattr(unified_ws, "_MAX_UNIFIED_ATTACHMENT_BASE64_CHARS", 8)
    with pytest.raises(ValueError, match="attachment base64"):
        _validate_unified_ws_message(
            {
                "type": "start_turn",
                "content": "hello",
                "attachments": [{"type": "file", "base64": "a" * 9}],
            }
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


def test_submit_user_reply_rejects_unknown_answer_fields_and_accepts_legacy_id() -> None:
    with pytest.raises(ValueError, match="unsupported fields"):
        _validate_unified_ws_message(
            {
                "type": "submit_user_reply",
                "turn_id": "turn-1",
                "answers": [{"questionId": "q1", "text": "ok", "padding": "x"}],
            }
        )

    message = {
        "type": "submit_user_reply",
        "turn_id": "turn-1",
        "answers": [{"id": "legacy-q1", "text": "ok"}],
    }
    assert _validate_unified_ws_message(message) is message


@pytest.mark.parametrize(
    ("message_type", "id_field", "field"),
    [("subscribe_turn", "turn_id", "after_seq"), ("resume_from", "turn_id", "seq")],
)
def test_replay_offsets_are_bounded_integers(message_type: str, id_field: str, field: str) -> None:
    with pytest.raises(ValueError, match=field):
        _validate_unified_ws_message({"type": message_type, id_field: "t1", field: "1"})
    with pytest.raises(ValueError, match=field):
        _validate_unified_ws_message({"type": message_type, id_field: "t1", field: 10_000_001})


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


def test_ping_rejects_padding_and_unknown_message_types_reject_unknown_fields() -> None:
    with pytest.raises(ValueError, match="unsupported fields"):
        _validate_unified_ws_message({"type": "ping", "padding": "x" * 1_000_000})
    with pytest.raises(ValueError, match="unsupported fields"):
        _validate_unified_ws_message({"type": "unrecognized", "padding": "x"})


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
