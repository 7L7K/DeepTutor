from __future__ import annotations

import pytest

from deeptutor.agents.question.agents.quiz_submission_agent import QuizSubmissionAgent


@pytest.fixture
def agent() -> QuizSubmissionAgent:
    return QuizSubmissionAgent(
        api_key="test",
        base_url="https://example.com",
        model="gpt-test",
        language="en",
    )


def test_quiz_submission_agent_finds_missing_question_numbers(agent: QuizSubmissionAgent) -> None:
    parsed = agent._parse_submitted_answers(
        submitted_answers="1a, 3-C 4D",
        question_count=4,
    )
    missing = agent._find_missing_question_numbers(
        parsed_answers=parsed,
        question_count=4,
    )
    assert missing == [2]
    assert parsed == {1: "a", 3: "C", 4: "D"}


def test_quiz_submission_agent_parses_compact_answer_lines(agent: QuizSubmissionAgent) -> None:
    parsed = agent._parse_submitted_answers(
        submitted_answers="1A2c 3-D 4:b",
        question_count=4,
    )

    assert parsed == {1: "A", 2: "c", 3: "D", 4: "b"}


@pytest.mark.asyncio
async def test_quiz_submission_agent_returns_missing_answer_prompt_without_llm(
    agent: QuizSubmissionAgent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def _unexpected_stream_llm(**_kwargs):
        nonlocal called
        called = True
        if False:
            yield ""

    monkeypatch.setattr(agent, "stream_llm", _unexpected_stream_llm)

    result = await agent.process(
        submitted_answers="1A",
        quiz_context={
            "title": "Practice quiz",
            "intro": "Answer all items.",
            "questions": [
                {"question_id": "q1", "question": "One?", "options": {"A": "Yes", "B": "No"}},
                {"question_id": "q2", "question": "Two?", "options": {"A": "Yes", "B": "No"}},
                {"question_id": "q3", "question": "Three?", "options": {"A": "Yes", "B": "No"}},
            ],
        },
    )

    assert called is False
    assert result["response"] == "I’m still missing answers for question(s): 2, 3. Please send just those missing items."
    assert result["structured_result"]["submission_state"] == "incomplete"
    assert result["structured_result"]["missing_question_numbers"] == [2, 3]


@pytest.mark.asyncio
async def test_quiz_submission_agent_normalizes_structured_result(
    agent: QuizSubmissionAgent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_stream_llm(**_kwargs):
        yield (
            '{"overall_summary":"Nice momentum overall.","question_results":['
            '{"question_id":"q1","correct_answer":"B","is_correct":false,'
            '"domain":"Helping Relationships","explanation":"Reflection of feeling names the emotion.",'
            '"coaching_note":"You mixed empathy with sympathy."},'
            '{"question_id":"q2","correct_answer":"B","is_correct":true,'
            '"domain":"Professional Orientation & Ethical Practice",'
            '"explanation":"Mandated reporting applies to suspected child abuse."}'
            ']}'
        )

    monkeypatch.setattr(agent, "stream_llm", _fake_stream_llm)

    result = await agent.process(
        submitted_answers="1A 2B",
        quiz_context={
            "title": "Practice quiz",
            "intro": "Answer all items.",
            "questions": [
                {
                    "question_id": "q1",
                    "question": "The counselor says, 'You feel overwhelmed.' What skill is this?",
                    "question_type": "choice",
                    "options": {"A": "Sympathy", "B": "Reflection of feeling"},
                },
                {
                    "question_id": "q2",
                    "question": "What should a counselor do after suspected child abuse is disclosed?",
                    "question_type": "choice",
                    "options": {"A": "Wait", "B": "Report"},
                },
            ],
        },
    )

    structured = result["structured_result"]
    assert structured["submission_state"] == "graded"
    assert structured["score"] == {"correct": 1, "total": 2, "percent": 50.0}
    assert structured["domain_breakdown"][0]["domain"] == "Helping Relationships"
    assert structured["question_results"][0]["user_answer"] == "A"
    assert structured["question_results"][0]["correct_answer"] == "B"
    assert structured["question_results"][0]["is_correct"] is False
    assert "Scored 1/2 (50%)" in result["response"]
    assert "Coach note: You mixed empathy with sympathy." in result["response"]


@pytest.mark.asyncio
async def test_quiz_submission_agent_allows_incomplete_grading_when_enabled(
    agent: QuizSubmissionAgent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_stream_llm(**_kwargs):
        yield (
            '{"overall_summary":"You answered one question and skipped one.","question_results":['
            '{"question_id":"q1","correct_answer":"B","is_correct":true,"is_answered":true,'
            '"domain":"Helping Relationships","explanation":"Reflection of feeling is the correct skill."},'
            '{"question_id":"q2","correct_answer":"B","is_correct":false,"is_answered":false,'
            '"domain":"Ethics","explanation":"A blank response is scored incorrect."}'
            ']}'
        )

    monkeypatch.setattr(agent, "stream_llm", _fake_stream_llm)

    result = await agent.process(
        submitted_answers="1B",
        quiz_context={
            "title": "Practice quiz",
            "intro": "Answer what you can.",
            "allow_incomplete": True,
            "questions": [
                {
                    "question_id": "q1",
                    "question": "The counselor reflects emotion. Which skill is this?",
                    "question_type": "choice",
                    "options": {"A": "Advice", "B": "Reflection"},
                },
                {
                    "question_id": "q2",
                    "question": "What is the mandated reporting response?",
                    "question_type": "choice",
                    "options": {"A": "Wait", "B": "Report"},
                },
            ],
        },
    )

    structured = result["structured_result"]
    assert structured["submission_state"] == "graded"
    assert structured["score"] == {"correct": 1, "total": 2, "percent": 50.0}
    assert structured["question_results"][1]["is_answered"] is False
    assert "No answer" in result["response"]
