from __future__ import annotations

import asyncio
from pathlib import Path

from deeptutor.agents.question.coordinator import AgentCoordinator
from deeptutor.agents.question.models import QAPair, QuestionTemplate


class FakeIdeaAgent:
    calls = 0

    async def process(self, **kwargs):
        type(self).calls += 1
        return {
            "templates": [
                QuestionTemplate(
                    question_id="",
                    concentration="core conditions",
                    question_type="choice",
                    difficulty="medium",
                ),
                QuestionTemplate(
                    question_id="",
                    concentration="group dynamics",
                    question_type="choice",
                    difficulty="medium",
                ),
            ],
            "knowledge_context": "stub context",
        }


class FakeGenerator:
    single_calls = 0
    set_calls = 0

    async def process(self, **kwargs):
        type(self).single_calls += 1
        template = kwargs["template"]
        return QAPair(
            question_id=template.question_id,
            question=f"Single question for {template.concentration}",
            correct_answer="A",
            explanation="single",
            question_type=template.question_type,
            options={"A": "Correct", "B": "Wrong", "C": "Wrong", "D": "Wrong"},
            concentration=template.concentration,
            difficulty=template.difficulty,
            validation={"schema_ok": True, "repaired": False, "issues": []},
            metadata={"generation_mode": "progressive_single"},
        )

    async def process_quiz_set(self, **kwargs):
        type(self).set_calls += 1
        return [
            QAPair(
                question_id=template.question_id,
                question=f"Set question for {template.concentration}",
                correct_answer="A",
                explanation="set",
                question_type=template.question_type,
                options={"A": "Correct", "B": "Wrong", "C": "Wrong", "D": "Wrong"},
                concentration=template.concentration,
                difficulty=template.difficulty,
                validation={"schema_ok": True, "repaired": False, "issues": []},
                metadata={"generation_mode": "quiz_set"},
            )
            for template in kwargs["templates"]
        ]


class StubCoordinator(AgentCoordinator):
    def __init__(self, tmp_path: Path, kb_name: str | None = None) -> None:
        super().__init__(output_dir=str(tmp_path), enable_idea_rag=False, kb_name=kb_name)

    def _create_idea_agent(self):  # type: ignore[override]
        return FakeIdeaAgent()

    def _create_generator(self):  # type: ignore[override]
        return FakeGenerator()


def test_coordinator_generate_from_topic_uses_direct_templates_by_default(tmp_path: Path) -> None:
    FakeIdeaAgent.calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    coordinator = StubCoordinator(tmp_path)

    summary = asyncio.run(
        coordinator.generate_from_topic(
            user_topic="counseling skills",
            preference="diagnostic",
            num_questions=2,
            difficulty="medium",
            question_type="choice",
        )
    )

    assert summary["success"] is True
    assert summary["completed"] == 2
    assert len(summary["results"]) == 2
    assert summary["results"][0]["qa_pair"]["question_id"] == "q_1"
    assert summary["results"][1]["qa_pair"]["question"]
    assert summary["trace"]["ideation_skipped"] is True
    assert FakeIdeaAgent.calls == 0
    assert FakeGenerator.single_calls == 0
    assert FakeGenerator.set_calls == 1


def test_kb_backed_quiz_generation_streams_first_question_before_set(tmp_path: Path) -> None:
    FakeIdeaAgent.calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    coordinator = StubCoordinator(tmp_path, kb_name="tester-1__nce-2026")

    summary = asyncio.run(
        coordinator.generate_from_topic(
            user_topic="NCE review",
            preference="use the KB",
            num_questions=2,
            difficulty="medium",
            question_type="choice",
        )
    )

    assert summary["success"] is True
    assert len(summary["results"]) == 2
    assert summary["trace"].get("ideation_skipped") is not True
    assert FakeIdeaAgent.calls == 1
    assert FakeGenerator.single_calls == 1
    assert FakeGenerator.set_calls == 1
    assert summary["results"][0]["qa_pair"]["metadata"]["generation_mode"] == "progressive_single"
    assert summary["results"][1]["qa_pair"]["metadata"]["generation_mode"] == "quiz_set"


def test_kb_backed_progressive_first_batch_can_be_disabled(tmp_path: Path, monkeypatch) -> None:
    FakeIdeaAgent.calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    monkeypatch.setenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", "0")
    coordinator = StubCoordinator(tmp_path, kb_name="tester-1__nce-2026")

    summary = asyncio.run(
        coordinator.generate_from_topic(
            user_topic="NCE review",
            preference="use the KB",
            num_questions=2,
            difficulty="medium",
            question_type="choice",
        )
    )

    assert summary["success"] is True
    assert FakeIdeaAgent.calls == 1
    assert FakeGenerator.single_calls == 0
    assert FakeGenerator.set_calls == 1


def test_topic_quiz_can_skip_ideation_with_direct_templates(tmp_path: Path, monkeypatch) -> None:
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    monkeypatch.setenv("PRACTICE_QUIZ_SKIP_IDEATION", "true")
    coordinator = StubCoordinator(tmp_path)

    summary = asyncio.run(
        coordinator.generate_from_topic(
            user_topic="NCE ethics boundaries",
            preference="diagnostic",
            num_questions=2,
            difficulty="medium",
            question_type="choice",
        )
    )

    assert summary["success"] is True
    assert summary["trace"]["ideation_skipped"] is True
    assert summary["results"][0]["template"]["metadata"]["ideation_skipped"] is True
    assert FakeGenerator.single_calls == 0
    assert FakeGenerator.set_calls == 1
