from __future__ import annotations

import pytest

from deeptutor.agents.question.coordinator import AgentCoordinator
from deeptutor.agents.question.models import QAPair


@pytest.mark.asyncio
async def test_coordinator_uses_practice_quiz_model(monkeypatch):
    seen: dict[str, object] = {}

    async def fake_process_quiz_set(self, templates, **kwargs):
        seen["model"] = self.get_model()
        seen["generation_api"] = kwargs.get("generation_api")
        return [
            QAPair(
                question_id=templates[0].question_id,
                question="Which action best protects client welfare?",
                correct_answer="A",
                explanation="It preserves the client's welfare and boundaries.",
                question_type="choice",
                options={"A": "Consult and document", "B": "Ignore it"},
                concentration=templates[0].concentration,
                difficulty=templates[0].difficulty,
                validation={"schema_ok": True},
                metadata={"generation_api": kwargs.get("generation_api")},
            )
        ]

    monkeypatch.setenv("PRACTICE_QUIZ_MODEL", "gpt-5-mini")
    monkeypatch.setenv("QUESTION_GENERATION_MODEL", "gpt-5-nano")
    monkeypatch.setenv("PRACTICE_GENERATION_API", "chat")
    monkeypatch.setattr(
        "deeptutor.agents.question.agents.generator.Generator.process_quiz_set",
        fake_process_quiz_set,
    )

    coordinator = AgentCoordinator(api_key="test", base_url="https://api.openai.com/v1")
    result = await coordinator.generate_from_topic("NCE ethics", num_questions=1)

    assert seen == {"model": "gpt-5-mini", "generation_api": "chat"}
    assert result["metadata"]["model"] == "gpt-5-mini"
    assert "PRACTICE_QUIZ_MODEL" in result["metadata"]["model_path"]


@pytest.mark.asyncio
async def test_coordinator_emits_first_useful_timing(monkeypatch):
    emitted: list[dict[str, object]] = []

    async def fake_process_quiz_set(self, templates, **kwargs):
        return [
            QAPair(
                question_id=templates[0].question_id,
                question="Question stem",
                correct_answer="A",
                explanation="Because.",
                question_type="choice",
                options={"A": "Correct", "B": "Distractor"},
                concentration=templates[0].concentration,
                difficulty=templates[0].difficulty,
                validation={"schema_ok": True},
                metadata={"generation_api": kwargs.get("generation_api")},
            )
        ]

    monkeypatch.setenv("PRACTICE_QUIZ_MODEL", "gpt-5-mini")
    monkeypatch.setenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", "1")
    monkeypatch.setenv("PRACTICE_STARTER_PAGE_API", "responses_minimal")
    monkeypatch.setenv("PRACTICE_BACKGROUND_PAGE_API", "chat")
    monkeypatch.setattr(
        "deeptutor.agents.question.agents.generator.Generator.process_quiz_set",
        fake_process_quiz_set,
    )

    coordinator = AgentCoordinator(api_key="test", base_url="https://api.openai.com/v1")
    coordinator.set_ws_callback(lambda payload: emitted.append(payload))
    result = await coordinator.generate_from_topic("NCE ethics", num_questions=2)

    assert [event["generation_api"] for event in emitted if event.get("type") == "result"] == [
        "responses_minimal",
        "chat",
    ]
    assert result["metadata"]["first_useful_output_ms"] <= result["metadata"]["total_completion_ms"]
