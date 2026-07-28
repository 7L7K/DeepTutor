"""Typed records for durable Course-owned quiz attempts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

QuizAttemptState = Literal["in_progress", "submitted", "graded", "abandoned", "archived"]


class QuizAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    owner_user_id: str
    course_id: str
    practice_set_id: str
    practice_set_revision_id: str
    state: QuizAttemptState
    score: dict[str, Any] | None = None
    revision: int = Field(ge=1)
    course_write_epoch: int = Field(ge=1)
    practice_set_write_epoch: int = Field(ge=1)
    started_at: float
    submitted_at: float | None = None
    graded_at: float | None = None
    archived_at: float | None = None
    updated_at: float


class QuizAttemptItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    attempt_id: str
    question_id: str
    display_ordinal: int = Field(ge=1)
    option_order: list[str] | None = None
    randomized_values: dict[str, Any] | None = None
    grading: dict[str, Any] | None = None
    error_type: str | None = None
    graded_at: float | None = None


class QuizAttemptAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_item_id: str
    response: Any | None = None
    revision: int = Field(ge=1)
    answered_at: float | None = None


class QuizAttemptView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt: QuizAttempt
    items: list[QuizAttemptItem]
    answers: list[QuizAttemptAnswer]


class AttemptItemPresentation(BaseModel):
    """Frozen client presentation choices for one revision question."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    display_ordinal: int = Field(ge=1)
    option_order: list[str] | None = None
    randomized_values: dict[str, Any] | None = None
