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
    calls = 0
    retrieval_calls = 0

    async def retrieve_context_for_topic(self, user_topic: str, **kwargs):
        type(self).retrieval_calls += 1
        return {
            "retrievals": [{"query": user_topic, "answer": "KB context"}],
            "knowledge_context": "KB context",
            "retrieval_queries": [user_topic],
        }

    async def process(self, **kwargs):
        type(self).calls += 1
        num_ideas = int(kwargs.get("num_ideas") or 2)
        candidates = [
            ("core conditions", "choice", "medium"),
            ("group dynamics", "choice", "medium"),
            ("career development", "choice", "medium"),
        ]
        while len(candidates) < num_ideas:
            candidates.append((f"domain review {len(candidates) + 1}", "choice", "medium"))
        return {
            "templates": [
                QuestionTemplate(
                    question_id="",
                    concentration=concentration,
                    question_type=question_type,
                    difficulty=difficulty,
                )
                for concentration, question_type, difficulty in candidates[:num_ideas]
            ],
            "knowledge_context": "stub context",
        }


class FakeGenerator:
    single_calls = 0
    set_calls = 0
    active_set_calls = 0
    max_active_set_calls = 0
    set_delay_seconds = 0.0
    set_generation_apis: list[str | None] = []
    invalid_set_question_ids: set[str] = set()
    omit_set_question_ids: set[str] = set()
    invalid_single_once_question_ids: set[str] = set()
    invalid_single_counts: dict[str, int] = {}

    async def process(self, **kwargs):
        type(self).single_calls += 1
        template = kwargs["template"]
        if (
            template.question_id in type(self).invalid_single_once_question_ids
            and type(self).invalid_single_counts.get(template.question_id, 0) == 0
        ):
            type(self).invalid_single_counts[template.question_id] = 1
            return QAPair(
                question_id=template.question_id,
                question=f"Invalid single question for {template.concentration}",
                correct_answer="N/A",
                explanation="",
                question_type=template.question_type,
                options=None,
                concentration=template.concentration,
                difficulty=template.difficulty,
                validation={
                    "schema_ok": False,
                    "repaired": False,
                    "issues": ["choice_missing_options"],
                },
                metadata={"generation_mode": "progressive_single"},
            )
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
        type(self).set_generation_apis.append(kwargs.get("generation_api"))
        type(self).active_set_calls += 1
        type(self).max_active_set_calls = max(
            type(self).max_active_set_calls,
            type(self).active_set_calls,
        )
        try:
            if type(self).set_delay_seconds:
                await asyncio.sleep(type(self).set_delay_seconds)
            pairs: list[QAPair] = []
            for template in kwargs["templates"]:
                if template.question_id in type(self).omit_set_question_ids:
                    continue
                if template.question_id in type(self).invalid_set_question_ids:
                    pairs.append(
                        QAPair(
                            question_id=template.question_id,
                            question=f"Invalid question for {template.concentration}",
                            correct_answer="N/A",
                            explanation="",
                            question_type=template.question_type,
                            options=None,
                            concentration=template.concentration,
                            difficulty=template.difficulty,
                            validation={},
                            metadata={"generation_mode": "quiz_set"},
                        )
                    )
                    continue
                pairs.append(
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
                )
            return pairs
        finally:
            type(self).active_set_calls -= 1


class StubCoordinator(AgentCoordinator):
    def __init__(
        self,
        tmp_path: Path,
        kb_name: str | None = None,
        enable_idea_rag: bool = False,
    ) -> None:
        super().__init__(
            output_dir=str(tmp_path),
            enable_idea_rag=enable_idea_rag,
            kb_name=kb_name,
        )

    def _create_idea_agent(self):  # type: ignore[override]
        return FakeIdeaAgent()

    def _create_generator(self):  # type: ignore[override]
        return FakeGenerator()


def test_coordinator_generate_from_topic_uses_direct_templates_by_default(tmp_path: Path, monkeypatch) -> None:
    FakeIdeaAgent.calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    monkeypatch.delenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", raising=False)
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


