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
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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


def _bounded_ws_nonnegative_int(value: object, *, label: str, maximum: int = 10_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > maximum:
        raise ValueError(f"{label} is invalid")
    return value


def _validate_unified_ws_message(message: object) -> dict[str, Any]:
    """Validate transport shape before dispatching or persisting a turn."""
    if not isinstance(message, dict):
        raise ValueError("Message must be an object.")
    msg_type = _bounded_ws_string(message.get("type"), label="Message type", maximum=64)

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
                if not isinstance(item, dict):
                    raise ValueError("attachments are invalid")
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
                        maximum=_MAX_UNIFIED_WS_MESSAGE_BYTES,
                    )

        for key in ("notebook_references", "book_references"):
            if key not in message or message[key] is None:
                continue
            references = _bounded_ws_list(message[key], label=key, maximum=50)
            for reference in references:
                if not isinstance(reference, dict):
                    raise ValueError(f"{key} are invalid")
                _bounded_ws_string(
                    reference.get("notebook_id", reference.get("book_id")), label=f"{key} id"
                )
                id_key = "record_ids" if key == "notebook_references" else "page_ids"
                for item_id in _bounded_ws_list(reference.get(id_key, []), label=id_key):
                    _bounded_ws_string(item_id, label=f"{id_key} item")
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
            if len(json.dumps(message["config"], ensure_ascii=False)) > _MAX_UNIFIED_CONFIG_BYTES:
                raise ValueError("config is too large")
        selection = message.get("llm_selection")
        if selection is not None:
            if not isinstance(selection, dict):
                raise ValueError("llm_selection is invalid")
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
                    if not isinstance(answer, dict):
                        raise ValueError("answers are invalid")
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
            if len(json.dumps(overrides, ensure_ascii=False)) > _MAX_UNIFIED_CONFIG_BYTES:
                raise ValueError("overrides are too large")
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

    try:
        while not closed:
            raw = await ws.receive_text()
            if not await ws_revalidate_auth(ws):
                closed = True
                break
            if len(raw.encode("utf-8")) > _MAX_UNIFIED_WS_MESSAGE_BYTES:
                await safe_send({"type": "error", "content": "Message is too large."})
                closed = True
                break
            try:
                msg = json.loads(raw)
                _validate_unified_ws_message(msg)
            except (json.JSONDecodeError, RecursionError, ValueError, TypeError):
                await safe_send({"type": "error", "content": "Invalid message."})
                continue

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
