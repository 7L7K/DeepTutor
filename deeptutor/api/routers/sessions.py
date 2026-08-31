"""
Unified session history API.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from deeptutor.services.session import (
    get_personal_sqlite_session_store,
    get_session_store,
    get_sqlite_session_store,
)
from deeptutor.services.storage.attachment_store import get_attachment_store

logger = logging.getLogger(__name__)

router = APIRouter()


def _distinct_session_stores(*, sqlite_only: bool = False):
    primary = get_sqlite_session_store() if sqlite_only else get_session_store()
    try:
        personal = get_personal_sqlite_session_store()
    except RuntimeError:
        # Standalone router/unit-test apps may omit the normal auth dependency.
        # Production requests always have an installed current-user context.
        return [primary]
    primary_path = getattr(primary, "db_path", None)
    personal_path = getattr(personal, "db_path", None)
    return (
        [primary] if primary is personal or primary_path == personal_path else [primary, personal]
    )


async def _owned_session_store(session_id: str, *, sqlite_only: bool = False):
    for store in _distinct_session_stores(sqlite_only=sqlite_only):
        if await store.get_session(session_id) is not None:
            return store
    return None


def _assert_course_session_write_allowed(session: dict[str, Any] | None) -> None:
    """Enforce the Course lifecycle on generic session metadata writes."""
    course_id = str((session or {}).get("course_id") or "").strip()
    if not course_id:
        return

    from deeptutor.courses.repository import CourseNotFoundError
    from deeptutor.courses.service import CourseUnavailableError, get_current_course_service

    try:
        course = get_current_course_service().get(course_id)
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except CourseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if course.state != "active":
        raise HTTPException(status_code=409, detail="Archived Course sessions are read-only")


class SessionRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)


class BranchSelectionRequest(BaseModel):
    """Edit-branch picker state: `{parent_message_id: chosen_child_id}`.

    Stored inside the session preferences blob so it survives reloads
    without a dedicated column.
    """

    selected_branches: dict[str, int] = Field(default_factory=dict)


class QuizResultItem(BaseModel):
    question_id: str = Field(default="", max_length=100)
    question: str = Field(..., min_length=1, max_length=50_000)
    question_type: str = Field(default="", max_length=100)
    options: dict[str, str] | None = Field(default=None, max_length=100)
    user_answer: str = Field(default="", max_length=20_000)
    correct_answer: str = Field(default="", max_length=20_000)
    explanation: str | None = Field(default="", max_length=20_000)
    difficulty: str | None = Field(default="", max_length=100)
    is_correct: bool

    @field_validator("options", mode="before")
    @classmethod
    def _coerce_options(cls, v):
        return v if isinstance(v, dict) else {}

    @field_validator("explanation", "difficulty", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        return v if isinstance(v, str) else ""

    @field_validator("options")
    @classmethod
    def option_text_is_bounded(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None and any(
            len(key) > 100 or len(text) > 2_000 for key, text in value.items()
        ):
            raise ValueError("quiz options are too large")
        return value


class QuizResultsRequest(BaseModel):
    answers: list[QuizResultItem] = Field(default_factory=list, max_length=100)
    turn_id: str = Field(default="", max_length=100)


def _format_quiz_results_message(answers: list[QuizResultItem]) -> str:
    total = len(answers)
    correct = sum(1 for item in answers if item.is_correct)
    score_pct = round((correct / total) * 100) if total else 0
    lines = ["[Quiz Performance]"]
    for idx, item in enumerate(answers, 1):
        question = item.question.strip().replace("\n", " ")
        user_answer = (item.user_answer or "").strip() or "(blank)"
        status = "Correct" if item.is_correct else "Incorrect"
        suffix = f" ({status})"
        if not item.is_correct and (item.correct_answer or "").strip():
            suffix = f" ({status}, correct: {(item.correct_answer or '').strip()})"
        qid = f"[{item.question_id}] " if item.question_id else ""
        lines.append(f"{idx}. {qid}Q: {question} -> Answered: {user_answer}{suffix}")
    lines.append(f"Score: {correct}/{total} ({score_pct}%)")
    return "\n".join(lines)


@router.get("")
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    fetched: list[dict[str, Any]] = []
    for store in _distinct_session_stores():
        fetched.extend(await store.list_sessions(limit=limit + offset, offset=0))
    deduped = {str(item.get("session_id") or item.get("id")): item for item in fetched}
    sessions = sorted(
        deduped.values(), key=lambda item: float(item.get("updated_at") or 0), reverse=True
    )
    return {"sessions": sessions[offset : offset + limit]}


# Cap (in characters) for a single event payload returned to the UI. RAG
# tools can attach whole KB documents to ``tool_result``/``observation``
# events; the frontend TraceSurface only needs a preview, and the LLM context
# is built from a separate content-only store, so capping here never affects
# model input.
MAX_EVENT_PAYLOAD = 1024 * 1024
_TRUNCATION_NOTICE = "\n\n[... content truncated]"
_TRUNCATABLE_EVENT_TYPES = ("tool_result", "observation")


def _truncate_oversized_events(
    messages: list[dict[str, Any]], limit: int = MAX_EVENT_PAYLOAD
) -> None:
    """Cap oversized ``tool_result``/``observation`` payloads in place.

    The session store already returns each message's events as a parsed
    ``events`` list (see ``SqliteSessionStore._serialize_message``), so we
    mutate that list directly. Only the UI rendering path is affected.
    """

    def _cap(container: dict[str, Any], field: str) -> bool:
        value = container.get(field)
        if isinstance(value, str) and len(value) > limit:
            container[field] = value[:limit] + _TRUNCATION_NOTICE
            return True
        return False

    for msg in messages:
        events = msg.get("events")
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict) or event.get("type") not in _TRUNCATABLE_EVENT_TYPES:
                continue
            truncated = _cap(event, "content")
            tool_metadata = (event.get("metadata") or {}).get("tool_metadata")
            if isinstance(tool_metadata, dict):
                for field in ("content", "answer"):
                    truncated = _cap(tool_metadata, field) or truncated
            if truncated:
                event["_truncated"] = True


@router.get("/{session_id}")
async def get_session(session_id: str):
    store = await _owned_session_store(session_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session = await store.get_session_with_messages(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _truncate_oversized_events(session.get("messages", []))
    return session


@router.patch("/{session_id}")
async def rename_session(session_id: str, payload: SessionRenameRequest):
    store = await _owned_session_store(session_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    course_id = str(session.get("course_id") or "").strip()
    if course_id:
        from deeptutor.courses.service import course_operation_lock

        async with course_operation_lock(course_id):
            session = await store.get_session(session_id)
            _assert_course_session_write_allowed(session)
            updated = await store.update_session_title(session_id, payload.title)
    else:
        updated = await store.update_session_title(session_id, payload.title)
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    session = await store.get_session(session_id)
    return {"session": session}


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    store = await _owned_session_store(session_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session = await store.get_session(session_id)
    if session and session.get("course_id"):
        raise HTTPException(status_code=409, detail="Course sessions are retained")
    deleted = await store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        await get_attachment_store().delete_session(session_id)
    except Exception:
        logger.exception("failed to clean up attachments for session %s", session_id)
    return {"deleted": True, "session_id": session_id}


@router.put("/{session_id}/branch-selection")
async def update_branch_selection(session_id: str, payload: BranchSelectionRequest):
    store = await _owned_session_store(session_id, sqlite_only=True)
    if store is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    course_id = str(session.get("course_id") or "").strip()
    if course_id:
        from deeptutor.courses.service import course_operation_lock

        async with course_operation_lock(course_id):
            session = await store.get_session(session_id)
            _assert_course_session_write_allowed(session)
            updated = await store.update_session_preferences(
                session_id, {"selected_branches": dict(payload.selected_branches)}
            )
    else:
        updated = await store.update_session_preferences(
            session_id, {"selected_branches": dict(payload.selected_branches)}
        )
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"selected_branches": payload.selected_branches}


@router.delete("/{session_id}/messages/{message_id}")
async def delete_turn_by_message(session_id: str, message_id: int):
    store = await _owned_session_store(session_id, sqlite_only=True)
    if store is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session = await store.get_session(session_id)
    if session and session.get("course_id"):
        raise HTTPException(status_code=409, detail="Course messages are retained")
    result = await store.delete_turn_by_message(session_id, message_id)
    if result["was_running"]:
        raise HTTPException(
            status_code=409, detail="Cannot delete a message while its turn is running"
        )
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail="Message not found")
    attachment_store = get_attachment_store()
    for aid in result["attachment_ids"]:
        try:
            await attachment_store.delete_attachment(session_id, aid)
        except Exception:
            logger.exception("failed to delete attachment %s for session %s", aid, session_id)
    return result


@router.post("/{session_id}/quiz-results")
async def record_quiz_results(session_id: str, payload: QuizResultsRequest):
    if not payload.answers:
        raise HTTPException(status_code=400, detail="Quiz results are required")
    store = await _owned_session_store(session_id, sqlite_only=True)
    if store is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("course_id"):
        raise HTTPException(status_code=409, detail="Quiz results are unavailable in Course mode")
    content = _format_quiz_results_message(payload.answers)
    await store.add_message(
        session_id=session_id,
        role="user",
        content=content,
        capability="deep_question",
    )
    notebook_count = 0
    try:
        notebook_count = await store.upsert_notebook_entries(
            session_id,
            [{**item.model_dump(), "turn_id": payload.turn_id} for item in payload.answers],
        )
    except Exception:
        logger.warning(
            "Failed to upsert notebook entries for session %s", session_id, exc_info=True
        )
    return {
        "recorded": True,
        "session_id": session_id,
        "answer_count": len(payload.answers),
        "notebook_count": notebook_count,
        "content": content,
    }
