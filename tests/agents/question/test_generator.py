from __future__ import annotations

import asyncio

import pytest

from deeptutor.agents.question.agents.generator import Generator
from deeptutor.agents.question.models import QuestionTemplate


class StubGenerator(Generator):
    def __init__(self, repaired_payload: dict | None = None) -> None:
        self._repaired_payload = repaired_payload or {}
        self.tool_flags = {}

    async def _repair_payload(self, **kwargs):  # type: ignore[override]
        return self._repaired_payload


class StubQuizSetGenerator(Generator):
    def __init__(
        self,
        raw_payload: dict,
        repaired_payloads: list[dict] | None = None,
        repaired_quiz_set_payload: dict | None = None,
    ) -> None:
        self._raw_payload = raw_payload
        self._repaired_payloads = list(repaired_payloads or [])
        self._repaired_quiz_set_payload = repaired_quiz_set_payload or {}
        self.tool_flags = {}

    def _build_available_tools_text(self) -> str:  # type: ignore[override]
        return "(no tools available)"

    async def _generate_quiz_set_payload(self, **kwargs):  # type: ignore[override]
        return '{"questions":[', self._raw_payload

    async def _repair_payload(self, **kwargs):  # type: ignore[override]
        if self._repaired_payloads:
            return self._repaired_payloads.pop(0)
        return {}

    async def _repair_quiz_set_payload(self, **kwargs):  # type: ignore[override]
        return self._repaired_quiz_set_payload


def test_generator_repairs_coding_question_that_looks_like_multiple_choice() -> None:
    generator = StubGenerator(
        repaired_payload={
            "question_type": "coding",
            "question": "Write pseudocode that alternates answer order across iterations to mitigate positional bias.",
            "options": None,
            "correct_answer": 'for i in range(total_iterations):\n    if i % 2 == 0:\n        prompt = f"{query} Answer 1: {answer1} Answer 2: {answer2}"\n    else:\n        prompt = f"{query} Answer 1: {answer2} Answer 2: {answer1}"\n    evaluate(prompt)',
            "explanation": "Alternate the two answers deterministically so each appears in each position equally often.",
        }
    )
    template = QuestionTemplate(
        question_id="q_3",
        concentration="win-rate comparison positional bias mitigation",
        question_type="coding",
        difficulty="hard",
    )
    invalid_payload = {
        "question_type": "coding",
        "question": "Select the code logic that best mitigates positional bias across iterations.",
        "options": {
            "A": "fixed order",
            "B": "alternate order every iteration",
            "C": "randomize order",
            "D": "always reverse order",
        },
        "correct_answer": "B",
        "explanation": "B is correct.",
    }

    normalized, validation = asyncio.run(
        generator._validate_and_repair_payload(
            template=template,
            payload=invalid_payload,
            user_topic="win-rate comparison",
            preference="",
            history_context="",
            knowledge_context="",
            available_tools="(no tools available)",
        )
    )

    assert normalized["question_type"] == "coding"
    assert normalized["options"] is None
    assert normalized["correct_answer"].startswith("for i in range")
    assert validation["repaired"] is True
    assert validation["schema_ok"] is True
    assert validation["issues"] == []


def test_generator_normalizes_choice_answer_from_option_text() -> None:
    payload = Generator._normalize_payload_shape(
        "choice",
        {
            "question_type": "choice",
            "question": "Which option is correct?",
            "options": {
                "a": "Alpha",
                "b": "Beta",
                "c": "Gamma",
                "d": "Delta",
            },
            "correct_answer": "Gamma",
            "explanation": "Because gamma matches the requirement.",
        },
    )

    assert payload["options"] == {
        "A": "Alpha",
        "B": "Beta",
        "C": "Gamma",
        "D": "Delta",
    }
    assert payload["correct_answer"] == "C"