def test_kb_backed_quiz_uses_fast_direct_quiz_set_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeIdeaAgent.calls = 0
    FakeIdeaAgent.retrieval_calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    monkeypatch.delenv("PRACTICE_QUIZ_FAST_KB_BATCH", raising=False)
    monkeypatch.delenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", raising=False)
    coordinator = StubCoordinator(
        tmp_path,
        kb_name="tester-1__nce-2026",
        enable_idea_rag=True,
    )

    summary = asyncio.run(
        coordinator.generate_from_topic(
            user_topic="NCE review",
            preference="use the KB",
            num_questions=6,
            difficulty="medium",
            question_type="choice",
        )
    )

    assert summary["success"] is True
    assert len(summary["results"]) == 6
    assert FakeIdeaAgent.retrieval_calls == 1
    assert FakeIdeaAgent.calls == 0
    assert FakeGenerator.single_calls == 0
    assert FakeGenerator.set_calls == 1
    assert summary["trace"]["batches"][0]["batch"] == "fast_kb_quiz_set"
    assert all(
        item["template"]["metadata"]["fast_kb_quiz_set"] is True
        for item in summary["results"]
    )
    assert [item["qa_pair"]["question_id"] for item in summary["results"]] == [
        "q_1",
        "q_2",
        "q_3",
        "q_4",
        "q_5",
        "q_6",
    ]


def test_kb_backed_quiz_generation_streams_first_question_before_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeIdeaAgent.calls = 0
    FakeIdeaAgent.retrieval_calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    monkeypatch.setenv("PRACTICE_QUIZ_FAST_KB_BATCH", "false")
    monkeypatch.setenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", "1")
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
    assert FakeIdeaAgent.retrieval_calls == 0
    assert FakeGenerator.single_calls == 1
    assert FakeGenerator.set_calls == 1
    assert summary["results"][0]["qa_pair"]["metadata"]["generation_mode"] == "progressive_single"
    assert summary["results"][1]["qa_pair"]["metadata"]["generation_mode"] == "starter_page"


def test_kb_backed_quiz_streams_direct_grounded_first_question_before_ideation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeIdeaAgent.calls = 0
    FakeIdeaAgent.retrieval_calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    monkeypatch.setenv("PRACTICE_QUIZ_FAST_KB_BATCH", "false")
    monkeypatch.setenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", "1")
    coordinator = StubCoordinator(
        tmp_path,
        kb_name="tester-1__nce-2026",
        enable_idea_rag=True,
    )

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
    assert FakeIdeaAgent.retrieval_calls == 1
    assert FakeIdeaAgent.calls == 0
    assert FakeGenerator.single_calls == 1
    assert FakeGenerator.set_calls == 1
    assert summary["results"][0]["template"]["metadata"]["direct_streamed_first"] is True
    assert summary["results"][0]["template"]["metadata"]["knowledge_context"] == "KB context"
    assert summary["results"][1]["template"]["metadata"]["direct_kb_templates"] is True
    assert summary["results"][0]["qa_pair"]["metadata"]["generation_mode"] == "direct_kb_first"
    assert summary["results"][1]["qa_pair"]["metadata"]["generation_mode"] == "starter_page"


