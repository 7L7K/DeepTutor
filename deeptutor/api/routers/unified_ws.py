"""
Unified WebSocket Endpoint
==========================

Single ``/api/v1/ws`` endpoint for turn-based execution and replayable streaming.

Supported client message ``type`` values:

- ``message`` / ``start_turn`` — start a new turn from a payload.
- ``subscribe_turn`` — stream events of an existing turn (with ``after_seq``).
- ``subscribe_session`` — stream events of the active turn for a session.
- ``resume_from`` — resume an in-flight turn after reconnection.
- ``unsubscribe`` — stop a previously created subscription.
- ``cancel_turn`` — cancel a running turn.
- ``submit_user_reply`` — deliver the user's reply for an ``ask_user``
  paused turn so the agentic loop can resume on the same turn.
- ``regenerate`` — re-run the last user message in the given session as a
  brand-new turn. Replaces the trailing assistant message (if any) and
  reuses the session's stored capability/tools/preferences. Optional
  ``overrides`` field accepts ``capability``, ``tools``, ``knowledge_bases``,
  ``language``, ``config``, ``notebook_references``, ``history_references``.
  Errors: ``regenerate_busy`` (another turn is running) and
  ``nothing_to_regenerate`` (no prior user message).
- ``check_active_turn`` — report whether the session has a live running turn;
  replies with ``active_turn_info`` (``turn_id``/``status``), marking stale
  persisted "running" rows as cancelled when no live execution exists.
- ``user_input`` — deliver a learner answer to the turn's StreamBus
  (resolves a pending ``wait_for_input``, e.g. an ``ask_user`` pause).
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from deeptutor.services.sandbox.quota import QuotaExceeded, UserExecQuota

router = APIRouter()
logger = logging.getLogger(__name__)

# Unified chat messages may carry a base64 attachment batch, so this is larger
# than ordinary text input. It is still a fixed transport ceiling, independent
# of the configurable document parser limits; the latter must never turn into
# a multi-gigabyte WebSocket frame allowance.
_MAX_UNIFIED_WS_MESSAGE_BYTES = 64 * 1024 * 1024
_MAX_UNIFIED_CONTENT_CHARS = 200_000
_MAX_UNIFIED_FIELD_CHARS = 512
_MAX_UNIFIED_REPLY_CHARS = 12_000
_MAX_UNIFIED_LIST_ITEMS = 100
_MAX_UNIFIED_CONFIG_BYTES = 256 * 1024
# Runtime settings allow at most 40 MiB per decoded attachment. Bound the
# encoded wire value to the largest base64 string that can satisfy that
# policy, rather than letting one known field consume the whole 64 MiB frame.
_MAX_UNIFIED_ATTACHMENT_BASE64_CHARS = ((40 * 1024 * 1024 + 2) // 3) * 4
_MAX_UNIFIED_JSON_DEPTH = 32
_MAX_UNIFIED_JSON_TOKENS = 50_000
_MAX_UNIFIED_ORDINARY_MESSAGE_BYTES = 8 * 1024 * 1024
_MAX_UNIFIED_CONFIG_WIRE_CHARS = _MAX_UNIFIED_CONFIG_BYTES * 6
# Only a small, bounded number of authenticated sockets may be waiting for a
# frame. Leases are released as soon as a frame arrives or the timeout fires;
# they do not cover turn execution.
_UNIFIED_WS_RECEIVE_USER_QUOTA = UserExecQuota(max_concurrent=2, max_per_minute=240)
# Keep the protocol queue low enough that eight maximum-size attachment frames
# cannot exhaust the 2 GiB application cgroup on the 4 GiB beta host.  The
# per-user quota remains two, so one account cannot consume the whole queue.
_UNIFIED_WS_RECEIVE_GLOBAL_QUOTA = UserExecQuota(max_concurrent=8, max_per_minute=2_000)
_UNIFIED_WS_RECEIVE_GLOBAL_KEY = "unified-ws-receive-global"
_UNIFIED_WS_FIRST_FRAME_TIMEOUT_S = 30.0
_UNIFIED_WS_IDLE_FRAME_TIMEOUT_S = 120.0
# Invalid client frames are never useful after the first protocol violation.
# Close after sending one generic error rather than keeping an authenticated
# socket alive for an unbounded stream of malformed messages.
_MAX_UNIFIED_INVALID_MESSAGES = 1

_START_TURN_FIELDS = frozenset(
    {
        "type",
        "content",
        "tools",
        "capability",
        "knowledge_bases",
        "session_id",
        "course_id",
        "attachments",
        "language",
        "config",
        "notebook_references",
        "history_references",
        "question_notebook_references",
        "book_references",
        "persona",
        "skills",
        "memory_references",
        "llm_selection",
        "parent_message_id",
    }
)
_UNIFIED_WS_ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "message": _START_TURN_FIELDS,
    "start_turn": _START_TURN_FIELDS,
    "subscribe_turn": frozenset({"type", "turn_id", "after_seq", "course_id"}),
    "subscribe_session": frozenset({"type", "session_id", "after_seq", "course_id"}),
    "resume_from": frozenset({"type", "turn_id", "seq", "course_id"}),
    "unsubscribe": frozenset({"type", "turn_id", "session_id", "course_id"}),
    "cancel_turn": frozenset({"type", "turn_id", "course_id"}),
    "regenerate": frozenset({"type", "session_id", "overrides", "course_id"}),
    "check_active_turn": frozenset({"type", "session_id", "course_id"}),
    "submit_user_reply": frozenset({"type", "turn_id", "text", "answers", "course_id"}),
    "user_input": frozenset({"type", "turn_id", "content", "course_id"}),
    "ping": frozenset({"type"}),
}
_UNIFIED_WS_ATTACHMENT_FIELDS = frozenset({"type", "url", "base64", "filename", "mime_type"})
_UNIFIED_WS_NOTEBOOK_REFERENCE_FIELDS = frozenset({"notebook_id", "record_ids"})
_UNIFIED_WS_BOOK_REFERENCE_FIELDS = frozenset({"book_id", "page_ids"})
_UNIFIED_WS_LLM_SELECTION_FIELDS = frozenset({"profile_id", "model_id"})
_UNIFIED_WS_ANSWER_FIELDS = frozenset({"questionId", "id", "text"})

_PREPARSE_FIXED_OBJECT_FIELDS = {
    "attachment": _UNIFIED_WS_ATTACHMENT_FIELDS,
    "notebook_reference": _UNIFIED_WS_NOTEBOOK_REFERENCE_FIELDS,
    "book_reference": _UNIFIED_WS_BOOK_REFERENCE_FIELDS,
    "llm_selection": _UNIFIED_WS_LLM_SELECTION_FIELDS,
    "answer": _UNIFIED_WS_ANSWER_FIELDS,
}
_PREPARSE_ROOT_CONTEXTS = {
    "type": "message_type",
    "content": "root_content",
    "text": "reply_text",
    "session_id": "field_string",
    "turn_id": "field_string",
    "course_id": "field_string",
    "capability": "field_string",
    "language": "field_string",
    "persona": "field_string",
    "attachments": "attachments",
    "notebook_references": "notebook_references",
    "book_references": "book_references",
    "history_references": "string_list",
    "question_notebook_references": "integer_list",
    "tools": "string_list",
    "knowledge_bases": "string_list",
    "skills": "string_list",
    "memory_references": "string_list",
    "llm_selection": "llm_selection",
    "answers": "answers",
    "config": "dynamic_root",
    "overrides": "dynamic_root",
    "after_seq": "nullable_integer",
    "seq": "nullable_integer",
    "parent_message_id": "nullable_integer",
}
_PREPARSE_ARRAY_LIMITS = {
    "attachments": 10,
    "notebook_references": 50,
    "book_references": 50,
    "answers": 50,
    "string_list": _MAX_UNIFIED_LIST_ITEMS,
    "integer_list": _MAX_UNIFIED_LIST_ITEMS,
}
_PREPARSE_ARRAY_ITEM_CONTEXTS = {
    "attachments": "attachment",
    "notebook_references": "notebook_reference",
    "book_references": "book_reference",
    "answers": "answer",
    "string_list": "list_string",
    "integer_list": "integer",
}
_PREPARSE_OBJECT_CHILD_CONTEXTS = {
    ("attachment", "type"): "field_string",
    ("attachment", "url"): "field_string",
    ("attachment", "filename"): "filename",
    ("attachment", "mime_type"): "mime_type",
    ("attachment", "base64"): "attachment_base64",
    ("notebook_reference", "notebook_id"): "field_string",
    ("notebook_reference", "record_ids"): "string_list",
    ("book_reference", "book_id"): "field_string",
    ("book_reference", "page_ids"): "string_list",
    ("llm_selection", "profile_id"): "field_string",
    ("llm_selection", "model_id"): "field_string",
    ("answer", "questionId"): "field_string",
    ("answer", "id"): "field_string",
    ("answer", "text"): "reply_text",
}


class _UnifiedWsFrameTooLarge(ValueError):
    """Raised before JSON parsing when a WebSocket text frame exceeds the cap."""


def _utf8_byte_length(value: str) -> int:
    """Return the UTF-8 byte length without allocating an encoded copy."""
    if value.isascii():
        return len(value)
    total = 0
    for char in value:
        codepoint = ord(char)
        total += (
            1 if codepoint <= 0x7F else 2 if codepoint <= 0x7FF else 3 if codepoint <= 0xFFFF else 4
        )
    return total


def _fits_utf8_byte_limit(value: str, maximum: int) -> bool:
    """Check a UTF-8 byte ceiling without allocating a duplicate encoded frame."""
    if len(value) > maximum:
        return False
    return _utf8_byte_length(value) <= maximum


def _reject_duplicate_json_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting ambiguous last-key-wins input."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON object contains duplicate fields.")
        result[key] = value
    return result


class _UnifiedWsJsonBudgetScanner:
    """Allocation-light structural validation before ``json.loads``.

    The scanner decodes only bounded object keys and the short message type.
    Large string bodies are counted in place, so invalid padding cannot make
    the JSON decoder materialize a second full object graph first.
    """

    def __init__(self, raw: str, *, frame_bytes: int) -> None:
        self.raw = raw
        self.length = len(raw)
        self.frame_bytes = frame_bytes
        self.tokens = 0
        self.attachment_base64_bytes = 0
        self.root_fields: set[str] | None = None
        self.message_type: str | None = None
        self.root_string_lengths: dict[str, int] = {}

    def scan(self) -> None:
        end = self._parse_value(self._skip_ws(0), context="root", depth=0)
        if self._skip_ws(end) != self.length:
            raise ValueError("Invalid JSON structure.")
        if self.root_fields is not None:
            allowed = _UNIFIED_WS_ALLOWED_FIELDS.get(self.message_type or "", {"type"})
            if self.root_fields.difference(allowed):
                raise ValueError("Message contains unsupported fields.")
        if (
            self.message_type == "user_input"
            and self.root_string_lengths.get("content", 0) > _MAX_UNIFIED_REPLY_CHARS
        ):
            raise ValueError("user_input content is too large.")
        ordinary_bytes = self.frame_bytes - self.attachment_base64_bytes
        if ordinary_bytes > _MAX_UNIFIED_ORDINARY_MESSAGE_BYTES:
            raise ValueError("Message envelope is too large.")

    def _consume_token(self) -> None:
        self.tokens += 1
        if self.tokens > _MAX_UNIFIED_JSON_TOKENS:
            raise ValueError("Message has too many JSON items.")

    def _skip_ws(self, index: int) -> int:
        while index < self.length and self.raw[index] in " \t\r\n":
            index += 1
        return index

    def _parse_value(self, index: int, *, context: str, depth: int) -> int:
        self._consume_token()
        index = self._skip_ws(index)
        if index >= self.length:
            raise ValueError("Missing JSON value.")
        start = index
        char = self.raw[index]
        if context in {"integer", "nullable_integer"}:
            if context == "nullable_integer" and self.raw.startswith("null", index):
                return index + 4
            if char not in "-0123456789":
                raise ValueError("JSON integer is invalid.")
            end = self._scan_number(index)
            number = self.raw[index:end]
            if any(marker in number for marker in ".eE") or len(number.lstrip("-")) > 19:
                raise ValueError("JSON integer is invalid.")
            return end
        if char == '"':
            maximum = {
                "message_type": 64,
                "root_content": _MAX_UNIFIED_CONTENT_CHARS,
                "reply_text": _MAX_UNIFIED_REPLY_CHARS,
                "field_string": _MAX_UNIFIED_FIELD_CHARS,
                "filename": 255,
                "mime_type": 255,
                "attachment_base64": _MAX_UNIFIED_ATTACHMENT_BASE64_CHARS,
                "list_string": _MAX_UNIFIED_FIELD_CHARS,
            }.get(context, _MAX_UNIFIED_CONFIG_BYTES)
            end, base64_wire_bytes, decoded_chars = self._scan_string(index, maximum=maximum)
            if context == "message_type":
                self.message_type = self._decode_string(index, end)
            elif context == "root_content":
                self.root_string_lengths["content"] = decoded_chars
            elif context == "attachment_base64" and base64_wire_bytes is not None:
                self.attachment_base64_bytes += base64_wire_bytes
            return end
        if char == "{":
            end = self._parse_object(index, context=context, depth=depth + 1)
        elif char == "[":
            end = self._parse_array(index, context=context, depth=depth + 1)
        elif self.raw.startswith("true", index):
            end = index + 4
        elif self.raw.startswith("false", index):
            end = index + 5
        elif self.raw.startswith("null", index):
            end = index + 4
        else:
            end = self._scan_number(index)
        if context == "dynamic_root" and end - start > _MAX_UNIFIED_CONFIG_WIRE_CHARS:
            raise ValueError("Dynamic payload is too large.")
        return end

    def _parse_object(self, index: int, *, context: str, depth: int) -> int:
        if depth > _MAX_UNIFIED_JSON_DEPTH:
            raise ValueError("Message JSON is nested too deeply.")
        fields: set[str] = set()
        allowed = _PREPARSE_FIXED_OBJECT_FIELDS.get(context)
        index = self._skip_ws(index + 1)
        if index < self.length and self.raw[index] == "}":
            if context == "root":
                self.root_fields = fields
            return index + 1
        while True:
            if index >= self.length or self.raw[index] != '"':
                raise ValueError("JSON object key is invalid.")
            self._consume_token()
            key_start = index
            key_limit = (
                _MAX_UNIFIED_CONFIG_BYTES
                if context in {"dynamic", "dynamic_root"}
                else _MAX_UNIFIED_FIELD_CHARS
            )
            index, _, _ = self._scan_string(index, maximum=key_limit)
            key = self._decode_string(key_start, index)
            if key in fields:
                raise ValueError("JSON object contains duplicate fields.")
            fields.add(key)
            if allowed is not None and key not in allowed:
                raise ValueError(f"{context} contains unsupported fields.")
            index = self._skip_ws(index)
            if index >= self.length or self.raw[index] != ":":
                raise ValueError("JSON object is missing a value separator.")
            child_context = self._child_context(context, key)
            index = self._parse_value(index + 1, context=child_context, depth=depth)
            index = self._skip_ws(index)
            if index >= self.length:
                raise ValueError("JSON object is incomplete.")
            if self.raw[index] == "}":
                if context == "root":
                    self.root_fields = fields
                return index + 1
            if self.raw[index] != ",":
                raise ValueError("JSON object item separator is invalid.")
            index = self._skip_ws(index + 1)

    def _parse_array(self, index: int, *, context: str, depth: int) -> int:
        if depth > _MAX_UNIFIED_JSON_DEPTH:
            raise ValueError("Message JSON is nested too deeply.")
        maximum = _PREPARSE_ARRAY_LIMITS.get(context, _MAX_UNIFIED_JSON_TOKENS)
        item_context = _PREPARSE_ARRAY_ITEM_CONTEXTS.get(
            context, "dynamic" if context in {"dynamic", "dynamic_root"} else "generic"
        )
        count = 0
        index = self._skip_ws(index + 1)
        if index < self.length and self.raw[index] == "]":
            return index + 1
        while True:
            count += 1
            if count > maximum:
                raise ValueError("JSON array has too many items.")
            index = self._parse_value(index, context=item_context, depth=depth)
            index = self._skip_ws(index)
            if index >= self.length:
                raise ValueError("JSON array is incomplete.")
            if self.raw[index] == "]":
                return index + 1
            if self.raw[index] != ",":
                raise ValueError("JSON array item separator is invalid.")
            index = self._skip_ws(index + 1)

    def _child_context(self, parent: str, key: str) -> str:
        if parent == "root":
            return _PREPARSE_ROOT_CONTEXTS.get(key, "generic")
        if parent in {"dynamic", "dynamic_root"}:
            return "dynamic"
        return _PREPARSE_OBJECT_CHILD_CONTEXTS.get((parent, key), "generic")

    def _scan_string(self, index: int, *, maximum: int) -> tuple[int, int | None, int]:
        payload_start = index + 1
        index = payload_start
        decoded_chars = 0
        base64_compatible = True
        base64_alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        base64_padding = 0
        while index < self.length:
            char = self.raw[index]
            if char == '"':
                valid_base64 = (
                    base64_compatible
                    and decoded_chars > 0
                    and decoded_chars % 4 == 0
                    and base64_padding <= 2
                )
                return index + 1, index - payload_start if valid_base64 else None, decoded_chars
            if char == "\\":
                index += 1
                if index >= self.length or self.raw[index] not in '"\\/bfnrtu':
                    raise ValueError("JSON string escape is invalid.")
                if self.raw[index] == "u":
                    escape = self.raw[index + 1 : index + 5]
                    if len(escape) != 4 or any(c not in "0123456789abcdefABCDEF" for c in escape):
                        raise ValueError("JSON unicode escape is invalid.")
                    decoded_char = chr(int(escape, 16))
                    index += 4
                else:
                    decoded_char = {
                        '"': '"',
                        "\\": "\\",
                        "/": "/",
                        "b": "\b",
                        "f": "\f",
                        "n": "\n",
                        "r": "\r",
                        "t": "\t",
                    }[self.raw[index]]
            elif ord(char) < 0x20:
                raise ValueError("JSON string contains a control character.")
            else:
                decoded_char = char
            if decoded_char == "=":
                base64_padding += 1
                if base64_padding > 2:
                    base64_compatible = False
            elif decoded_char not in base64_alphabet or base64_padding:
                base64_compatible = False
            decoded_chars += 1
            if decoded_chars > maximum:
                raise ValueError("JSON string is too large.")
            index += 1
        raise ValueError("JSON string is incomplete.")

    def _decode_string(self, start: int, end: int) -> str:
        """Decode one already-scanned bounded key/value without JSON parsing."""
        decoded: list[str] = []
        index = start + 1
        stop = end - 1
        escapes = {
            '"': '"',
            "\\": "\\",
            "/": "/",
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
        }
        while index < stop:
            char = self.raw[index]
            if char != "\\":
                decoded.append(char)
                index += 1
                continue
            index += 1
            escape = self.raw[index]
            if escape == "u":
                decoded.append(chr(int(self.raw[index + 1 : index + 5], 16)))
                index += 5
            else:
                decoded.append(escapes[escape])
                index += 1
        return "".join(decoded)

    def _scan_number(self, index: int) -> int:
        start = index
        if self.raw[index] == "-":
            index += 1
        if index >= self.length:
            raise ValueError("JSON number is incomplete.")
        if self.raw[index] == "0":
            index += 1
        elif self.raw[index].isdigit() and self.raw[index] != "0":
            while index < self.length and self.raw[index].isdigit():
                index += 1
        else:
            raise ValueError("JSON value is invalid.")
        if index < self.length and self.raw[index] == ".":
            index += 1
            fraction_start = index
            while index < self.length and self.raw[index].isdigit():
                index += 1
            if index == fraction_start:
                raise ValueError("JSON number fraction is invalid.")
        if index < self.length and self.raw[index] in "eE":
            index += 1
            if index < self.length and self.raw[index] in "+-":
                index += 1
            exponent_start = index
            while index < self.length and self.raw[index].isdigit():
                index += 1
            if index == exponent_start:
                raise ValueError("JSON number exponent is invalid.")
        if index - start > 128:
            raise ValueError("JSON number is too large.")
        return index


def _bounded_json_serialized_size(value: object, *, maximum: int, label: str) -> None:
    """Match the old ``json.dumps`` size gate without building a JSON copy."""
    total = 0
    tokens = 0
    stack: list[tuple[object, int]] = [(value, 0)]

    def add(amount: int) -> None:
        nonlocal total
        total += amount
        if total > maximum:
            raise ValueError(f"{label} is too large")

    def add_string(text: str) -> None:
        add(2)
        for char in text:
            if char in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
                add(2)
            elif ord(char) < 0x20:
                add(6)
            else:
                add(1)

    while stack:
        current, depth = stack.pop()
        tokens += 1
        if tokens > _MAX_UNIFIED_JSON_TOKENS or depth > _MAX_UNIFIED_JSON_DEPTH:
            raise ValueError(f"{label} is invalid")
        if current is None:
            add(4)
        elif current is True:
            add(4)
        elif current is False:
            add(5)
        elif isinstance(current, str):
            add_string(current)
        elif isinstance(current, (int, float)):
            add(len(str(current)))
        elif isinstance(current, list):
            add(2 + max(0, len(current) - 1) * 2)
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, dict):
            add(2 + max(0, len(current) - 1) * 2)
            for key, item in current.items():
                if not isinstance(key, str):
                    raise ValueError(f"{label} is invalid")
                add_string(key)
                add(2)
                stack.append((item, depth + 1))
        else:
            raise ValueError(f"{label} is invalid")


def _decode_bounded_unified_ws_text(raw: object) -> dict[str, Any]:
    """Apply the transport ceiling before allocating JSON parser structures."""
    if not isinstance(raw, str):
        raise ValueError("WebSocket frame must be text.")
    if not _fits_utf8_byte_limit(raw, _MAX_UNIFIED_WS_MESSAGE_BYTES):
        raise _UnifiedWsFrameTooLarge("Message is too large.")
    try:
        frame_bytes = _utf8_byte_length(raw)
        _UnifiedWsJsonBudgetScanner(raw, frame_bytes=frame_bytes).scan()
        message = json.loads(raw, object_pairs_hook=_reject_duplicate_json_fields)
        return _validate_unified_ws_message(message)
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as exc:
        if isinstance(exc, _UnifiedWsFrameTooLarge):
            raise
        raise ValueError("Invalid message.") from exc


async def _receive_bounded_unified_ws_message(ws: WebSocket, *, timeout_s: float) -> dict[str, Any]:
    """Receive a text frame and reject it before JSON parsing when oversized.

    Uvicorn is configured with the same 64 MiB hard cap, so an oversized
    network frame is rejected by the server protocol before ASGI receives it.
    This application-level guard covers direct/test ASGI invocation and avoids
    allocating a second encoded copy merely to measure UTF-8 bytes.
    """
    from deeptutor.multi_user.context import get_current_user

    leases = AsyncExitStack()
    try:
        user_lease = await _UNIFIED_WS_RECEIVE_USER_QUOTA.acquire(get_current_user().id)
        await leases.enter_async_context(user_lease)
        global_lease = await _UNIFIED_WS_RECEIVE_GLOBAL_QUOTA.acquire(
            _UNIFIED_WS_RECEIVE_GLOBAL_KEY
        )
        await leases.enter_async_context(global_lease)
        frame = await asyncio.wait_for(ws.receive(), timeout=timeout_s)
        if frame.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(frame.get("code", 1000))
        return _decode_bounded_unified_ws_text(frame.get("text"))
    finally:
        await leases.aclose()


def _bounded_ws_string(
    value: object, *, label: str, maximum: int = _MAX_UNIFIED_FIELD_CHARS
) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"{label} is invalid")
    return value


def _bounded_ws_list(value: object, *, label: str, maximum: int = _MAX_UNIFIED_LIST_ITEMS) -> list:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{label} is invalid")
    return value


def _bounded_ws_object(
    value: object, *, label: str, allowed_fields: frozenset[str]
) -> dict[str, Any]:
    """Validate one fixed-shape client protocol object.

    Capability ``config`` remains intentionally extensible and is bounded by
    its separate aggregate limit. This helper is for protocol-owned nested
    objects whose complete wire shape is defined by the unified WS contract.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{label} is invalid")
    if set(value).difference(allowed_fields):
        raise ValueError(f"{label} contains unsupported fields")
    return value


