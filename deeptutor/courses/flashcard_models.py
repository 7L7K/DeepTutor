"""Typed, bounded records for Course-owned Flashcards and review history."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FlashcardDeckMode = Literal["manual", "generated"]
FlashcardDeckState = Literal["draft", "ready", "archived"]
FlashcardState = Literal["active", "archived"]
FlashcardRating = Literal["again", "hard", "good", "easy"]


class FlashcardDeck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    owner_user_id: str
    course_id: str
    title: str
    mode: FlashcardDeckMode
    state: FlashcardDeckState
    source_snapshot: list[dict] = Field(default_factory=list)
    generation_receipt: dict | None = None
    supersedes_deck_id: str | None = None
    revision: int = Field(ge=1)
    write_epoch: int = Field(ge=1)
    created_at: float
    updated_at: float
    ready_at: float | None = None
    archived_at: float | None = None


class Flashcard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    deck_id: str
    prompt: str
    answer: str
    hint: str | None = None
    card_type: Literal[
        "definition", "concept", "comparison", "application", "process", "recall"
    ] = "recall"
    objective_ids: list[str] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)
    ordinal: int = Field(ge=1)
    revision: int = Field(ge=1)
    state: FlashcardState
    created_at: float
    updated_at: float
    archived_at: float | None = None


class FlashcardReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    owner_user_id: str
    course_id: str
    deck_id: str
    card_id: str
    rating: FlashcardRating
    idempotency_key: str
    course_write_epoch: int = Field(ge=1)
    deck_revision: int = Field(ge=1)
    card_revision: int = Field(ge=1)
    review_count: int = Field(ge=1)
    interval_seconds: int = Field(ge=1)
    was_due: bool
    reviewed_at: float
    next_review_at: float

    @field_validator("idempotency_key")
    @classmethod
    def _idempotency_key_is_bounded(cls, value: str) -> str:
        if not value or len(value) > 160:
            raise ValueError("idempotency_key must be non-empty and bounded")
        return value


class FlashcardSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: str
    review_count: int = Field(ge=0)
    interval_seconds: int = Field(ge=0)
    next_review_at: float
    last_review_id: str | None = None


class FlashcardReviewSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: float
    total_active_cards: int = Field(ge=0)
    due_cards: int = Field(ge=0)
    completed_cards: int = Field(ge=0)
    review_count: int = Field(ge=0)


class FlashcardDeckView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deck: FlashcardDeck
    cards: list[Flashcard]
    schedules: list[FlashcardSchedule]
    review_summary: FlashcardReviewSummary
