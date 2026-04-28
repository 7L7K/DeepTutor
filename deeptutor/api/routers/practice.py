"""
Practice mode API.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from deeptutor.api.routers.access import get_current_tester
from deeptutor.services.session import get_sqlite_session_store

router = APIRouter()


class PracticeAttemptCreateRequest(BaseModel):
    session_id: str | None = None
    source_type: str = "practice"
    source_session_id: str | None = None
    source_message_id: int | None = None
    title: str = Field(default="Practice Quiz", min_length=1, max_length=100)
    topic: str = ""
    knowledge_base: str = ""
    mode: str = "untimed"
    status: str = "in_progress"
    time_limit_seconds: float | None = None
    quiz_snapshot: dict[str, Any] = Field(default_factory=dict)

    @field_validator("quiz_snapshot", mode="before")
    @classmethod
    def _coerce_snapshot(cls, value):
        return value if isinstance(value, dict) else {}


class PracticeAttemptResultSaveRequest(BaseModel):
    submitted_at: float | None = None
    duration_seconds: float | None = None
    timed_out: bool = False
    structured_result: dict[str, Any] = Field(default_factory=dict)

    @field_validator("structured_result", mode="before")
    @classmethod
    def _coerce_result(cls, value):
        return value if isinstance(value, dict) else {}


@router.post("/attempts")
async def create_attempt(payload: PracticeAttemptCreateRequest, tester: dict = Depends(get_current_tester)):
    store = get_sqlite_session_store()
    try:
        data = payload.model_dump()
        data["tester_id"] = tester["id"]
        attempt = await store.create_quiz_attempt(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"attempt": attempt}


@router.get("/attempts/{attempt_id}")
async def get_attempt(attempt_id: str, tester: dict = Depends(get_current_tester)):
    store = get_sqlite_session_store()
    attempt = await store.get_quiz_attempt(attempt_id, tester_id=tester["id"])
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    attempt["items"] = await store.get_quiz_attempt_items(attempt_id, tester_id=tester["id"])
    return {"attempt": attempt}


@router.post("/attempts/{attempt_id}/results")
async def save_attempt_results(
    attempt_id: str,
    payload: PracticeAttemptResultSaveRequest,
    tester: dict = Depends(get_current_tester),
):
    store = get_sqlite_session_store()
    try:
        attempt = await store.save_quiz_attempt_results(attempt_id, payload.model_dump(), tester_id=tester["id"])
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    return {"attempt": attempt}


@router.get("/attempts")
async def list_attempts(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session_id: str | None = Query(default=None),
    source_session_id: str | None = Query(default=None),
    tester: dict = Depends(get_current_tester),
):
    store = get_sqlite_session_store()
    attempts = await store.list_quiz_attempts(
        limit=limit,
        offset=offset,
        session_id=session_id,
        source_session_id=source_session_id,
        tester_id=tester["id"],
    )
    return {"attempts": attempts}


@router.get("/progress")
async def get_progress(
    recent_attempt_window: int = Query(default=10, ge=1, le=50),
    tester: dict = Depends(get_current_tester),
):
    store = get_sqlite_session_store()
    domains = await store.get_domain_progress_summary(
        recent_attempt_window=recent_attempt_window,
        tester_id=tester["id"],
    )
    return {"domains": domains, "recent_attempt_window": recent_attempt_window}
