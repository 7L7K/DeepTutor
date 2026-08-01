"""Typed, bounded persistence records for Course-owned Practice authoring."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PracticeMode = Literal["manual", "generated"]
PracticeSetState = Literal["draft", "archived"]
PracticeRevisionState = Literal["draft", "ready", "superseded"]


class PracticeSourceReceipt(BaseModel):
    """The immutable, server-resolved identity of one Course source version."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_revision: int = Field(ge=1)
    content_sha256: str

    @field_validator("source_id")
    @classmethod
    def _source_id_is_opaque(cls, value: str) -> str:
        if not value.startswith("src_") or len(value) > 80:
            raise ValueError("source_id must be an opaque Course source ID")
        return value

    @field_validator("content_sha256")
    @classmethod
    def _fingerprint_is_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
        return value


class PracticeCitation(PracticeSourceReceipt):
    """A source receipt plus an optional bounded location inside that source."""

    locator: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("locator")
    @classmethod
    def _bounded_locator(cls, value: dict[str, str | int | float | bool | None]) -> dict[str, str | int | float | bool | None]:
        if len(value) > 16:
            raise ValueError("citation locator has too many fields")
        for key, item in value.items():
            if not key or len(key) > 80:
                raise ValueError("citation locator keys must be non-empty and bounded")
            if isinstance(item, str) and len(item) > 500:
                raise ValueError("citation locator values must be bounded")
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("citation locator numbers must be finite")
        return value


class ExactAnswerContract(BaseModel):
    """The deliberately small deterministic answer contract in P4-02A.

    Additional grading kinds must be added as named, typed models instead of
    widening this record to an unbounded JSON blob.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["exact"]
    answer: str

    @field_validator("answer")
    @classmethod
    def _answer_is_bounded(cls, value: str) -> str:
        if not value.strip() or len(value) > 4_000:
            raise ValueError("exact answer must be non-empty and bounded")
        return value


class PracticeSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    owner_user_id: str
    course_id: str
    title: str
    mode: PracticeMode
    state: PracticeSetState = "draft"
    current_revision_id: str | None = None
    revision: int = Field(ge=1)
    write_epoch: int = Field(ge=1)
    created_at: float
    updated_at: float
    archived_at: float | None = None


class PracticeSetRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    practice_set_id: str
    revision_number: int = Field(ge=1)
    state: PracticeRevisionState = "draft"
    source_snapshot: list[PracticeSourceReceipt] = Field(default_factory=list)
    objective_ids: list[str] = Field(default_factory=list)
    generation_receipt: dict[str, str | int | float | bool | None] | None = None
    created_at: float
    ready_at: float | None = None


class PracticeQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    practice_set_revision_id: str
    question_type: str
    prompt: str
    answer_contract: ExactAnswerContract
    explanation: str
    objective_ids: list[str] = Field(default_factory=list)
    citations: list[PracticeCitation] = Field(default_factory=list)
    ordinal: int = Field(ge=1)
    created_at: float
