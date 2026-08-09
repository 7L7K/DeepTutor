"""Typed, bounded persistence records for Course-owned Practice authoring."""

from __future__ import annotations

import math
import re
from typing import Annotated, Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PracticeMode = Literal["manual", "generated"]
PracticeSetState = Literal["draft", "archived"]
PracticeRevisionState = Literal["draft", "ready", "superseded"]
OPAQUE_OPTION_ID_PATTERN = re.compile(r"opt_[0-9a-f]{32}\Z")


def is_opaque_option_id(value: object) -> bool:
    """Return whether *value* is a canonical server-owned option identifier."""

    return isinstance(value, str) and OPAQUE_OPTION_ID_PATTERN.fullmatch(value) is not None


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
    """A bounded deterministic answer contract.

    Additional grading kinds must be added as named, typed models instead of
    widening this record to an unbounded JSON blob.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["exact"]
    answer: str
    accepted_answers: list[str] = Field(
        default_factory=list,
        max_length=8,
        exclude_if=lambda value: not value,
    )

    @field_validator("answer")
    @classmethod
    def _answer_is_bounded(cls, value: str) -> str:
        if not value.strip() or len(value) > 4_000:
            raise ValueError("exact answer must be non-empty and bounded")
        return value

    @field_validator("accepted_answers")
    @classmethod
    def _accepted_answers_are_bounded(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 4_000 for item in value):
            raise ValueError("accepted exact answers must be non-empty and bounded")
        normalized = [" ".join(item.casefold().split()) for item in value]
        if len(set(normalized)) != len(normalized):
            raise ValueError("accepted exact answers must be unique")
        return value

    @model_validator(mode="after")
    def _accepted_answers_do_not_repeat_primary(self) -> "ExactAnswerContract":
        primary = " ".join(self.answer.casefold().split())
        if primary in {" ".join(item.casefold().split()) for item in self.accepted_answers}:
            raise ValueError("accepted exact answers must differ from the primary answer")
        return self


_BOUNDED_DASHES = str.maketrans(
    {
        "\u058a": "-",
        "\u05be": "-",
        "\u1400": "-",
        "\u1806": "-",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2e17": "-",
        "\u2e1a": "-",
        "\u2e3a": "-",
        "\u2e3b": "-",
        "\u2e40": "-",
        "\u301c": "-",
        "\u3030": "-",
        "\u30a0": "-",
        "\ufe31": "-",
        "\ufe32": "-",
        "\ufe58": "-",
        "\ufe63": "-",
        "\uff0d": "-",
        "\u2212": "-",
    }
)


def normalize_bounded_short_answer(value: str) -> str:
    """Normalize only safe text-surface differences for bounded grading."""

    normalized = unicodedata.normalize("NFKC", value).translate(_BOUNDED_DASHES)
    normalized = re.sub(r"\s+", " ", normalized.casefold().strip())
    normalized = re.sub(r"[.!?\u3002\uff01\uff1f\u2026]+$", "", normalized).rstrip()
    return normalized


class BoundedShortAnswerContract(BaseModel):
    """Explicit normalized answers; never fuzzy or provider-graded."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["bounded_short_answer_v1"]
    canonical_answer: str
    accepted_normalized_answers: list[str] = Field(min_length=1, max_length=16)
    normalization_version: Literal["bounded-text-normalization-v1"]

    @field_validator("canonical_answer")
    @classmethod
    def _canonical_answer_is_bounded(cls, value: str) -> str:
        if not value.strip() or len(value) > 4_000:
            raise ValueError("canonical answer must be non-empty and bounded")
        return value

    @field_validator("accepted_normalized_answers")
    @classmethod
    def _accepted_answers_are_pre_normalized(cls, value: list[str]) -> list[str]:
        if any(
            not item
            or len(item) > 4_000
            or normalize_bounded_short_answer(item) != item
            for item in value
        ):
            raise ValueError("accepted bounded answers must use normalized v1 form")
        if len(set(value)) != len(value):
            raise ValueError("accepted bounded answers must be unique")
        return value

    @model_validator(mode="after")
    def _canonical_answer_is_explicitly_accepted(self) -> "BoundedShortAnswerContract":
        if normalize_bounded_short_answer(self.canonical_answer) not in self.accepted_normalized_answers:
            raise ValueError("accepted bounded answers must include the canonical answer")
        return self


class SingleChoiceOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str
    text: str = Field(min_length=1, max_length=4_000)

    @field_validator("option_id")
    @classmethod
    def _option_id_is_opaque(cls, value: str) -> str:
        if not is_opaque_option_id(value):
            raise ValueError("option_id must use canonical opaque option format")
        return value

    @field_validator("text")
    @classmethod
    def _option_text_is_bounded(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("option text must be non-empty without surrounding whitespace")
        return value


class SingleChoiceAnswerContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["single_choice_v1"]
    correct_option_id: str

    @field_validator("correct_option_id")
    @classmethod
    def _correct_option_id_is_opaque(cls, value: str) -> str:
        if not is_opaque_option_id(value):
            raise ValueError("correct_option_id must use canonical opaque option format")
        return value


PracticeAnswerContract = Annotated[
    ExactAnswerContract | BoundedShortAnswerContract | SingleChoiceAnswerContract,
    Field(discriminator="kind"),
]


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
    options: list[SingleChoiceOption] = Field(default_factory=list, max_length=8)
    answer_contract: PracticeAnswerContract
    explanation: str
    objective_ids: list[str] = Field(default_factory=list)
    citations: list[PracticeCitation] = Field(default_factory=list)
    ordinal: int = Field(ge=1)
    created_at: float

    @field_validator("question_type")
    @classmethod
    def _question_type_is_bounded(cls, value: str) -> str:
        if not value or value != value.strip() or len(value) > 80:
            raise ValueError("question_type must be non-empty and bounded")
        return value

    @model_validator(mode="after")
    def _question_shape_matches_answer_contract(self) -> "PracticeQuestion":
        if isinstance(self.answer_contract, SingleChoiceAnswerContract):
            if self.question_type != "single_choice" or len(self.options) < 2:
                raise ValueError("single-choice questions require at least two options")
            option_ids = [item.option_id for item in self.options]
            if len(set(option_ids)) != len(option_ids):
                raise ValueError("single-choice option IDs must be unique")
            option_text = [" ".join(item.text.casefold().split()) for item in self.options]
            if len(set(option_text)) != len(option_text):
                raise ValueError("single-choice option text must be unique")
            if self.answer_contract.correct_option_id not in option_ids:
                raise ValueError("correct option must belong to the immutable question")
        elif isinstance(self.answer_contract, BoundedShortAnswerContract):
            if self.options or self.question_type != "short_answer":
                raise ValueError("bounded short answers require question_type='short_answer'")
        elif self.options or self.question_type == "single_choice":
            # Historical exact rows accepted any bounded type string. Keep
            # them readable after 0015; all new authoring is canonicalized by
            # the repository boundary to `short_answer`.
            raise ValueError("short-answer contracts require question_type='short_answer'")
        return self
