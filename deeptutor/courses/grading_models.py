"""Immutable deterministic grading receipts for Course quiz attempts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class GradingEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    owner_user_id: str
    course_id: str
    practice_set_id: str
    attempt_id: str
    attempt_item_id: str
    question_id: str
    objective_id: str
    module_id: str | None = None
    knowledge_type: str | None = None
    algorithm: Literal["exact-v1"]
    payload_sha256: str
    is_correct: bool
    grading: dict[str, Any]
    error_type: str | None = None
    state: Literal["pending", "applied", "unmapped"]
    created_at: float
    applied_at: float | None = None
    response: Any | None = None


__all__ = ["GradingEvidence"]
