"""Strict records for source-grounded Flashcard generation.

These are intentionally distinct from Practice generation records: a generated
deck has no answer contract or grading semantics and can never mutate mastery.
Only opaque source receipts, not retrieved text or provider payloads, persist.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

GenerationState = Literal["queued", "running", "completed", "failed"]
GenerationErrorCode = Literal[
    "provider_unavailable",
    "provider_failed",
    "invalid_output",
    "source_changed",
    "authority_changed",
    "interrupted",
    "provider_timed_out",
]


class FlashcardSourceReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_revision: int = Field(ge=1)
    content_sha256: str

    @field_validator("source_id")
    @classmethod
    def opaque_source_id(cls, value: str) -> str:
        if not value.startswith("src_") or len(value) > 80:
            raise ValueError("source_id must be an opaque Course source ID")
        return value

    @field_validator("content_sha256")
    @classmethod
    def sha256(cls, value: str) -> str:
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
        return value


class FlashcardCitation(FlashcardSourceReceipt):
    locator: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("locator")
    @classmethod
    def bounded_locator(
        cls, value: dict[str, str | int | float | bool | None]
    ) -> dict[str, str | int | float | bool | None]:
        if len(value) > 16 or any(not key or len(key) > 80 for key in value):
            raise ValueError("citation locator is invalid")
        if any(isinstance(item, str) and len(item) > 500 for item in value.values()):
            raise ValueError("citation locator is invalid")
        return value


class FlashcardGenerationOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    owner_user_id: str
    course_id: str
    deck_id: str
    supersedes_deck_id: str | None = None
    idempotency_key: str
    request_fingerprint: str
    source_snapshot: list[FlashcardSourceReceipt]
    objective_ids: list[str] = Field(default_factory=list)
    course_write_epoch: int = Field(ge=1)
    deck_write_epoch: int = Field(ge=1)
    item_limit: int = Field(ge=1, le=48)
    context_char_limit: int = Field(ge=1, le=48_000)
    state: GenerationState
    error_code: GenerationErrorCode | None = None
    created_at: float
    started_at: float | None = None
    completed_at: float | None = None
    updated_at: float

    @field_validator("id")
    @classmethod
    def opaque_operation_id(cls, value: str) -> str:
        if not value.startswith("ofg_") or len(value) > 80:
            raise ValueError("generation operation ID must be opaque")
        return value

    @field_validator("request_fingerprint")
    @classmethod
    def fingerprint(cls, value: str) -> str:
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("request_fingerprint must be a SHA-256 digest")
        return value


class GeneratedFlashcard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=12_000)
    answer: str = Field(min_length=1, max_length=12_000)
    objective_ids: list[str] = Field(default_factory=list, max_length=64)
    citations: list[FlashcardCitation] = Field(min_length=1, max_length=32)


class GeneratedFlashcardOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cards: list[GeneratedFlashcard] = Field(min_length=1, max_length=48)
    provider_label: Literal["deterministic-local"]


class FlashcardGenerationSourceText(BaseModel):
    """Ephemeral untrusted Course material. It is never written to SQLite."""

    model_config = ConfigDict(extra="forbid")
    receipt: FlashcardSourceReceipt
    text: str = Field(min_length=1, max_length=12_000)


class FlashcardGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    course_id: str
    deck_id: str
    source_material: list[FlashcardGenerationSourceText] = Field(min_length=1, max_length=64)
    objective_ids: list[str] = Field(default_factory=list, max_length=64)
    item_limit: int = Field(ge=1, le=48)
    context_char_limit: int = Field(ge=1, le=48_000)


class FlashcardGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deck_id: str
    operation: FlashcardGenerationOperation
