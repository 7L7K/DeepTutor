"""Strict, provider-neutral records for grounded Practice generation.

Only opaque source receipts are durable.  Retrieved Course text is an
ephemeral, untrusted input to the provider adapter and is never persisted in a
generation operation or receipt.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .practice_models import ExactAnswerContract, PracticeCitation, PracticeSourceReceipt

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


class PracticeGenerationOperation(BaseModel):
    """Durable operation state with no prompt, source text, or provider error."""

    model_config = ConfigDict(extra="forbid")

    id: str
    owner_user_id: str
    course_id: str
    practice_set_id: str
    practice_set_revision_id: str
    idempotency_key: str
    request_fingerprint: str
    source_snapshot: list[PracticeSourceReceipt]
    objective_ids: list[str] = Field(default_factory=list)
    course_write_epoch: int = Field(ge=1)
    practice_set_write_epoch: int = Field(ge=1)
    item_limit: int = Field(ge=1, le=12)
    context_char_limit: int = Field(ge=1, le=48_000)
    state: GenerationState
    error_code: GenerationErrorCode | None = None
    created_at: float
    started_at: float | None = None
    completed_at: float | None = None
    updated_at: float

    @field_validator("id")
    @classmethod
    def _opaque_operation_id(cls, value: str) -> str:
        if not value.startswith("opg_") or len(value) > 80:
            raise ValueError("generation operation ID must be opaque")
        return value

    @field_validator("request_fingerprint")
    @classmethod
    def _fingerprint(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("request_fingerprint must be a SHA-256 digest")
        return value


class GeneratedPracticeQuestion(BaseModel):
    """The only structured output accepted from a Practice generator."""

    model_config = ConfigDict(extra="forbid")

    question_type: str
    prompt: str
    answer_contract: ExactAnswerContract
    explanation: str = ""
    objective_ids: list[str] = Field(default_factory=list)
    citations: list[PracticeCitation]

    @field_validator("question_type")
    @classmethod
    def _question_type(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value or len(value) > 80:
            raise ValueError("question_type must be non-empty and bounded")
        return value

    @field_validator("prompt", "explanation")
    @classmethod
    def _text(cls, value: str) -> str:
        if len(value) > 12_000:
            raise ValueError("generated text is too long")
        return value


class GeneratedPracticeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[GeneratedPracticeQuestion] = Field(min_length=1, max_length=12)
    provider_label: Literal["deterministic-local"]


class GenerationSourceText(BaseModel):
    """Ephemeral text resolved from an exact source receipt.

    ``text`` is Course material, not a system instruction, tool request, or
    authority.  It must never be written into SQLite operation rows.
    """

    model_config = ConfigDict(extra="forbid")

    receipt: PracticeSourceReceipt
    text: str = Field(min_length=1, max_length=12_000)


class PracticeGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    course_id: str
    practice_set_id: str
    practice_set_revision_id: str
    source_material: list[GenerationSourceText] = Field(min_length=1, max_length=64)
    objective_ids: list[str] = Field(default_factory=list, max_length=64)
    item_limit: int = Field(ge=1, le=12)
    context_char_limit: int = Field(ge=1, le=48_000)


class PracticeGenerationRequest(BaseModel):
    """The atomic creation result exposed to an API adapter."""

    model_config = ConfigDict(extra="forbid")

    practice_set_id: str
    practice_set_revision_id: str
    operation: PracticeGenerationOperation
