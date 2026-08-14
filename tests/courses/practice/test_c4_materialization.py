"""Focused C4 proof for exact qualified-content materialization."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from deeptutor.courses.generation_models import GeneratedPracticeQuestion
from deeptutor.courses.practice_models import (
    SingleChoiceAnswerContract,
    SingleChoiceOption,
)

ROOT = Path(__file__).resolve().parents[3]
PRIMARY = ROOT / "docs/verification/2026-08-10-teeechr-c3-final-learning-loop-v3-1/primary/model-qualified-candidate.json"
REMEDIATION = ROOT / "docs/verification/2026-08-10-teeechr-c3-final-learning-loop-v3-1-remediation-v2/remediation/model-qualified-candidate.json"


def test_c4_uses_the_frozen_three_item_primary_and_two_item_remediation() -> None:
    primary = json.loads(PRIMARY.read_text(encoding="utf-8"))
    remediation = json.loads(REMEDIATION.read_text(encoding="utf-8"))

    assert primary["status"] == "MODEL_QUALIFIED"
    assert remediation["status"] == "MODEL_QUALIFIED"
    assert len(primary["questions"]) == 3
    assert len(remediation["questions"]) == 2
    assert [item["objective_ids"] for item in primary["questions"]] == [
        ["OBJ-RESP-01"],
        ["OBJ-RESP-02"],
        ["OBJ-RESP-03"],
    ]
    assert {item["objective_ids"][0] for item in remediation["questions"]} == {
        "OBJ-RESP-02",
        "OBJ-RESP-03",
    }
    assert hashlib.sha256(PRIMARY.read_bytes()).hexdigest()
    assert hashlib.sha256(REMEDIATION.read_bytes()).hexdigest()


def test_generated_practice_question_preserves_typed_choice_contract() -> None:
    options = [
        SingleChoiceOption(option_id=f"opt_{index:032x}", text=text)
        for index, text in enumerate(("Incorrect", "Correct"), 1)
    ]
    question = GeneratedPracticeQuestion(
        question_type="single_choice",
        prompt="Which statement is correct?",
        options=options,
        answer_contract=SingleChoiceAnswerContract(
            kind="single_choice_v1", correct_option_id=options[1].option_id
        ),
        explanation="The second option is the qualified answer.",
        objective_ids=["OBJ-RESP-02"],
        citations=[],
    )
    assert question.options[1].option_id == question.answer_contract.correct_option_id
