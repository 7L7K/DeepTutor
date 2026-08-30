"""Small ASGI request-body limits for routes that accept binary data."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from deeptutor.services.config.runtime_settings import get_chat_attachment_limits

_NOTEBOOK_UPSERT_PATH = "/api/v1/question-notebook/entries/upsert"
_JSON_ENVELOPE_BYTES = 1024 * 1024
_COURSE_SOURCE_PREFIX = "/api/v1/courses/"
_COURSE_SOURCE_SUFFIX = "/sources"
_COURSE_SOURCE_BODY_BYTES = 12 * 1024 * 1024


class _RequestBodyTooLarge(Exception):
    pass


def notebook_upsert_body_limit() -> int:
    """Allow policy-sized base64 plus bounded JSON metadata overhead."""
    max_bytes = get_chat_attachment_limits().max_total_bytes
    return ((max_bytes + 2) // 3) * 4 + _JSON_ENVELOPE_BYTES


def course_source_body_limit() -> int:
    """Bound multipart intake before FastAPI creates UploadFile objects."""
    return _COURSE_SOURCE_BODY_BYTES


def _request_body_limit(scope: Scope) -> int | None:
    path = str(scope.get("path") or "")
    normalized_path = path[:-1] if path.endswith("/") and path != "/" else path
    method = str(scope.get("method") or "").upper()
    if method != "POST":
        return None
    if path == _NOTEBOOK_UPSERT_PATH:
        return notebook_upsert_body_limit()
    if (
        normalized_path.startswith(_COURSE_SOURCE_PREFIX)
        and normalized_path.endswith(_COURSE_SOURCE_SUFFIX)
        and len(normalized_path) > len(_COURSE_SOURCE_PREFIX) + len(_COURSE_SOURCE_SUFFIX)
        and "/" not in normalized_path[len(_COURSE_SOURCE_PREFIX) : -len(_COURSE_SOURCE_SUFFIX)]
    ):
        return course_source_body_limit()
    return None


class NotebookUpsertBodyLimitMiddleware:
    """Reject oversized notebook/Course upload bodies before FastAPI parses them."""

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
