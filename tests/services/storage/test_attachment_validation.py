from __future__ import annotations

import base64

import pytest

from deeptutor.services.config.runtime_settings import ChatAttachmentLimits
from deeptutor.services.storage.attachment_validation import (
    AttachmentValidationError,
    validate_chat_attachments,
    validate_notebook_answer_images,
)


def _limits() -> ChatAttachmentLimits:
    return ChatAttachmentLimits(
        max_file_bytes=4,
        max_total_bytes=6,
        max_chars_per_doc=100,
        max_chars_total=100,
    )


def test_chat_validation_rejects_an_oversized_image_before_persistence(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.storage.attachment_validation.get_chat_attachment_limits", _limits
    )

    with pytest.raises(AttachmentValidationError, match="per-file"):
        validate_chat_attachments(
            [
                {
                    "id": "image1",
                    "type": "image",
                    "filename": "answer.png",
                    "mime_type": "image/png",
                    "base64": base64.b64encode(b"12345").decode(),
                }
            ]
        )


def test_chat_validation_bounds_encoded_input_before_decode(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.storage.attachment_validation.get_chat_attachment_limits", _limits
    )

    with pytest.raises(AttachmentValidationError, match="per-file"):
        validate_chat_attachments(
            [
                {
                    "id": "image1",
                    "type": "image",
                    "filename": "answer.png",
                    "mime_type": "image/png",
                    "base64": "A" * 12,
                }
            ]
        )


def test_chat_validation_rejects_non_document_non_image_bypass(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.storage.attachment_validation.get_chat_attachment_limits", _limits
    )

    with pytest.raises(AttachmentValidationError, match="unsupported file type"):
        validate_chat_attachments(
            [
                {
                    "id": "binary1",
                    "type": "file",
                    "filename": "archive.zip",
                    "mime_type": "application/zip",
                    "base64": base64.b64encode(b"1234").decode(),
                }
            ]
        )


def test_notebook_validation_requires_raw_strict_base64(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.storage.attachment_validation.get_chat_attachment_limits", _limits
    )

    with pytest.raises(AttachmentValidationError, match="invalid base64"):
        validate_notebook_answer_images(
            [{"filename": "answer.png", "mime_type": "image/png", "base64": "!!!!"}]
        )


def test_notebook_validation_rejects_non_object_entries(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.storage.attachment_validation.get_chat_attachment_limits", _limits
    )

    with pytest.raises(AttachmentValidationError, match="answer image 1 is invalid"):
        validate_notebook_answer_images(["not-an-image-record"])


def test_notebook_validation_rejects_spoofed_image_bytes(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.storage.attachment_validation.get_chat_attachment_limits", _limits
    )

    with pytest.raises(AttachmentValidationError, match="do not match"):
        validate_notebook_answer_images(
            [
                {
                    "filename": "answer.png",
                    "mime_type": "image/png",
                    "base64": base64.b64encode(b"bad!").decode(),
                }
            ]
        )
