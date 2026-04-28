from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.agents.question.coordinator import AgentCoordinator
from deeptutor.agents.question.models import QAPair, QuestionTemplate


@pytest.fixture(autouse=True)
def _stub_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "deeptutor.agents.question.coordinator.load_config_with_main",
        lambda *_args, **_kwargs: {"capabilities": {"question": {"generation": {}}}},
    )


class FakeIdeaAgent:
    async def process(self, **kwargs):
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

    _pairs = [
        QAPair(
            question_id="q_1",
            question="Which response best demonstrates unconditional positive regard?",
            correct_answer="A",
            explanation="Acceptance without judgment fits unconditional positive regard.",
            question_type="choice",
            options={
                "A": "Offering acceptance without judgment",
                "B": "Interpreting resistance immediately",
                "C": "Redirecting away from feelings",
                "D": "Assigning a diagnosis first",
            },
            concentration="core conditions",
            difficulty="medium",
            validation={"schema_ok": True, "repaired": False, "issues": []},
            metadata={"generation_mode": "quiz_set"},
        ),
        QAPair(
            question_id="q_2",
            question="A counseling group is becoming dominated by one member. What should the facilitator do first?",
            correct_answer="B",
            explanation="The facilitator should rebalance participation while keeping the group process visible.",
            question_type="choice",
            options={
                "A": "Ignore it so the group self-corrects",
                "B": "Name the pattern and invite quieter members in",
                "C": "End the group early",
                "D": "Remove the dominant member immediately",
            },
            concentration="group dynamics",
            difficulty="medium",
            validation={"schema_ok": True, "repaired": False, "issues": []},
            metadata={"generation_mode": "quiz_set"},
        ),
    ]

    async def process(self, **kwargs):
        type(self).single_calls += 1
        template = kwargs["template"]
        index = max(0, int(str(template.question_id).split("_")[-1]) - 1)
        pair = self._pairs[index]
        return QAPair(
            **{
                **pair.__dict__,
                "question": f"Single question for {template.concentration}",
                "metadata": {"generation_mode": "progressive_single"},
            }
        )

    async def process_quiz_set(self, **kwargs):
        type(self).set_calls += 1
        return self._pairs


class StubCoordinator(AgentCoordinator):
    def __init__(self, tmp_path: Path, kb_name: str | None = None) -> None:
        super().__init__(output_dir=str(tmp_path), enable_idea_rag=False, kb_name=kb_name)

    def _create_idea_agent(self):  # type: ignore[override]
        return FakeIdeaAgent()

    def _create_generator(self):  # type: ignore[override]
        return FakeGenerator()


def test_coordinator_generate_from_topic_preserves_summary_results_contract(tmp_path: Path) -> None:
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
    assert FakeGenerator.single_calls == 2
    assert FakeGenerator.set_calls == 0


def test_kb_backed_quiz_generation_skips_progressive_single_calls(tmp_path: Path) -> None:
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
    assert FakeGenerator.single_calls == 0
    assert FakeGenerator.set_calls == 1