def test_kb_backed_quiz_retries_invalid_direct_first_question(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeIdeaAgent.calls = 0
    FakeIdeaAgent.retrieval_calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    FakeGenerator.invalid_single_once_question_ids = {"q_1"}
    FakeGenerator.invalid_single_counts = {}
    monkeypatch.setenv("PRACTICE_QUIZ_FAST_KB_BATCH", "false")
    monkeypatch.setenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", "1")
    coordinator = StubCoordinator(
        tmp_path,
        kb_name="tester-1__nce-2026",
        enable_idea_rag=True,
    )

    try:
        summary = asyncio.run(
            coordinator.generate_from_topic(
                user_topic="NCE review",
                preference="use the KB",
                num_questions=2,
                difficulty="medium",
                question_type="choice",
            )
        )
    finally:
        FakeGenerator.invalid_single_once_question_ids = set()
        FakeGenerator.invalid_single_counts = {}

    assert summary["success"] is True
    assert summary["completed"] == 2
    assert summary["failed"] == 0
    assert FakeGenerator.single_calls == 2
    assert summary["results"][0]["qa_pair"]["metadata"]["generation_mode"] == "direct_kb_first_retry"
    assert summary["results"][0]["qa_pair"]["validation"]["schema_ok"] is True


def test_kb_backed_quiz_streams_first_five_questions_as_starter_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    FakeIdeaAgent.calls = 0
    FakeIdeaAgent.retrieval_calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    FakeGenerator.set_generation_apis = []
    monkeypatch.setenv("PRACTICE_QUIZ_FAST_KB_BATCH", "false")
    monkeypatch.setenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", "1")
    monkeypatch.setenv("PRACTICE_STARTER_PAGE_API", "chat")
    coordinator = StubCoordinator(
        tmp_path,
        kb_name="tester-1__nce-2026",
        enable_idea_rag=True,
    )

    summary = asyncio.run(
        coordinator.generate_from_topic(
            user_topic="NCE review",
            preference="use the KB",
            num_questions=6,
            difficulty="medium",
            question_type="choice",
        )
    )

    assert summary["success"] is True
    assert len(summary["results"]) == 6
    assert FakeIdeaAgent.retrieval_calls == 1
    assert FakeIdeaAgent.calls == 0
    assert FakeGenerator.single_calls == 1
    assert FakeGenerator.set_calls == 2
    assert [
        item["qa_pair"]["metadata"]["generation_mode"]
        for item in summary["results"][:5]
    ] == [
        "direct_kb_first",
        "starter_page",
        "starter_page",
        "starter_page",
        "starter_page",
    ]
    assert [item["qa_pair"]["question_id"] for item in summary["results"]] == [
        "q_1",
        "q_2",
        "q_3",
        "q_4",
        "q_5",
        "q_6",
    ]
    assert FakeGenerator.set_generation_apis == ["chat", "chat"]


def test_kb_starter_page_can_use_responses_while_background_stays_chat(
    tmp_path: Path,
    monkeypatch,
) -> None:
    FakeIdeaAgent.calls = 0
    FakeIdeaAgent.retrieval_calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    FakeGenerator.set_generation_apis = []
    monkeypatch.setenv("PRACTICE_QUIZ_FAST_KB_BATCH", "false")
    monkeypatch.setenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", "1")
    monkeypatch.setenv("PRACTICE_STARTER_PAGE_API", "responses")
    coordinator = StubCoordinator(
        tmp_path,
        kb_name="tester-1__nce-2026",
        enable_idea_rag=True,
    )

    summary = asyncio.run(
        coordinator.generate_from_topic(
            user_topic="NCE review",
            preference="use the KB",
            num_questions=6,
            difficulty="medium",
            question_type="choice",
        )
    )

    assert summary["success"] is True
    assert len(summary["results"]) == 6
    assert FakeGenerator.set_calls == 2
    assert FakeGenerator.set_generation_apis == ["responses", "chat"]
    assert [item["qa_pair"]["question_id"] for item in summary["results"]] == [
        "q_1",
        "q_2",
        "q_3",
        "q_4",
        "q_5",
        "q_6",
    ]


def test_kb_starter_page_missing_item_falls_back_to_single_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    FakeIdeaAgent.calls = 0
    FakeIdeaAgent.retrieval_calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    FakeGenerator.omit_set_question_ids = {"q_3"}
    FakeGenerator.invalid_set_question_ids = set()
    monkeypatch.setenv("PRACTICE_QUIZ_FAST_KB_BATCH", "false")
    monkeypatch.setenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", "1")
    monkeypatch.setenv("PRACTICE_STARTER_PAGE_API", "chat")
    coordinator = StubCoordinator(
        tmp_path,
        kb_name="tester-1__nce-2026",
        enable_idea_rag=True,
    )

    try:
        summary = asyncio.run(
            coordinator.generate_from_topic(
                user_topic="NCE review",
                preference="use the KB",
                num_questions=6,
                difficulty="medium",
                question_type="choice",
            )
        )
    finally:
        FakeGenerator.omit_set_question_ids = set()

    assert summary["success"] is True
    assert summary["completed"] == 6
    assert summary["failed"] == 0
    assert FakeGenerator.single_calls == 2
    assert [item["qa_pair"]["question_id"] for item in summary["results"]] == [
        "q_1",
        "q_2",
        "q_3",
        "q_4",
        "q_5",
        "q_6",
    ]
    assert summary["results"][2]["qa_pair"]["metadata"]["generation_mode"] == "single_fallback"


def test_kb_starter_page_invalid_item_falls_back_to_single_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    FakeIdeaAgent.calls = 0
    FakeIdeaAgent.retrieval_calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    FakeGenerator.omit_set_question_ids = set()
    FakeGenerator.invalid_set_question_ids = {"q_4"}
    monkeypatch.setenv("PRACTICE_QUIZ_FAST_KB_BATCH", "false")
    monkeypatch.setenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", "1")
    monkeypatch.setenv("PRACTICE_STARTER_PAGE_API", "chat")
    coordinator = StubCoordinator(
        tmp_path,
        kb_name="tester-1__nce-2026",
        enable_idea_rag=True,
    )

    try:
        summary = asyncio.run(
            coordinator.generate_from_topic(
                user_topic="NCE review",
                preference="use the KB",
                num_questions=6,
                difficulty="medium",
                question_type="choice",
            )
        )
    finally:
        FakeGenerator.invalid_set_question_ids = set()

    assert summary["success"] is True
    assert summary["completed"] == 6
    assert summary["failed"] == 0
    assert FakeGenerator.single_calls == 2
    assert summary["results"][3]["qa_pair"]["question_id"] == "q_4"
    assert summary["results"][3]["qa_pair"]["metadata"]["generation_mode"] == "single_fallback"


def test_remaining_quiz_generation_runs_in_configured_chunks(tmp_path: Path, monkeypatch) -> None:
    FakeIdeaAgent.calls = 0
    FakeIdeaAgent.retrieval_calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    FakeGenerator.active_set_calls = 0
    FakeGenerator.max_active_set_calls = 0
    monkeypatch.setenv("PRACTICE_QUIZ_FAST_KB_BATCH", "false")
    monkeypatch.setenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", "1")
    monkeypatch.setenv("PRACTICE_QUIZ_REMAINING_BATCH_SIZE", "1")
    monkeypatch.setenv("PRACTICE_QUIZ_STARTER_PAGE_SIZE", "1")
    coordinator = StubCoordinator(
        tmp_path,
        kb_name="tester-1__nce-2026",
        enable_idea_rag=True,
    )

    summary = asyncio.run(
        coordinator.generate_from_topic(
            user_topic="NCE review",
            preference="use the KB",
            num_questions=3,
            difficulty="medium",
            question_type="choice",
        )
    )

    assert summary["success"] is True
    assert len(summary["results"]) == 3
    assert FakeGenerator.single_calls == 1
    assert FakeGenerator.set_calls == 2
    assert [item["qa_pair"]["question_id"] for item in summary["results"]] == [
        "q_1",
        "q_2",
        "q_3",
    ]


def test_kb_ideation_can_be_enabled_for_progressive_quiz(tmp_path: Path, monkeypatch) -> None:
    FakeIdeaAgent.calls = 0
    FakeIdeaAgent.retrieval_calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    monkeypatch.setenv("PRACTICE_QUIZ_FAST_KB_BATCH", "false")
    monkeypatch.setenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", "1")
    monkeypatch.setenv("PRACTICE_QUIZ_SKIP_KB_IDEATION", "false")
    coordinator = StubCoordinator(
        tmp_path,
        kb_name="tester-1__nce-2026",
        enable_idea_rag=True,
    )

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
    assert FakeIdeaAgent.retrieval_calls == 1
    assert FakeIdeaAgent.calls == 1
    assert FakeGenerator.single_calls == 1
    assert FakeGenerator.set_calls == 1


def test_remaining_quiz_chunks_run_with_bounded_concurrency(tmp_path: Path, monkeypatch) -> None:
    FakeIdeaAgent.calls = 0
    FakeIdeaAgent.retrieval_calls = 0
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    FakeGenerator.active_set_calls = 0
    FakeGenerator.max_active_set_calls = 0
    FakeGenerator.set_delay_seconds = 0.01
    monkeypatch.setenv("PRACTICE_QUIZ_FAST_KB_BATCH", "false")
    monkeypatch.setenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", "1")
    monkeypatch.setenv("PRACTICE_QUIZ_REMAINING_BATCH_SIZE", "1")
    monkeypatch.setenv("PRACTICE_QUIZ_REMAINING_CONCURRENCY", "2")
    monkeypatch.setenv("PRACTICE_QUIZ_STARTER_PAGE_SIZE", "1")
    coordinator = StubCoordinator(
        tmp_path,
        kb_name="tester-1__nce-2026",
        enable_idea_rag=True,
    )

    try:
        summary = asyncio.run(
            coordinator.generate_from_topic(
                user_topic="NCE review",
                preference="use the KB",
                num_questions=5,
                difficulty="medium",
                question_type="choice",
            )
        )
    finally:
        FakeGenerator.set_delay_seconds = 0.0

    assert summary["success"] is True
    assert len(summary["results"]) == 5
    assert FakeGenerator.single_calls == 1
    assert FakeGenerator.set_calls == 4
    assert FakeGenerator.max_active_set_calls == 2
    assert [item["qa_pair"]["question_id"] for item in summary["results"]] == [
        "q_1",
        "q_2",
        "q_3",
        "q_4",
        "q_5",
    ]


def test_kb_backed_progressive_first_batch_can_be_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeIdeaAgent.calls = 0
    FakeIdeaAgent.retrieval_calls = 0
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


def test_topic_quiz_can_skip_ideation_with_direct_templates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeGenerator.single_calls = 0
    FakeGenerator.set_calls = 0
    monkeypatch.setenv("PRACTICE_QUIZ_SKIP_IDEATION", "true")
    monkeypatch.delenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", raising=False)
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
