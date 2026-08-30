"""Small ASGI request-body limits for JSON routes with inline binary data."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from deeptutor.services.config.runtime_settings import get_chat_attachment_limits

_NOTEBOOK_UPSERT_PATH = "/api/v1/question-notebook/entries/upsert"
_JSON_ENVELOPE_BYTES = 1024 * 1024


class _RequestBodyTooLarge(Exception):
    pass


def notebook_upsert_body_limit() -> int:
    """Allow policy-sized base64 plus bounded JSON metadata overhead."""
    max_bytes = get_chat_attachment_limits().max_total_bytes
    return ((max_bytes + 2) // 3) * 4 + _JSON_ENVELOPE_BYTES


class NotebookUpsertBodyLimitMiddleware:
    """Reject an oversized notebook JSON request before FastAPI parses it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != _NOTEBOOK_UPSERT_PATH:
            await self.app(scope, receive, send)
            return

        limit = notebook_upsert_body_limit()
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
