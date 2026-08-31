from __future__ import annotations

import json

import pytest

from deeptutor.api.routers.unified_ws import (
    _MAX_UNIFIED_CONFIG_BYTES,
    _MAX_UNIFIED_CONTENT_CHARS,
    _MAX_UNIFIED_WS_MESSAGE_BYTES,
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
