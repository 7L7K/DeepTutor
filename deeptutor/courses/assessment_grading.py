"""Pure deterministic grading shared by Python and SQLite authority checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import unicodedata

from .practice_models import (
    BoundedShortAnswerContract,
    ExactAnswerContract,
    PracticeAnswerContract,
    SingleChoiceAnswerContract,
    SingleChoiceOption,
    normalize_bounded_short_answer,
)


@dataclass(frozen=True)
class AssessmentDecision:
    is_correct: bool
    error_type: str | None
    raw_response: str
    normalized_response: str


def _exact(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def grade_assessment_response(
    response: Any,
    contract: PracticeAnswerContract,
    options: list[SingleChoiceOption],
) -> AssessmentDecision:
    """Validate one typed learner response and return its exact decision."""

    if isinstance(contract, SingleChoiceAnswerContract):
        if not (
            isinstance(response, dict)
            and set(response) == {"option_id"}
            and isinstance(response["option_id"], str)
        ):
            raise ValueError("Single-choice response must be exactly {'option_id': string}")
        selected = response["option_id"]
        option_ids = {item.option_id for item in options}
        if selected not in option_ids:
            raise ValueError("Selected option does not belong to the immutable question")
        is_correct = selected == contract.correct_option_id
        return AssessmentDecision(
            is_correct=is_correct,
            error_type=None if is_correct else "application",
            raw_response=selected,
            normalized_response=selected,
        )

    if not (
        isinstance(response, dict)
        and set(response) == {"answer"}
        and isinstance(response["answer"], str)
    ):
        raise ValueError("Short-answer response must be exactly {'answer': string}")
    answer = response["answer"]
    if len(answer) > 4_000:
        raise ValueError("Short-answer response is too large")
    if isinstance(contract, BoundedShortAnswerContract):
        normalized = normalize_bounded_short_answer(answer)
        is_correct = normalized in contract.accepted_normalized_answers
    elif isinstance(contract, ExactAnswerContract):
        normalized = _exact(answer)
        is_correct = any(
            normalized == _exact(candidate)
            for candidate in [contract.answer, *contract.accepted_answers]
        )
    else:  # pragma: no cover - the discriminated union is exhaustive.
        raise ValueError("Unsupported Practice answer contract")
    return AssessmentDecision(
        is_correct=is_correct,
        error_type=None if is_correct else ("metacognitive" if not answer.strip() else "application"),
        raw_response=answer,
        normalized_response=normalized,
    )


__all__ = ["AssessmentDecision", "grade_assessment_response"]