def _bounded_ws_nonnegative_int(value: object, *, label: str, maximum: int = 10_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > maximum:
        raise ValueError(f"{label} is invalid")
    return value


def _validate_unified_ws_message(message: object) -> dict[str, Any]:
    """Validate transport shape before dispatching or persisting a turn."""
    if not isinstance(message, dict):
        raise ValueError("Message must be an object.")
    msg_type = _bounded_ws_string(message.get("type"), label="Message type", maximum=64)
    unexpected_fields = set(message).difference(_UNIFIED_WS_ALLOWED_FIELDS.get(msg_type, {"type"}))
    if unexpected_fields:
        raise ValueError("Message contains unsupported fields.")

    for key in ("session_id", "turn_id", "course_id"):
        if key in message and message[key] is not None:
            _bounded_ws_string(message[key], label=key)
    for key in ("after_seq", "seq"):
        if key in message and message[key] is not None:
            _bounded_ws_nonnegative_int(message[key], label=key)

    if msg_type in {"message", "start_turn"}:
        _bounded_ws_string(
            message.get("content"), label="content", maximum=_MAX_UNIFIED_CONTENT_CHARS
        )
        for key in ("capability", "language", "persona"):
            if key in message and message[key] is not None:
                _bounded_ws_string(message[key], label=key)
        for key in ("tools", "knowledge_bases", "skills", "memory_references"):
            if key not in message:
                continue
            values = _bounded_ws_list(message[key], label=key)
            for value in values:
                _bounded_ws_string(value, label=f"{key} item")

        attachments = message.get("attachments")
        if attachments is not None:
            for item in _bounded_ws_list(attachments, label="attachments", maximum=10):
                item = _bounded_ws_object(
                    item,
                    label="attachment",
                    allowed_fields=_UNIFIED_WS_ATTACHMENT_FIELDS,
                )
                for key, maximum in (
                    ("type", _MAX_UNIFIED_FIELD_CHARS),
                    ("url", _MAX_UNIFIED_FIELD_CHARS),
                    ("filename", 255),
                    ("mime_type", 255),
                ):
                    if key in item and item[key] is not None:
                        _bounded_ws_string(item[key], label=f"attachment {key}", maximum=maximum)
                if "base64" in item and item["base64"] is not None:
                    _bounded_ws_string(
                        item["base64"],
                        label="attachment base64",
                        maximum=_MAX_UNIFIED_ATTACHMENT_BASE64_CHARS,
                    )

        for key in ("notebook_references", "book_references"):
            if key not in message or message[key] is None:
                continue
            references = _bounded_ws_list(message[key], label=key, maximum=50)
            for reference in references:
                reference = _bounded_ws_object(
                    reference,
                    label=f"{key} item",
                    allowed_fields=(
                        _UNIFIED_WS_NOTEBOOK_REFERENCE_FIELDS
                        if key == "notebook_references"
                        else _UNIFIED_WS_BOOK_REFERENCE_FIELDS
                    ),
                )
                _bounded_ws_string(
                    reference.get("notebook_id", reference.get("book_id")), label=f"{key} id"
                )
                id_key = "record_ids" if key == "notebook_references" else "page_ids"
                for item_id in _bounded_ws_list(reference.get(id_key, []), label=id_key):
                    _bounded_ws_string(item_id, label=f"{id_key} item")
        if "history_references" in message:
            for session_id in _bounded_ws_list(
                message["history_references"], label="history_references"
            ):
                _bounded_ws_string(session_id, label="history_references item")
        if "question_notebook_references" in message:
            for item in _bounded_ws_list(
                message["question_notebook_references"],
                label="question_notebook_references",
            ):
                _bounded_ws_nonnegative_int(
                    item, label="question_notebook_reference", maximum=2**63 - 1
                )
        if "config" in message and message["config"] is not None:
            if not isinstance(message["config"], dict):
                raise ValueError("config is invalid")
            _bounded_json_serialized_size(
                message["config"], maximum=_MAX_UNIFIED_CONFIG_BYTES, label="config"
            )
        selection = message.get("llm_selection")
        if selection is not None:
            selection = _bounded_ws_object(
                selection,
                label="llm_selection",
                allowed_fields=_UNIFIED_WS_LLM_SELECTION_FIELDS,
            )
            for key in ("profile_id", "model_id"):
                _bounded_ws_string(selection.get(key), label=f"llm_selection.{key}")
        if "parent_message_id" in message:
            parent_id = message["parent_message_id"]
            if parent_id is not None:
                _bounded_ws_nonnegative_int(parent_id, label="parent_message_id", maximum=2**63 - 1)
        return message

    if msg_type in {"submit_user_reply", "user_input"}:
        if msg_type == "submit_user_reply":
            if "text" in message and message["text"] is not None:
                _bounded_ws_string(message["text"], label="text", maximum=_MAX_UNIFIED_REPLY_CHARS)
            answers = message.get("answers")
            if answers is not None:
                for answer in _bounded_ws_list(answers, label="answers", maximum=50):
                    answer = _bounded_ws_object(
                        answer,
                        label="answer",
                        allowed_fields=_UNIFIED_WS_ANSWER_FIELDS,
                    )
                    _bounded_ws_string(
                        answer.get("questionId", answer.get("id")), label="answer questionId"
                    )
                    _bounded_ws_string(
                        answer.get("text", ""),
                        label="answer text",
                        maximum=_MAX_UNIFIED_REPLY_CHARS,
                    )
        else:
            _bounded_ws_string(
                message.get("content", ""), label="content", maximum=_MAX_UNIFIED_REPLY_CHARS
            )
        return message

    if msg_type in {
        "subscribe_turn",
        "subscribe_session",
        "resume_from",
        "cancel_turn",
        "regenerate",
        "check_active_turn",
        "unsubscribe",
        "ping",
    }:
        if msg_type == "regenerate" and message.get("overrides") is not None:
            overrides = message["overrides"]
            if not isinstance(overrides, dict):
                raise ValueError("overrides are invalid")
            _bounded_json_serialized_size(
                overrides, maximum=_MAX_UNIFIED_CONFIG_BYTES, label="overrides"
            )
        return message

    # Unknown types are still returned so the route can issue its existing
    # protocol error; their envelope has already been bounded above.
    return message


@router.websocket("/ws")
async def unified_websocket(ws: WebSocket) -> None:
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth, ws_revalidate_auth
    from deeptutor.multi_user.context import reset_current_user

    user_token = await ws_require_auth(ws)
    if user_token is ws_auth_failed:
        return

    await ws.accept()
    closed = False
    subscription_tasks: dict[str, asyncio.Task[None]] = {}

    async def safe_send(data: dict[str, Any]) -> None:
        nonlocal closed
        if closed:
            return
        try:
            # default=str so one non-serializable value inside an event can
            # never poison the push channel (send_json would raise, flag the
            # socket as closed, and silently freeze the stream for the user).
            await ws.send_text(json.dumps(data, ensure_ascii=False, default=str))
        except Exception:
            closed = True

    async def stop_subscription(key: str) -> None:
        task = subscription_tasks.pop(key, None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def runtime_for(course_id: str | None):
        from deeptutor.services.session import get_turn_runtime_manager

        if course_id:
            from deeptutor.courses.service import install_personal_course_context

            install_personal_course_context()
        return get_turn_runtime_manager(personal=bool(course_id))

    async def authorize_session(
        runtime,
        session_id: str,
        course_id: str | None,
        *,
        writable: bool = False,
    ) -> bool:
        session = await runtime.store.get_session(session_id)
        if session is None or (session.get("course_id") or None) != (course_id or None):
            await safe_send({"type": "error", "content": "Session not found."})
            return False
        if course_id and writable:
            from deeptutor.courses.repository import CourseNotFoundError
            from deeptutor.courses.service import CourseUnavailableError, get_current_course_service

            try:
                course = get_current_course_service().get(course_id)
            except (CourseNotFoundError, CourseUnavailableError):
                await safe_send({"type": "error", "content": "Session not found."})
                return False
            if course.state != "active":
                await safe_send(
                    {"type": "error", "content": "Archived Course sessions are read-only."}
                )
                return False
        return True

    async def authorize_turn(
        runtime,
        turn_id: str,
        course_id: str | None,
        *,
        writable: bool = False,
    ) -> bool:
        turn = await runtime.store.get_turn(turn_id)
        if turn is None:
            await safe_send({"type": "error", "content": "Turn not found."})
            return False
        return await authorize_session(
            runtime,
            str(turn.get("session_id") or ""),
            course_id,
            writable=writable,
        )

    def course_is_active(course_id: str | None) -> bool:
        if not course_id:
            return True
        from deeptutor.courses.repository import CourseNotFoundError
        from deeptutor.courses.service import CourseUnavailableError, get_current_course_service

        try:
            return get_current_course_service().get(course_id).state == "active"
        except (CourseNotFoundError, CourseUnavailableError):
            return False

    async def subscribe_turn(
        turn_id: str, after_seq: int = 0, course_id: str | None = None
    ) -> None:
        async def _forward() -> None:
            runtime = runtime_for(course_id)
            async for event in runtime.subscribe_turn(
                turn_id,
                after_seq=after_seq,
                reconcile_orphan=course_is_active(course_id),
            ):
                if not await ws_revalidate_auth(ws):
                    return
                await safe_send(event)

        runtime = runtime_for(course_id)
        if not await authorize_turn(runtime, turn_id, course_id):
            return
        await stop_subscription(turn_id)
        subscription_tasks[turn_id] = asyncio.create_task(_forward())

    async def subscribe_session(
        session_id: str, after_seq: int = 0, course_id: str | None = None
    ) -> None:
        async def _forward() -> None:
            runtime = runtime_for(course_id)
            async for event in runtime.subscribe_session(
                session_id,
                after_seq=after_seq,
                reconcile_orphan=course_is_active(course_id),
            ):
                if not await ws_revalidate_auth(ws):
                    return
                await safe_send(event)

        runtime = runtime_for(course_id)
        if not await authorize_session(runtime, session_id, course_id):
            return
        key = f"session:{session_id}"
        await stop_subscription(key)
        subscription_tasks[key] = asyncio.create_task(_forward())

    invalid_messages = 0
    received_messages = 0

    try:
        while not closed:
            if not await ws_revalidate_auth(ws):
                closed = True
                break
            try:
                msg = await _receive_bounded_unified_ws_message(
                    ws,
                    timeout_s=(
                        _UNIFIED_WS_FIRST_FRAME_TIMEOUT_S
                        if received_messages == 0
                        else _UNIFIED_WS_IDLE_FRAME_TIMEOUT_S
                    ),
                )
            except _UnifiedWsFrameTooLarge:
                await safe_send({"type": "error", "content": "Message is too large."})
                closed = True
                break
            except QuotaExceeded:
                await safe_send(
                    {"type": "error", "content": "Socket capacity is busy. Retry shortly."}
                )
                closed = True
                break
            except TimeoutError:
                await safe_send({"type": "error", "content": "Socket request timed out."})
                closed = True
                break
            except ValueError:
                await safe_send({"type": "error", "content": "Invalid message."})
                invalid_messages += 1
                if invalid_messages >= _MAX_UNIFIED_INVALID_MESSAGES:
                    closed = True
                    break
                continue

            received_messages += 1

            # The first check protects an idle socket before it blocks on
            # receive; this second check preserves the existing guarantee
            # that a user disabled while the socket was waiting cannot start
            # a turn with the just-received message.
            if not await ws_revalidate_auth(ws):
                closed = True
                break

            msg_type = msg.get("type")
            requested_course_id = str(msg.get("course_id") or "").strip() or None

            if msg_type in {"message", "start_turn"}:
                runtime = runtime_for(requested_course_id)
                try:
                    _, turn = await runtime.start_turn(msg)
                except RuntimeError as exc:
                    await safe_send(
                        {
                            "type": "error",
                            "source": "unified_ws",
                            "stage": "",
                            "content": str(exc),
                            "metadata": {"turn_terminal": True, "status": "rejected"},
                            "session_id": str(msg.get("session_id") or ""),
                            "turn_id": "",
                            "seq": 0,
                        }
                    )
                    continue
                await subscribe_turn(turn["id"], after_seq=0, course_id=requested_course_id)
                continue

            if msg_type == "ping":
                # Client-side heartbeat. Respond with a lightweight pong so
                # the client knows the socket is alive; the client never
                # consumes pong as a user-visible event (see unified-ws.ts
                # filter below) but does refresh ``lastReceivedAt`` from it.
                await safe_send({"type": "pong"})
                continue

            if msg_type == "subscribe_turn":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await safe_send({"type": "error", "content": "Missing turn_id."})
                    continue
                await subscribe_turn(
                    turn_id,
                    after_seq=int(msg.get("after_seq") or 0),
                    course_id=requested_course_id,
                )
                continue

            if msg_type == "subscribe_session":
                session_id = str(msg.get("session_id") or "").strip()
                if not session_id:
                    await safe_send({"type": "error", "content": "Missing session_id."})
                    continue
                await subscribe_session(
                    session_id,
                    after_seq=int(msg.get("after_seq") or 0),
                    course_id=requested_course_id,
                )
                continue

            if msg_type == "check_active_turn":
                session_id = str(msg.get("session_id") or "").strip()
                if not session_id:
                    await safe_send({"type": "error", "content": "Missing session_id."})
                    continue
                runtime = runtime_for(requested_course_id)
                if not await authorize_session(
                    runtime, session_id, requested_course_id, writable=True
                ):
                    continue
                active_turn = await runtime.store.get_active_turn(session_id)
                if active_turn:
                    # Verify the turn has a live execution; stale persisted
                    # "running" rows (e.g. after server restart) have none.
                    turn_id = active_turn["id"]
                    has_live = await runtime.has_live_execution(turn_id)
                    if has_live:
                        await safe_send(
                            {
                                "type": "active_turn_info",
                                "turn_id": turn_id,
                                "status": active_turn.get("status", "running"),
                            }
                        )
                    else:
                        # Stale turn from a previous process — mark it terminal
                        # so create_turn won't reject the upcoming start_turn.
                        await runtime.store.update_turn_status(
                            turn_id, "cancelled", "Stale turn after restart"
                        )
                        await safe_send(
                            {"type": "active_turn_info", "turn_id": "", "status": "none"}
                        )
                else:
                    await safe_send({"type": "active_turn_info", "turn_id": "", "status": "none"})
                continue

            if msg_type == "resume_from":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await safe_send({"type": "error", "content": "Missing turn_id."})
                    continue
                await subscribe_turn(
                    turn_id,
                    after_seq=int(msg.get("seq") or 0),
                    course_id=requested_course_id,
                )
                continue

            if msg_type == "unsubscribe":
                turn_id = str(msg.get("turn_id") or "").strip()
                if turn_id:
                    await stop_subscription(turn_id)
                session_id = str(msg.get("session_id") or "").strip()
                if session_id:
                    await stop_subscription(f"session:{session_id}")
                continue

            if msg_type == "cancel_turn":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await safe_send({"type": "error", "content": "Missing turn_id."})
                    continue
                runtime = runtime_for(requested_course_id)
                if not await authorize_turn(runtime, turn_id, requested_course_id, writable=True):
                    continue
                cancelled = await runtime.cancel_turn(turn_id)
                if not cancelled:
                    await safe_send({"type": "error", "content": f"Turn not found: {turn_id}"})
                continue

            if msg_type == "submit_user_reply":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await safe_send({"type": "error", "content": "Missing turn_id."})
                    continue
                # Accept either the legacy ``text`` (single free-form
                # reply) or the v2 ``answers`` (list of {questionId, text}
                # pairs). Empty text is allowed (lets the user signal "I
                # have no answer" without typing).
                text = msg.get("text")
                text_str = str(text) if text is not None else None
                answers_raw = msg.get("answers")
                answers: list[dict[str, Any]] | None = None
                if isinstance(answers_raw, list):
                    cleaned: list[dict[str, Any]] = []
                    for entry in answers_raw:
                        if not isinstance(entry, dict):
                            continue
                        qid = str(entry.get("questionId") or entry.get("id") or "").strip()
                        if not qid:
                            continue
                        cleaned.append({"questionId": qid, "text": str(entry.get("text") or "")})
                    answers = cleaned or None
                runtime = runtime_for(requested_course_id)
                if not await authorize_turn(runtime, turn_id, requested_course_id, writable=True):
                    continue
                accepted = await runtime.submit_user_reply(turn_id, text=text_str, answers=answers)
                if not accepted:
                    await safe_send(
                        {
                            "type": "error",
                            "content": (f"Turn {turn_id} is not awaiting a user reply."),
                        }
                    )
                continue

            if msg_type == "regenerate":
                session_id = str(msg.get("session_id") or "").strip()
                if not session_id:
                    await safe_send({"type": "error", "content": "Missing session_id."})
                    continue
                runtime = runtime_for(requested_course_id)
                if not await authorize_session(
                    runtime, session_id, requested_course_id, writable=True
                ):
                    continue
                overrides = msg.get("overrides") if isinstance(msg.get("overrides"), dict) else None
                try:
                    _, turn = await runtime.regenerate_last_turn(
                        session_id,
                        overrides=overrides,
                    )
                except RuntimeError as exc:
                    await safe_send(
                        {
                            "type": "error",
                            "source": "unified_ws",
                            "stage": "",
                            "content": str(exc),
                            "metadata": {
                                "turn_terminal": True,
                                "status": "rejected",
                                "reason": str(exc),
                            },
                            "session_id": session_id,
                            "turn_id": "",
                            "seq": 0,
                        }
                    )
                    continue
                await subscribe_turn(turn["id"], after_seq=0, course_id=requested_course_id)
                continue

            if msg_type == "user_input":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await safe_send({"type": "error", "content": "Missing turn_id for user_input."})
                    continue
                runtime = runtime_for(requested_course_id)
                if not await authorize_turn(runtime, turn_id, requested_course_id, writable=True):
                    continue
                from deeptutor.core.stream_bus import get_bus

                bus = get_bus(turn_id)
                if bus is None:
                    await safe_send(
                        {"type": "error", "content": f"No active bus for turn: {turn_id}"}
                    )
                    continue
                bus.submit_input(str(msg.get("content") or ""))
                continue

            await safe_send({"type": "error", "content": f"Unknown type: {msg_type}"})

    except WebSocketDisconnect:
        logger.debug("Client disconnected from /ws")
    except Exception as exc:
        logger.error("Unified WS error: %s", exc, exc_info=True)
        await safe_send({"type": "error", "content": str(exc)})
    finally:
        closed = True
        for key in list(subscription_tasks.keys()):
            await stop_subscription(key)
        if user_token is not None:
            reset_current_user(user_token)
