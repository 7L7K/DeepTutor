"""Small ASGI request-body limits for routes that accept binary data."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from deeptutor.services.config.runtime_settings import get_chat_attachment_limits
from deeptutor.services.sandbox.quota import QuotaExceeded, UserExecQuota

_NOTEBOOK_UPSERT_PATH = "/api/v1/question-notebook/entries/upsert"
_JSON_ENVELOPE_BYTES = 1024 * 1024
_NOTEBOOK_SUMMARY_PATHS = frozenset(
    {
        "/api/v1/notebook/add_record",
        "/api/v1/notebook/add_record_with_summary",
    }
)
_NOTEBOOK_SUMMARY_BODY_BYTES = 64 * 1024
_MASTERY_NOTEBOOK_PREFIX = "/api/v1/learning/progress/"
_MASTERY_NOTEBOOK_SUFFIX = "/generate-from-notebook"
_MASTERY_NOTEBOOK_BODY_BYTES = 96 * 1024
_MASTERY_STRUCTURE_SUFFIXES = ("/init-modules", "/import-from-book")
_MASTERY_STRUCTURE_BODY_BYTES = 1024 * 1024
_QUIZ_RESULTS_PREFIX = "/api/v1/sessions/"
_QUIZ_RESULTS_SUFFIX = "/quiz-results"
_QUIZ_RESULTS_BODY_BYTES = 1024 * 1024
_COURSE_SOURCE_PREFIX = "/api/v1/courses/"
_COURSE_SOURCE_SUFFIX = "/sources"
_COURSE_SOURCE_BODY_BYTES = 12 * 1024 * 1024
_PARTNER_CHAT_PREFIX = "/api/v1/partners/"
_PARTNER_CHAT_SUFFIXES = ("/chat", "/chat/execute-stream")
_PARTNER_CHAT_JSON_OVERHEAD_BYTES = 1024 * 1024
_VOICE_TTS_PATH = "/api/v1/voice/tts"
_VOICE_TTS_BODY_BYTES = 128 * 1024
_VOICE_STT_PATH = "/api/v1/voice/stt"
_VOICE_STT_BODY_BYTES = 26 * 1024 * 1024
_VOICE_STT_INTAKE_QUOTA = UserExecQuota(max_concurrent=4, max_per_minute=48)


class _RequestBodyTooLarge(Exception):
    pass


def notebook_upsert_body_limit() -> int:
    """Allow policy-sized base64 plus bounded JSON metadata overhead."""
    max_bytes = get_chat_attachment_limits().max_total_bytes
    return ((max_bytes + 2) // 3) * 4 + _JSON_ENVELOPE_BYTES


def course_source_body_limit() -> int:
    """Bound multipart intake before FastAPI creates UploadFile objects."""
    return _COURSE_SOURCE_BODY_BYTES


def partner_chat_body_limit() -> int:
    """Allow policy-sized base64 attachments plus a bounded JSON envelope."""
    max_bytes = get_chat_attachment_limits().max_total_bytes
    return ((max_bytes + 2) // 3) * 4 + _PARTNER_CHAT_JSON_OVERHEAD_BYTES


def _request_body_limit(scope: Scope) -> int | None:
    path = str(scope.get("path") or "")
    normalized_path = path[:-1] if path.endswith("/") and path != "/" else path
    method = str(scope.get("method") or "").upper()
    if method != "POST":
        return None
    if normalized_path == _VOICE_TTS_PATH:
        return _VOICE_TTS_BODY_BYTES
    if normalized_path == _VOICE_STT_PATH:
        return _VOICE_STT_BODY_BYTES
    if normalized_path == _NOTEBOOK_UPSERT_PATH:
        return notebook_upsert_body_limit()
    if normalized_path in _NOTEBOOK_SUMMARY_PATHS:
        return _NOTEBOOK_SUMMARY_BODY_BYTES
    if (
        normalized_path.startswith(_MASTERY_NOTEBOOK_PREFIX)
        and normalized_path.endswith(_MASTERY_NOTEBOOK_SUFFIX)
        and len(normalized_path) > len(_MASTERY_NOTEBOOK_PREFIX) + len(_MASTERY_NOTEBOOK_SUFFIX)
        and "/"
        not in normalized_path[len(_MASTERY_NOTEBOOK_PREFIX) : -len(_MASTERY_NOTEBOOK_SUFFIX)]
    ):
        return _MASTERY_NOTEBOOK_BODY_BYTES
    if normalized_path.startswith(_MASTERY_NOTEBOOK_PREFIX):
        for suffix in _MASTERY_STRUCTURE_SUFFIXES:
            if not normalized_path.endswith(suffix):
                continue
            book_id = normalized_path[len(_MASTERY_NOTEBOOK_PREFIX) : -len(suffix)]
            if book_id and "/" not in book_id:
                return _MASTERY_STRUCTURE_BODY_BYTES
    if (
        normalized_path.startswith(_QUIZ_RESULTS_PREFIX)
        and normalized_path.endswith(_QUIZ_RESULTS_SUFFIX)
        and "/" not in normalized_path[len(_QUIZ_RESULTS_PREFIX) : -len(_QUIZ_RESULTS_SUFFIX)]
        and len(normalized_path) > len(_QUIZ_RESULTS_PREFIX) + len(_QUIZ_RESULTS_SUFFIX)
    ):
        return _QUIZ_RESULTS_BODY_BYTES
    if (
        normalized_path.startswith(_COURSE_SOURCE_PREFIX)
        and normalized_path.endswith(_COURSE_SOURCE_SUFFIX)
        and len(normalized_path) > len(_COURSE_SOURCE_PREFIX) + len(_COURSE_SOURCE_SUFFIX)
        and "/" not in normalized_path[len(_COURSE_SOURCE_PREFIX) : -len(_COURSE_SOURCE_SUFFIX)]
    ):
        return course_source_body_limit()
    if normalized_path.startswith(_PARTNER_CHAT_PREFIX) and any(
        normalized_path.endswith(suffix)
        and len(normalized_path) > len(_PARTNER_CHAT_PREFIX) + len(suffix)
        and "/" not in normalized_path[len(_PARTNER_CHAT_PREFIX) : -len(suffix)]
        for suffix in _PARTNER_CHAT_SUFFIXES
    ):
        return partner_chat_body_limit()
    return None


class NotebookUpsertBodyLimitMiddleware:
    """Reject oversized binary/JSON intake before FastAPI parses it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = _request_body_limit(scope)
        if limit is None:
            await self.app(scope, receive, send)
            return
        intake_lease = None
        if str(scope.get("path") or "").rstrip("/") == _VOICE_STT_PATH:
            try:
                intake_lease = await _VOICE_STT_INTAKE_QUOTA.acquire("voice-stt-intake-global")
            except QuotaExceeded:
                await _send_rate_limited(send)
                return
        try:
            headers = dict(scope.get("headers") or [])
            raw_length = headers.get(b"content-length")
            if raw_length:
                try:
                    content_length = int(raw_length)
                    if content_length < 0 or content_length > limit:
                        await _send_too_large(send)
                        return
                except ValueError:
                    await _send_too_large(send)
                    return

            received = 0
            response_started = False

            async def limited_receive() -> Message:
                nonlocal received
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > limit:
                        raise _RequestBodyTooLarge
                return message

            async def tracked_send(message: Message) -> None:
                nonlocal response_started
                if message["type"] == "http.response.start":
                    response_started = True
                await send(message)

            try:
                await self.app(scope, limited_receive, tracked_send)
            except _RequestBodyTooLarge:
                if not response_started:
                    await _send_too_large(send)
        finally:
            if intake_lease is not None:
                await intake_lease.__aexit__(None, None, None)


async def _send_too_large(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": b'{"detail":"Request body too large"}',
        }
    )


async def _send_rate_limited(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 429,
            "headers": [(b"content-type", b"application/json"), (b"retry-after", b"1")],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": b'{"detail":"Request capacity is busy. Retry shortly"}',
        }
    )
