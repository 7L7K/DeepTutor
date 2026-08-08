"""Strict records for source-grounded Flashcard generation.

These are intentionally distinct from Practice generation records: a generated
deck has no answer contract or grading semantics and can never mutate mastery.
Only opaque source receipts, not retrieved text or provider payloads, persist.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

CardType = Literal["definition", "concept", "comparison", "application", "process", "recall"]
GenerationState = Literal[
    "queued",
    "running",
    "awaiting_review",
    "completed",
    "failed",
    "cancelling",
    "cancelled",
]
GenerationErrorCode = Literal[
    "provider_unavailable",
    "provider_failed",
    "invalid_output",
    "source_changed",
    "authority_changed",
    "interrupted",
    "provider_timed_out",
    "configuration_error",
    "quota_exceeded",
    "insufficient_valid_cards",
    "cancelled",
]


class FlashcardGenerationBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focus: str = Field(min_length=1, max_length=1000)
    desired_count: int = Field(ge=1, le=48)
    card_type_mix: list[CardType] = Field(min_length=1, max_length=6)
    difficulty: Literal["introductory", "intermediate", "advanced", "mixed"] = "mixed"
    answer_length: Literal["short", "medium"] = "short"
    include_hints: bool = True

    @field_validator("card_type_mix")
    @classmethod
    def unique_card_types(cls, value: list[CardType]) -> list[CardType]:
        if len(value) != len(set(value)):
            raise ValueError("card_type_mix must be unique")
        return value


class FlashcardGenerationOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["workspace", "chat", "practice_remediation", "general_chat"]
    session_id: str | None = Field(default=None, max_length=160)
    message_id: int | None = Field(default=None, ge=1)
    practice_attempt_id: str | None = Field(default=None, max_length=80)
    practice_set_id: str | None = Field(default=None, max_length=80)
    practice_set_revision_id: str | None = Field(default=None, max_length=80)
    practice_question_ids: list[str] = Field(default_factory=list, max_length=64)
    grading_evidence_ids: list[str] = Field(default_factory=list, max_length=128)
    selected_message_ids: list[int] = Field(default_factory=list, max_length=32)
    context_sha256: str | None = Field(default=None, max_length=64)
    context_summary: str | None = Field(default=None, max_length=160)
    context_title: str | None = Field(default=None, max_length=120)
    context_topics: list[str] = Field(default_factory=list, max_length=6)
    session_scope: Literal["personal", "admin"] | None = None

    @field_validator("selected_message_ids")
    @classmethod
    def unique_message_ids(cls, value: list[int]) -> list[int]:
        if any(item < 1 for item in value) or len(value) != len(set(value)):
            raise ValueError("selected_message_ids are invalid")
        return value

    @field_validator("context_topics")
    @classmethod
    def valid_context_topics(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if (
            any(not item or len(item) > 80 for item in cleaned)
            or len(cleaned) != len({item.casefold() for item in cleaned})
        ):
            raise ValueError("context_topics are invalid")
        return cleaned

    @field_validator("context_sha256")
    @classmethod
    def context_digest(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("context_sha256 must be a SHA-256 digest")
        return value

    @field_validator(
        "practice_attempt_id",
        "practice_set_id",
        "practice_set_revision_id",
    )
    @classmethod
    def opaque_practice_ids(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or len(value) > 80):
            raise ValueError("Practice provenance IDs are invalid")
        return value

    @field_validator("practice_question_ids", "grading_evidence_ids")
    @classmethod
    def unique_practice_ids(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 80 for item in value):
            raise ValueError("Practice provenance IDs are invalid")
        if len(value) != len(set(value)):
            raise ValueError("Practice provenance IDs must be unique")
        return value

    @model_validator(mode="after")
    def provenance_matches_kind(self) -> "FlashcardGenerationOrigin":
        if self.kind == "general_chat":
            if (
                not self.session_id
                or self.message_id is None
                or len(self.selected_message_ids) < 2
                or not self.context_sha256
                or not (self.context_summary or "").strip()
                or self.practice_attempt_id is not None
            ):
                raise ValueError("General Chat provenance is incomplete")
        elif (
            self.selected_message_ids
            or self.context_sha256 is not None
            or self.context_summary is not None
            or self.context_title is not None
            or self.context_topics
            or self.session_scope is not None
        ):
            raise ValueError(
                "Conversation context provenance is reserved for General Chat"
            )
        return self

    @model_serializer(mode="wrap")
    def serialize_origin(self, handler: SerializerFunctionWrapHandler):
        payload = handler(self)
        if self.practice_set_id is None:
            for key in (
                "practice_set_id",
                "practice_set_revision_id",
                "practice_question_ids",
                "grading_evidence_ids",
            ):
                payload.pop(key, None)
        if self.kind != "general_chat":
            for key in ("context_title", "context_topics", "session_scope"):
                payload.pop(key, None)
        return payload


class FlashcardProviderReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["deterministic-local", "openai"]
    requested_model: str = Field(min_length=1, max_length=160)
    actual_model: str = Field(min_length=1, max_length=160)
    request_id: str | None = Field(default=None, max_length=200)
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_microusd: int | None = Field(default=None, ge=0)
    pricing_version: str = Field(default="provider-free", min_length=1, max_length=80)
    response_status: str | None = Field(default=None, max_length=80)
    service_tier: str | None = Field(default=None, max_length=80)
    prompt_version: str = Field(
        default="course-flashcards-v2", min_length=1, max_length=80
    )
    schema_version: str = Field(
        default="course-flashcards-schema-v2", min_length=1, max_length=80
    )
    reasoning_effort: str = Field(default="none", min_length=1, max_length=40)
    store: Literal[False] = False
    latency_ms: int | None = Field(default=None, ge=0)
    returned_count: int = Field(ge=0, le=48)
    valid_count: int = Field(ge=0, le=48)
    generated_at: float


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
    generation_brief: FlashcardGenerationBrief
    origin: FlashcardGenerationOrigin
    candidates: list["FlashcardCandidate"] | None = None
    candidate_revision: int = Field(default=0, ge=0)
    provider_receipt: FlashcardProviderReceipt | None = None
    provider_invoked_at: float | None = None
    cancel_requested_at: float | None = None
    review_expires_at: float | None = None
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
    hint: str | None = Field(default=None, max_length=2_000)
    card_type: CardType = "recall"
    objective_ids: list[str] = Field(default_factory=list, max_length=64)
    citations: list[FlashcardCitation] = Field(default_factory=list, max_length=3)


class FlashcardCandidate(GeneratedFlashcard):
    candidate_id: str

    @field_validator("candidate_id")
    @classmethod
    def opaque_candidate_id(cls, value: str) -> str:
        if not value.startswith("fcd_") or len(value) > 80:
            raise ValueError("candidate_id must be opaque")
        return value


class GeneratedFlashcardOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cards: list[GeneratedFlashcard] = Field(min_length=1, max_length=48)
    provider_label: Literal["deterministic-local", "openai"]
    requested_model: str = Field(default="deterministic-local", min_length=1, max_length=160)
    actual_model: str = Field(default="deterministic-local", min_length=1, max_length=160)
    request_id: str | None = Field(default=None, max_length=200)
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_microusd: int | None = Field(default=None, ge=0)
    pricing_version: str = Field(default="provider-free", min_length=1, max_length=80)
    response_status: str | None = Field(default=None, max_length=80)
    service_tier: str | None = Field(default=None, max_length=80)
    prompt_version: str = Field(
        default="course-flashcards-v2", min_length=1, max_length=80
    )
    schema_version: str = Field(
        default="course-flashcards-schema-v2", min_length=1, max_length=80
    )
    reasoning_effort: str = Field(default="none", min_length=1, max_length=40)
    store: Literal[False] = False
    latency_ms: int | None = Field(default=None, ge=0)
    generated_at: float = Field(default_factory=time.time)


class FlashcardGenerationSourceText(BaseModel):
    """Ephemeral untrusted Course material. It is never written to SQLite."""

    model_config = ConfigDict(extra="forbid")
    receipt: FlashcardSourceReceipt
    text: str = Field(min_length=1, max_length=12_000)


class FlashcardGenerationConversationText(BaseModel):
    """Ephemeral owner-scoped conversation context, never persisted as text."""

    model_config = ConfigDict(extra="forbid")
    selected_message_ids: list[int] = Field(min_length=2, max_length=32)
    context_sha256: str = Field(min_length=64, max_length=64)
    text: str = Field(min_length=1, max_length=12_000)


class FlashcardGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    owner_user_id: str = Field(min_length=1, max_length=160)
    course_id: str
    deck_id: str
    origin: FlashcardGenerationOrigin
    source_material: list[FlashcardGenerationSourceText] = Field(
        default_factory=list, max_length=64
    )
    conversation_context: FlashcardGenerationConversationText | None = None
    objective_ids: list[str] = Field(default_factory=list, max_length=64)
    generation_brief: FlashcardGenerationBrief
    item_limit: int = Field(ge=1, le=48)
    context_char_limit: int = Field(ge=1, le=48_000)


class FlashcardGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deck_id: str
    operation: FlashcardGenerationOperation


class FlashcardGenerationBriefReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    course_write_epoch: int = Field(ge=1)
    brief: FlashcardGenerationBrief
    source_snapshot: list[FlashcardSourceReceipt] = Field(default_factory=list, max_length=64)
    objective_ids: list[str] = Field(default_factory=list, max_length=64)
    origin: FlashcardGenerationOrigin
    provider_available: bool
    warnings: list[str] = Field(default_factory=list, max_length=8)


class FlashcardCandidatePublication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_ids: list[str] = Field(min_length=1, max_length=48)
    expected_candidate_revision: int = Field(ge=1)

    @field_validator("candidate_ids")
    @classmethod
    def unique_candidates(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("candidate_ids must be unique")
        if any(not item.startswith("fcd_") or len(item) > 80 for item in value):
            raise ValueError("candidate_ids must be opaque")
        return value