def test_generator_process_quiz_set_repairs_duplicate_and_missing_items() -> None:
    generator = StubQuizSetGenerator(
        raw_payload={
            "questions": [
                {
                    "question_id": "q_1",
                    "question_type": "choice",
                    "question": "Which counseling skill best reflects unconditional positive regard?",
                    "options": {
                        "A": "Offering acceptance without judgment",
                        "B": "Interpreting transference immediately",
                        "C": "Assigning diagnostic labels quickly",
                        "D": "Redirecting away from emotion",
                    },
                    "correct_answer": "A",
                    "explanation": "Acceptance without judgment aligns with unconditional positive regard.",
                },
                {
                    "question_id": "q_2",
                    "question_type": "choice",
                    "question": "Which counseling skill best reflects unconditional positive regard?",
                    "options": {
                        "A": "Offering acceptance without judgment",
                        "B": "Interpreting transference immediately",
                        "C": "Assigning diagnostic labels quickly",
                        "D": "Redirecting away from emotion",
                    },
                    "correct_answer": "A",
                    "explanation": "Duplicate question that should be repaired.",
                },
            ]
        },
        repaired_payloads=[
            {
                "question_type": "choice",
                "question": "A counselor wants to demonstrate empathic reflection. Which response is strongest?",
                "options": {
                    "A": "Let's skip how that felt and move to solutions.",
                    "B": "It sounds like you felt dismissed and alone in that moment.",
                    "C": "You probably overreacted to the situation.",
                    "D": "Most clients feel that way, so it's normal.",
                },
                "correct_answer": "B",
                "explanation": "The response names and reflects the client's felt experience.",
            }
        ],
    )

    templates = [
        QuestionTemplate(
            question_id="q_1",
            concentration="core conditions",
            question_type="choice",
            difficulty="medium",
        ),
        QuestionTemplate(
            question_id="q_2",
            concentration="empathic reflection",
            question_type="choice",
            difficulty="medium",
        ),
        QuestionTemplate(
            question_id="q_3",
            concentration="ethical boundaries",
            question_type="choice",
            difficulty="medium",
        ),
    ]

    quiz_set = asyncio.run(
        generator.process_quiz_set(
            templates=templates,
            user_topic="counseling skills",
            preference="diagnostic",
            history_context="",
        )
    )

    assert len(quiz_set) == 3
    assert quiz_set[0].question.startswith("Which counseling skill")
    assert quiz_set[0].validation["schema_ok"] is True

    assert quiz_set[1].question.startswith("A counselor wants to demonstrate empathic reflection")
    assert quiz_set[1].validation["repaired"] is True
    assert quiz_set[1].validation["schema_ok"] is True

    assert quiz_set[2].validation["repaired"] is False
    assert "missing_question" in quiz_set[2].validation["issues"]
    assert quiz_set[2].metadata["generation_mode"] == "quiz_set"


def test_generator_process_quiz_set_repairs_whole_set_before_item_repairs() -> None:
    generator = StubQuizSetGenerator(
        raw_payload={},
        repaired_quiz_set_payload={
            "questions": [
                {
                    "question_id": "q_1",
                    "question_type": "choice",
                    "question": "Which approach best reflects reflective listening?",
                    "options": {
                        "A": "Immediately advising the client what to do",
                        "B": "Restating the client's meaning and feeling accurately",
                        "C": "Changing the subject to keep momentum",
                        "D": "Explaining the theory behind empathy",
                    },
                    "correct_answer": "B",
                    "explanation": "Reflective listening mirrors the client's meaning and feeling.",
                },
                {
                    "question_id": "q_2",
                    "question_type": "choice",
                    "question": "A counselor notices silence after a difficult disclosure. What is the best immediate response?",
                    "options": {
                        "A": "Fill the silence quickly with more questions",
                        "B": "Acknowledge the moment and allow space for the client",
                        "C": "End the session early",
                        "D": "Ignore the silence and move to homework",
                    },
                    "correct_answer": "B",
                    "explanation": "Using the silence intentionally can support processing and safety.",
                },
            ]
        },
    )

    templates = [
        QuestionTemplate(
            question_id="q_1",
            concentration="reflective listening",
            question_type="choice",
            difficulty="medium",
        ),
        QuestionTemplate(
            question_id="q_2",
            concentration="therapeutic silence",
            question_type="choice",
            difficulty="medium",
        ),
    ]

    quiz_set = asyncio.run(
        generator.process_quiz_set(
            templates=templates,
            user_topic="counseling microskills",
            preference="quick check",
            history_context="",
        )
    )

    assert len(quiz_set) == 2
    assert all(item.validation["schema_ok"] is True for item in quiz_set)
    assert all(item.validation["repaired"] is False for item in quiz_set)
