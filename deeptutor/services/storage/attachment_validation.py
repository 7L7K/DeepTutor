"""Fail-closed validation shared by attachment persistence entry points."""

from __future__ import annotations

import base64
from pathlib import PurePosixPath
import re
from typing import Any

from deeptutor.services.config.runtime_settings import get_chat_attachment_limits
from deeptutor.utils.document_extractor import is_document_extension

MAX_CHAT_ATTACHMENT_COUNT = 10
MAX_NOTEBOOK_ANSWER_IMAGE_COUNT = 5

# SVG is deliberately a document, not an image: it is text extracted for the
# model and must never be served as an executable image document.
_IMAGE_MIME_BY_EXTENSION = {
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}
_ATTACHMENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class AttachmentValidationError(ValueError):
    """Raised before an untrusted attachment can reach disk or extraction."""


def validate_attachment_id(value: object, *, label: str) -> str:
    attachment_id = str(value or "").strip()
    if not _ATTACHMENT_ID_RE.fullmatch(attachment_id):
        raise AttachmentValidationError(f"{label} has an invalid attachment id")
    return attachment_id


def decode_base64(value: object, *, label: str) -> bytes:
    """Decode one raw (not data-URL) base64 value without permissive aliases."""
    if not isinstance(value, str) or not value:
        raise AttachmentValidationError(f"{label} is missing base64 data")
    if value.startswith("data:"):
        raise AttachmentValidationError(f"{label} must not use a data URL")
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:
        raise AttachmentValidationError(f"{label} has invalid base64 data") from exc


def _reject_oversized_base64(value: object, *, label: str, max_bytes: int) -> None:
    """Bound encoded input before allocating its decoded byte buffer."""
    if not isinstance(value, str):
        return
    # Strict base64 uses four characters per three bytes. The final quantum
    # may include padding, so this is a safe upper bound rather than an exact
    # decoded-size calculation.
    max_encoded_chars = ((max_bytes + 2) // 3) * 4
    if len(value) > max_encoded_chars:
        raise AttachmentValidationError(f"{label} exceeds the per-file size limit")


def validate_chat_attachments(items: object) -> list[dict[str, Any]]:
    """Return persistence-ready chat attachments after batch-wide validation.

    Every uploaded byte is checked before storage.  Existing internal URLs
    are intentionally not accepted on this write path: clients submit new
    files here, while previously persisted records are read from the session.
    """
    if not isinstance(items, list):
        raise AttachmentValidationError("attachments must be a list")
    if len(items) > MAX_CHAT_ATTACHMENT_COUNT:
        raise AttachmentValidationError(
            f"too many attachments (maximum {MAX_CHAT_ATTACHMENT_COUNT})"
        )

    limits = get_chat_attachment_limits()
    total = 0
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise AttachmentValidationError(f"attachment {index} is invalid")
        if item.get("url"):
            raise AttachmentValidationError("attachment URLs cannot be submitted")
        filename = str(item.get("filename") or "").strip()
        declared_type = str(item.get("type") or "file").strip().lower()
        mime_type = str(item.get("mime_type") or "").strip().lower()
        _reject_oversized_base64(
            item.get("base64"), label=f"attachment {index}", max_bytes=limits.max_file_bytes
        )
        raw = decode_base64(item.get("base64"), label=f"attachment {index}")
        attachment_id = validate_attachment_id(item.get("id"), label=f"attachment {index}")
        _check_size(
            raw, total, limits.max_file_bytes, limits.max_total_bytes, f"attachment {index}"
        )
        _validate_type(
            filename=filename,
            declared_type=declared_type,
            mime_type=mime_type,
            data=raw,
            images_only=False,
            label=f"attachment {index}",
        )
        total += len(raw)
        validated.append(
            {
                **item,
                "filename": filename,
                "type": declared_type,
                "mime_type": mime_type,
                "id": attachment_id,
                "base64": item["base64"],
                "_raw_bytes": raw,
            }
        )
    return validated


def validate_notebook_answer_images(items: object) -> list[dict[str, Any]]:
    """Validate only new notebook image bytes before they are persisted."""
    if not isinstance(items, list):
        raise AttachmentValidationError("answer images must be a list")
    if len(items) > MAX_NOTEBOOK_ANSWER_IMAGE_COUNT:
        raise AttachmentValidationError(
            f"too many answer images (maximum {MAX_NOTEBOOK_ANSWER_IMAGE_COUNT})"
        )

    limits = get_chat_attachment_limits()
    total = 0
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise AttachmentValidationError(f"answer image {index} is invalid")
        filename = str(item.get("filename") or "").strip()
        mime_type = str(item.get("mime_type") or "").strip().lower()
        _reject_oversized_base64(
            item.get("base64"), label=f"answer image {index}", max_bytes=limits.max_file_bytes
        )
        raw = decode_base64(item.get("base64"), label=f"answer image {index}")
        _check_size(
            raw, total, limits.max_file_bytes, limits.max_total_bytes, f"answer image {index}"
        )
        _validate_type(
            filename=filename,
            declared_type="image",
            mime_type=mime_type,
            data=raw,
            images_only=True,
            label=f"answer image {index}",
        )
        total += len(raw)
        validated.append({**item, "filename": filename, "mime_type": mime_type, "_raw_bytes": raw})
    return validated


def _check_size(raw: bytes, total: int, max_file: int, max_total: int, label: str) -> None:
    if not raw:
        raise AttachmentValidationError(f"{label} is empty")
    if len(raw) > max_file:
        raise AttachmentValidationError(f"{label} exceeds the per-file size limit")
    if total + len(raw) > max_total:
        raise AttachmentValidationError("attachment batch exceeds the total size limit")


def _validate_type(
    *, filename: str, declared_type: str, mime_type: str, data: bytes, images_only: bool, label: str
) -> None:
    ext = PurePosixPath(filename).suffix.lower()
    if ext in _IMAGE_MIME_BY_EXTENSION:
        if declared_type != "image":
            raise AttachmentValidationError(f"{label} must be declared as an image")
        expected_mime = _IMAGE_MIME_BY_EXTENSION[ext]
        if mime_type and mime_type != expected_mime:
            raise AttachmentValidationError(f"{label} MIME type does not match its filename")
        if not _image_magic_matches(ext, data):
            raise AttachmentValidationError(f"{label} bytes do not match its image type")
        return
    if images_only:
        raise AttachmentValidationError(f"{label} has an unsupported image type")
    if not filename or not is_document_extension(filename):
        raise AttachmentValidationError(f"{label} has an unsupported file type")
    if declared_type not in {"file", "pdf"}:
        raise AttachmentValidationError(f"{label} must be declared as a file")
    if declared_type == "pdf" and ext != ".pdf":
        raise AttachmentValidationError(f"{label} PDF type does not match its filename")
    if ext == ".pdf" and not data.startswith(b"%PDF-"):
        raise AttachmentValidationError(f"{label} bytes do not match its PDF type")
    if ext in {".docx", ".xlsx", ".pptx"} and not data.startswith(b"PK\x03\x04"):
        raise AttachmentValidationError(f"{label} bytes do not match its Office type")


def _image_magic_matches(ext: str, data: bytes) -> bool:
    if ext == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if ext == ".gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if ext == ".webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    if ext == ".bmp":
        return data.startswith(b"BM")
    if ext in {".tif", ".tiff"}:
        return data.startswith((b"II*\x00", b"MM\x00*"))
    if ext in {".avif", ".heic", ".heif"}:
        return len(data) >= 12 and data[4:8] == b"ftyp" and ext[1:].encode() in data[8:24]
    return False
