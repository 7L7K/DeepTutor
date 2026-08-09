"""Strict, provider-neutral records for grounded Practice generation.

Only opaque source receipts are durable.  Retrieved Course text is an
ephemeral, untrusted input to the provider adapter and is never persisted in a
generation operation or receipt.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .practice_models import ExactAnswerContract, PracticeCitation, PracticeSourceReceipt

GenerationState = Literal["queued", "running", "completed", "failed"]
PracticePlanState = Literal["draft", "confirmed", "expired"]
PracticeDifficulty = Literal["foundation", "mixed", "challenge"]
PracticeTimingMode = Literal["untimed", "practice_timer"]
PracticePlanOriginKind = Literal["practice", "course_chat"]
PracticeQualityProfile = Literal["baseline-v1", "c3-biology-v1"]
PracticeGenerationPurpose = Literal["practice", "remediation"]
PracticeGenerationOutcome = Literal["generated", "abstain"]
PracticeGenerationAbstainReason = Literal["unsupported_by_allowed_sources"]
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
    focus: str = Field(min_length=1, max_length=4_000)
    difficulty: PracticeDifficulty
    timing_mode: PracticeTimingMode
    quality_profile: PracticeQualityProfile = "baseline-v1"
    state: GenerationState
    error_code: GenerationErrorCode | None = None
    created_at: float
    started_at: float | None = None
    completed_at: float | None = None
    cancel_requested_at: float | None = None
    cancelled_at: float | None = None
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


class PracticeGenerationPlanOrigin(BaseModel):
    """Non-authoritative provenance for the learner entry point."""

    model_config = ConfigDict(extra="forbid")

    kind: PracticePlanOriginKind
    session_id: str | None = Field(default=None, max_length=160)
    assistant_message_id: int | None = Field(default=None, ge=1)
    citation_anchors: list["CourseChatCitationAnchor"] = Field(
        default_factory=list, max_length=32
    )

    @field_validator("session_id")
    @classmethod
    def _session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("session_id must be non-empty")
        return cleaned

    @field_validator("citation_anchors")
    @classmethod
    def _citation_anchors_are_unique(
        cls, value: list["CourseChatCitationAnchor"]
    ) -> list["CourseChatCitationAnchor"]:
        identities = [
            (item.course_id, item.source_id, item.source_revision, item.source_content_hash)
            for item in value
        ]
        if len(set(identities)) != len(identities):
            raise ValueError("citation_anchors must not contain duplicate source versions")
        return value


class CourseChatCitationAnchor(BaseModel):
    """Validated, text-free provenance copied from one persisted Course turn."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    course_id: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=5, max_length=80)
    source_revision: int = Field(ge=1)
    source_content_hash: str = Field(min_length=64, max_length=64)
    source_title_snapshot: str = Field(min_length=1, max_length=500)
    locator_type: str | None = Field(default=None, max_length=80)
    locator_value: str | None = Field(default=None, max_length=500)
    retrieval_fragment_id: str | None = Field(default=None, max_length=160)

    @field_validator("course_id")
    @classmethod
    def _course_id_is_opaque(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("course_id must be non-empty")
        return value

    @field_validator("source_id")
    @classmethod
    def _source_id_is_opaque(cls, value: str) -> str:
        if not value.startswith("src_"):
            raise ValueError("source_id must be an opaque Course source ID")
        return value

    @field_validator("source_content_hash")
    @classmethod
    def _source_hash_is_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("source_content_hash must be a lowercase SHA-256 digest")
        return value

    @field_validator("source_title_snapshot", "locator_type", "locator_value", "retrieval_fragment_id")
    @classmethod
    def _bounded_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None


class PracticeGenerationPlan(BaseModel):
    """Editable provider-free plan that freezes private Course authority."""

    model_config = ConfigDict(extra="forbid")

    id: str
    owner_user_id: str
    course_id: str
    title: str
    focus: str
    source_snapshot: list[PracticeSourceReceipt] = Field(min_length=1, max_length=64)
    objective_ids: list[str] = Field(default_factory=list, max_length=64)
    item_limit: int = Field(ge=1, le=12)
    difficulty: PracticeDifficulty
    timing_mode: PracticeTimingMode
    quality_profile: PracticeQualityProfile = "baseline-v1"
    origin: PracticeGenerationPlanOrigin
    course_write_epoch: int = Field(ge=1)
    revision: int = Field(ge=1)
    state: PracticePlanState
    confirmed_operation_id: str | None = None
    created_at: float
    updated_at: float
    confirmed_at: float | None = None

    @field_validator("id")
    @classmethod
    def _opaque_plan_id(cls, value: str) -> str:
        if not value.startswith("pln_") or len(value) > 80:
            raise ValueError("generation plan ID must be opaque")
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


class PracticeGenerationRequestContract(BaseModel):
    """Deterministic scope receipt echoed by every C3 provider result."""

    model_config = ConfigDict(extra="forbid")

    request_contract_id: str = Field(min_length=5, max_length=80)
    requested_objective_ids: list[str] = Field(min_length=1, max_length=64)
    source_scope_hash: str = Field(min_length=64, max_length=64)
    generation_purpose: PracticeGenerationPurpose

    @field_validator("request_contract_id")
    @classmethod
    def _opaque_contract_id(cls, value: str) -> str:
        if not value.startswith("pgc_"):
            raise ValueError("request_contract_id must be opaque")
        return value

    @field_validator("requested_objective_ids")
    @classmethod
    def _unique_requested_objectives(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(not item.strip() for item in value):
            raise ValueError("requested objective IDs must be unique and non-empty")
        return value

    @field_validator("source_scope_hash")
    @classmethod
    def _source_scope_digest(cls, value: str) -> str:
        if any(char not in "0123456789abcdef" for char in value):
            raise ValueError("source_scope_hash must be a SHA-256 digest")
        return value


class GeneratedPracticeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[GeneratedPracticeQuestion] = Field(default_factory=list, max_length=12)
    provider_label: Literal["deterministic-local", "openai", "policy-local"]
    request_contract: PracticeGenerationRequestContract | None = None
    outcome: PracticeGenerationOutcome = "generated"
    abstain_reason: PracticeGenerationAbstainReason | None = None
    requested_model: str | None = Field(default=None, max_length=120)
    actual_model: str | None = Field(default=None, max_length=120)
    request_id: str | None = Field(default=None, max_length=160)
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_microusd: int | None = Field(default=None, ge=0)
    pricing_version: str = Field(default="provider-free", min_length=1, max_length=80)
    prompt_version: str = Field(default="course-practice-v1", min_length=1, max_length=80)
    schema_version: str = Field(default="course-practice-schema-v1", min_length=1, max_length=80)
    reasoning_effort: str = Field(default="none", min_length=1, max_length=40)
    store: Literal[False] = False
    response_status: str | None = Field(default=None, max_length=80)
    latency_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _outcome_shape(self) -> "GeneratedPracticeOutput":
        if self.outcome == "generated":
            if not self.questions or self.abstain_reason is not None:
                raise ValueError("generated output requires questions and no abstain reason")
            if self.provider_label == "policy-local":
                raise ValueError("policy-local output cannot publish generated questions")
        elif self.questions or self.abstain_reason is None or self.request_contract is None:
            raise ValueError("abstention requires an empty question set, reason, and request contract")
        return self


class GenerationSourceText(BaseModel):
    """Ephemeral text resolved from an exact source receipt.

    ``text`` is Course material, not a system instruction, tool request, or
    authority.  It must never be written into SQLite operation rows.
    """

    model_config = ConfigDict(extra="forbid")

    receipt: PracticeSourceReceipt
    text: str = Field(min_length=1, max_length=12_000)


class PracticeObjectiveEvidenceBinding(BaseModel):
    """Server-owned exact evidence eligible for one approved objective.

    The provider may choose wording, but it cannot widen this binding. Each
    quote is one exact physical source line so its receipt and reachability can
    be checked before any provider admission or cost.
    """

    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=160)
    receipt: PracticeSourceReceipt
    evidence_quotes: list[str] = Field(min_length=1, max_length=16)

    @field_validator("objective_id")
    @classmethod
    def _objective_id(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("objective_id must not contain surrounding whitespace")
        return value

    @field_validator("evidence_quotes")
    @classmethod
    def _exact_physical_lines(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("objective evidence quotes must be unique")
        if any(
            quote != quote.strip()
            or "\n" in quote
            or "\r" in quote
            or not 8 <= len(quote) <= 500
            for quote in value
        ):
            raise ValueError(
                "objective evidence quotes must be bounded exact physical lines"
            )
        return value


class PracticeGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    owner_user_id: str
    course_id: str
    practice_set_id: str
    practice_set_revision_id: str
    source_material: list[GenerationSourceText] = Field(min_length=1, max_length=64)
    objective_ids: list[str] = Field(default_factory=list, max_length=64)
    requested_objective_ids: list[str] | None = Field(default=None, max_length=64)
    objective_evidence_bindings: list[PracticeObjectiveEvidenceBinding] = Field(
        default_factory=list, max_length=128
    )
    generation_purpose: PracticeGenerationPurpose = "practice"
    item_limit: int = Field(ge=1, le=12)
    context_char_limit: int = Field(ge=1, le=48_000)
    focus: str = Field(min_length=1, max_length=4_000)
    difficulty: PracticeDifficulty
    timing_mode: PracticeTimingMode
    quality_profile: PracticeQualityProfile = "baseline-v1"

    @field_validator("objective_ids")
    @classmethod
    def _unique_approved_objectives(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(not item.strip() for item in value):
            raise ValueError("objective IDs must be unique and non-empty")
        return value

    @field_validator("requested_objective_ids")
    @classmethod
    def _unique_requested_objectives(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if value is not None and (
            len(set(value)) != len(value) or any(not item.strip() for item in value)
        ):
            raise ValueError("requested objective IDs must be unique and non-empty")
        return value

    def effective_requested_objective_ids(self) -> list[str]:
        return list(
            self.objective_ids
            if self.requested_objective_ids is None
            else self.requested_objective_ids
        )

    @model_validator(mode="after")
    def _objective_evidence_is_unique_and_approved(
        self,
    ) -> "PracticeGenerationInput":
        identities = [
            (
                binding.objective_id,
                binding.receipt.source_id,
                binding.receipt.source_revision,
                binding.receipt.content_sha256,
            )
            for binding in self.objective_evidence_bindings
        ]
        if len(set(identities)) != len(identities):
            raise ValueError(
                "objective evidence bindings must be unique by objective and receipt"
            )
        approved = set(self.objective_ids)
        if any(
            binding.objective_id not in approved
            for binding in self.objective_evidence_bindings
        ):
            raise ValueError("objective evidence must bind only approved objectives")
        return self

    def effective_objective_evidence_bindings(
        self,
    ) -> list[PracticeObjectiveEvidenceBinding]:
        requested = set(self.effective_requested_objective_ids())
        return [
            binding
            for binding in self.objective_evidence_bindings
            if binding.objective_id in requested
        ]


def build_practice_generation_request_contract(
    request: PracticeGenerationInput,
) -> PracticeGenerationRequestContract:
    """Build a stable, text-free receipt for the exact requested generation scope."""

    if request.quality_profile == "c3-biology-v1":
        receipts: list[object] = sorted(
            (
                binding.objective_id,
                binding.receipt.source_id,
                binding.receipt.source_revision,
                binding.receipt.content_sha256,
                tuple(sorted(binding.evidence_quotes)),
            )
            for binding in request.effective_objective_evidence_bindings()
        )
    else:
        receipts = sorted(
            (
                item.receipt.source_id,
                item.receipt.source_revision,
                item.receipt.content_sha256,
            )
            for item in request.source_material
        )
    source_scope_hash = hashlib.sha256(
        json.dumps(receipts, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    requested = request.effective_requested_objective_ids()
    identity = {
        "operation_id": request.operation_id,
        "course_id": request.course_id,
        "practice_set_id": request.practice_set_id,
        "practice_set_revision_id": request.practice_set_revision_id,
        "requested_objective_ids": requested,
        "source_scope_hash": source_scope_hash,
        "generation_purpose": request.generation_purpose,
    }
    request_contract_id = "pgc_" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    return PracticeGenerationRequestContract(
        request_contract_id=request_contract_id,
        requested_objective_ids=requested,
        source_scope_hash=source_scope_hash,
        generation_purpose=request.generation_purpose,
    )


class PracticeGenerationRequest(BaseModel):
    """The atomic creation result exposed to an API adapter."""

    model_config = ConfigDict(extra="forbid")

    practice_set_id: str
    practice_set_revision_id: str
    operation: PracticeGenerationOperation


class PracticeGenerationPlanConfirmation(BaseModel):
    """Atomic confirmation result shared by Practice and Course Chat."""

    model_config = ConfigDict(extra="forbid")

    plan: PracticeGenerationPlan
    request: PracticeGenerationRequest
