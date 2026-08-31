"""Focused protocol-boundary tests for partner and Book WebSockets."""

from __future__ import annotations

import base64

import pytest

from deeptutor.api.routers import book as book_router
from deeptutor.api.routers import partners as partners_router


def test_partner_ws_accepts_legacy_message_form_with_valid_attachment(monkeypatch) -> None:
    monkeypatch.setattr(partners_router, "_partner_upload_caps", lambda: (8, 8))

    message = partners_router._validate_partner_ws_message(
        {
            "content": "Explain this",
            "attachments": [
                {
                    "type": "file",
                    "filename": "note.txt",
                    "mime_type": "text/plain",
                    "base64": base64.b64encode(b"hello").decode(),
                }
            ],
        }
    )

    assert message["content"] == "Explain this"
    assert message["attachments"][0].filename == "note.txt"


@pytest.mark.parametrize(
    "payload",
    [
        {"content": "hi", "ignored": "padding"},
        {"action": "unknown"},
        {"content": "hi", "attachments": [{"base64": "not base64!"}]},
    ],
)
def test_partner_ws_rejects_unknown_or_invalid_frames(monkeypatch, payload) -> None:
    monkeypatch.setattr(partners_router, "_partner_upload_caps", lambda: (8, 8))
    with pytest.raises(ValueError):
        partners_router._validate_partner_ws_message(payload)


def test_partner_attachment_materialization_rejects_permissive_base64(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(partners_router, "_partner_upload_caps", lambda: (8, 8))
    monkeypatch.setattr(partners_router, "get_partner_media_dir", lambda *_args: tmp_path)
    attachment = partners_router.ChatAttachmentRequest(
        filename="note.txt", base64="aGVsbG8=\nignored"
    )

    with pytest.raises(partners_router.HTTPException) as exc_info:
        partners_router._materialize_partner_attachments("ada", [attachment])

    assert exc_info.value.status_code == 422


def test_book_ws_create_schema_is_bounded_and_preserves_valid_contract() -> None:
    message = book_router._validate_book_ws_message(
        {
            "type": "create",
            "user_intent": "Learn the Fourier transform",
            "chat_selections": [{"session_id": "chat-1", "message_ids": [1, 2]}],
            "notebook_refs": [{"notebook_id": "notebook-1", "record_ids": [3]}],
            "knowledge_bases": ["calculus"],
            "question_categories": [1],
            "question_entries": [2],
            "language": "en",
        }
    )

    assert message["type"] == "create"
    assert message["chat_selections"][0]["session_id"] == "chat-1"


def test_book_ws_rejects_unsupported_and_extra_nested_schema() -> None:
    with pytest.raises(ValueError):
        book_router._validate_book_ws_message(
            {"type": "compile_page", "book_id": "b", "page_id": "p", "padding": "x"}
        )

    with pytest.raises(ValueError):
        book_router._validate_book_ws_message(
            {
                "type": "confirm_proposal",
                "book_id": "b",
                "proposal": {"title": "x", "unexpected": "x"},
            }
        )


def test_book_ws_rejects_oversized_dynamic_block_parameters() -> None:
    with pytest.raises(ValueError):
        book_router._validate_book_ws_message(
            {
                "type": "regenerate_block",
                "book_id": "b",
                "page_id": "p",
                "block_id": "block",
                "params_override": {"payload": "x" * (book_router._BOOK_WS_MAX_DYNAMIC_BYTES + 1)},
            }
        )
