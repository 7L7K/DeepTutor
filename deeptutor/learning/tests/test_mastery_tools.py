"""Tests for the Mastery Path tools — the seam between the chat-loop tutor and
the engine. They drive the full loop the tutor uses: build a path, read the
gate, pose + grade questions, assess qualitative objectives, with the active
path id injected server-side (never by the model)."""

from __future__ import annotations

import asyncio
import json

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.capabilities.mastery import tools as mastery_tools
from deeptutor.capabilities.mastery.tools import CourseMasteryReplyReceipt
from deeptutor.core.context import UnifiedContext
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.tools.mastery_tool import (
    MasteryAssessTool,
    MasteryBuildTool,
    MasteryGradeTool,
    MasteryQuizTool,
    MasteryStatusTool,
)


@pytest.fixture
def path_id(tmp_path, monkeypatch):
    """Point the LearningStore at a temp workspace and yield a stable path id."""
    monkeypatch.setattr(LearningStore, "__init__", _store_init_factory(tmp_path))
    return "test_path"


@pytest.fixture
def session_store(tmp_path, monkeypatch):
    store = SQLiteSessionStore(db_path=tmp_path / "chat.db")
    monkeypatch.setattr("deeptutor.services.session.get_sqlite_session_store", lambda: store)
    return store


def _store_init_factory(root):
    def _init(self, root_arg=None):  # mirrors LearningStore.__init__ signature
        from pathlib import Path

        self._root = Path(root) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    return _init


async def _build_basic(path_id):
    build = MasteryBuildTool()
    return await build.execute(
        _mastery_path_id=path_id,
        mode="replace",
        modules=[
            {
                "name": "Module 1",
                "knowledge_points": [
                    {"name": "Truth tables", "type": "memory"},
                    {"name": "Why XOR matters", "type": "concept"},
                ],
            }
        ],
    )


def _course_kwargs(pending, receipt=None, *, answer="forged"):
    kwargs = {
        "_mastery_path_id": "lp_crs_one",
        "_course_id": "crs_one",
        "_session_id": "session_one",
        "_turn_id": "turn_one",
        "answer": answer,
    }
    if receipt is not None:
        kwargs["_course_mastery_reply_receipt"] = receipt
    return kwargs


async def _course_quiz(path_id="lp_crs_one"):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    return await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=status["next"]["knowledge_point_id"],
        question="2+2?",
        expected_answer="4",
        question_type="short",
    )


def _mint_course_receipt(pipeline, service, *, answer="4", questions=None):
    pending = service.get_or_create("lp_crs_one").pending_question
    assert pending is not None
    return pipeline._mint_course_mastery_reply_receipt(
        context=UnifiedContext(
            session_id="session_one",
            metadata={
                "course_context": {"course_id": "crs_one"},
                "mastery_path_id": "lp_crs_one",
                "turn_id": "turn_one",
            },
        ),
        ask_user={
            "questions": questions
            if questions is not None
            else [{"id": "q1", "prompt": pending.prompt, "options": []}]
        },
        ask_tool_call_id="ask_call_one",
        reply_text=answer,
        answers=None,
    )


# ── build ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_creates_path(path_id):
    result = await _build_basic(path_id)
    assert result.success
    payload = json.loads(result.content)
    assert payload["knowledge_points_added"] == 2
    assert payload["map"]["counts"]["total"] == 2


@pytest.mark.asyncio
async def test_build_rejects_empty_modules(path_id):
    result = await MasteryBuildTool().execute(_mastery_path_id=path_id, modules=[])
    assert result.success is False


@pytest.mark.asyncio
async def test_build_append_keeps_existing(path_id):
    await _build_basic(path_id)
    result = await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        mode="append",
        modules=[
            {"name": "Module 2", "knowledge_points": [{"name": "Adders", "type": "procedure"}]}
        ],
    )
    payload = json.loads(result.content)
    assert payload["map"]["counts"]["total"] == 3  # 2 existing + 1 appended


@pytest.mark.asyncio
async def test_build_unknown_type_defaults_to_concept(path_id):
    result = await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        modules=[{"name": "M", "knowledge_points": [{"name": "Thing", "type": "nonsense"}]}],
    )
    kp = json.loads(result.content)["map"]["modules"][0]["knowledge_points"][0]
    assert kp["type"] == "concept"


# ── status ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_empty_path_asks_for_build(path_id):
    payload = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    assert payload["status"] == "empty"


@pytest.mark.asyncio
async def test_status_points_at_first_objective(path_id):
    await _build_basic(path_id)
    payload = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    assert payload["status"] == "active"
    assert payload["next"]["action"] == "probe"
    assert payload["next"]["knowledge_point_type"] == "memory"


@pytest.mark.asyncio
async def test_no_path_id_fails_closed():
    result = await MasteryStatusTool().execute(_mastery_path_id="")
    assert result.success is False


# ── quiz + grade: the deterministic objective gate ───────────────────────────


@pytest.mark.asyncio
async def test_quiz_then_grade_drives_memory_gate(path_id):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    quiz, grade = MasteryQuizTool(), MasteryGradeTool()
    mastered = False
    for _ in range(3):
        await quiz.execute(
            _mastery_path_id=path_id,
            knowledge_point_id=kp_id,
            question="2+2?",
            expected_answer="4",
            question_type="short",
        )
        result = json.loads((await grade.execute(_mastery_path_id=path_id, answer="4")).content)
        assert result["is_correct"] is True
        mastered = result["mastered"]
    # 0.5 -> 0.8 -> 1.0 ≥ 0.9: mastered only after the third correct answer.
    assert mastered is True


@pytest.mark.asyncio
async def test_grade_without_pending_fails(path_id):
    await _build_basic(path_id)
    result = await MasteryGradeTool().execute(_mastery_path_id=path_id, answer="x")
    assert result.success is False


@pytest.mark.asyncio
async def test_quiz_unknown_kp_fails(path_id):
    await _build_basic(path_id)
    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id="nope",
        question="?",
        expected_answer="x",
    )
    assert result.success is False


@pytest.mark.asyncio
async def test_wrong_answer_does_not_master(path_id):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]
    await MasteryQuizTool().execute(
        _mastery_path_id=path_id, knowledge_point_id=kp_id, question="2+2?", expected_answer="4"
    )
    result = json.loads(
        (await MasteryGradeTool().execute(_mastery_path_id=path_id, answer="5")).content
    )
    assert result["is_correct"] is False
    assert result["mastered"] is False


@pytest.mark.asyncio
async def test_course_grade_without_reply_receipt_has_no_mutation(path_id, monkeypatch):
    service = LearningService(LearningStore())
    monkeypatch.setattr(mastery_tools, "_new_service", lambda _path_id: service)
    await _course_quiz()
    before = service.get_or_create("lp_crs_one")
    assert before.pending_question is not None
    version = before.version

    result = await MasteryGradeTool().execute(**_course_kwargs(before.pending_question, answer="4"))

    assert result.success is False
    after = service.get_or_create("lp_crs_one")
    assert after.version == version
    assert after.pending_question is not None
    assert after.quiz_attempts == []


@pytest.mark.asyncio
async def test_course_grade_uses_paused_reply_not_forged_model_answer(path_id, monkeypatch):
    service = LearningService(LearningStore())
    monkeypatch.setattr(mastery_tools, "_new_service", lambda _path_id: service)
    await _course_quiz()
    pipeline = AgenticChatPipeline(language="en")
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline._new_service", lambda _path_id: service
    )

    receipt = _mint_course_receipt(pipeline, service, answer="4")
    assert receipt is not None
    correct = json.loads(
        (
            await MasteryGradeTool().execute(
                **_course_kwargs(service.get_or_create("lp_crs_one").pending_question, receipt, answer="5")
            )
        ).content
    )
    assert correct["is_correct"] is True
    assert receipt.consumed is True

    await _course_quiz()
    wrong_receipt = _mint_course_receipt(pipeline, service, answer="5")
    assert wrong_receipt is not None
    wrong = json.loads(
        (
            await MasteryGradeTool().execute(
                **_course_kwargs(
                    service.get_or_create("lp_crs_one").pending_question,
                    wrong_receipt,
                    answer="4",
                )
            )
        ).content
    )
    assert wrong["is_correct"] is False


@pytest.mark.asyncio
async def test_course_receipt_rejects_mismatch_and_is_one_use(path_id, monkeypatch):
    service = LearningService(LearningStore())
    monkeypatch.setattr(mastery_tools, "_new_service", lambda _path_id: service)
    await _course_quiz()
    pipeline = AgenticChatPipeline(language="en")
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline._new_service", lambda _path_id: service
    )
    receipt = _mint_course_receipt(pipeline, service)
    assert receipt is not None
    receipt.pending_question_id = "wrong_question"
    mismatch = await MasteryGradeTool().execute(
        **_course_kwargs(service.get_or_create("lp_crs_one").pending_question, receipt)
    )
    assert mismatch.success is False
    assert service.get_or_create("lp_crs_one").quiz_attempts == []

    receipt.pending_question_id = service.get_or_create("lp_crs_one").pending_question.question_id
    first = await MasteryGradeTool().execute(
        **_course_kwargs(service.get_or_create("lp_crs_one").pending_question, receipt)
    )
    assert first.success is True
    assert receipt.consumed is True
    second = await MasteryGradeTool().execute(**_course_kwargs(None, receipt))
    assert second.success is False
    assert len(service.get_or_create("lp_crs_one").quiz_attempts) == 1


@pytest.mark.asyncio
async def test_course_receipt_rejects_parallel_duplicate_grades(path_id, monkeypatch):
    service = LearningService(LearningStore())
    monkeypatch.setattr(mastery_tools, "_new_service", lambda _path_id: service)
    await _build_basic("lp_crs_one")
    status = json.loads(
        (await MasteryStatusTool().execute(_mastery_path_id="lp_crs_one")).content
    )
    await MasteryQuizTool().execute(
        _mastery_path_id="lp_crs_one",
        knowledge_point_id=status["next"]["knowledge_point_id"],
        question="2+2?",
        expected_answer="A",
        question_type="choice",
        options=["A: four", "B: five"],
    )
    pending = service.get_or_create("lp_crs_one").pending_question
    assert pending is not None
    receipt = CourseMasteryReplyReceipt(
        version=1,
        course_id="crs_one",
        mastery_path_id="lp_crs_one",
        session_id="session_one",
        turn_id="turn_one",
        pending_question_id=pending.question_id,
        ask_tool_call_id="ask_call_one",
        ask_question_id="q1",
        actual_answer_text="A",
    )

    async def _slow_choice(*_args):
        await asyncio.sleep(0)
        return {"A": "four", "B": "five"}, "A"

    monkeypatch.setattr(mastery_tools, "_resolve_pending_choice", _slow_choice)
    kwargs = _course_kwargs(pending, receipt, answer="B")
    first, second = await asyncio.gather(
        MasteryGradeTool().execute(**kwargs), MasteryGradeTool().execute(**kwargs)
    )

    assert sorted([first.success, second.success]) == [False, True]
    assert receipt.consumed is True
    assert len(service.get_or_create("lp_crs_one").quiz_attempts) == 1


@pytest.mark.asyncio
async def test_course_receipt_retries_once_after_real_store_save_failure(path_id, monkeypatch):
    store = LearningStore()
    service = LearningService(store)
    monkeypatch.setattr(mastery_tools, "_new_service", lambda _path_id: service)
    await _course_quiz()
    pipeline = AgenticChatPipeline(language="en")
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline._new_service", lambda _path_id: service
    )
    receipt = _mint_course_receipt(pipeline, service)
    assert receipt is not None

    original_save = service.save

    def _save_failure(_progress):
        raise RuntimeError("simulated durable save failure")

    monkeypatch.setattr(service, "save", _save_failure)
    with pytest.raises(RuntimeError, match="durable save failure"):
        await MasteryGradeTool().execute(
            **_course_kwargs(service.get_or_create("lp_crs_one").pending_question, receipt)
        )

    assert receipt.consumed is False
    assert receipt.redeeming is False
    failed_state = store.load("lp_crs_one")
    assert failed_state is not None
    assert failed_state.pending_question is not None
    assert failed_state.quiz_attempts == []

    monkeypatch.setattr(service, "save", original_save)
    retry = await MasteryGradeTool().execute(
        **_course_kwargs(service.get_or_create("lp_crs_one").pending_question, receipt)
    )

    assert retry.success is True
    assert receipt.consumed is True
    durable_state = store.load("lp_crs_one")
    assert durable_state is not None
    assert durable_state.pending_question is None
    assert len(durable_state.quiz_attempts) == 1


@pytest.mark.asyncio
async def test_course_receipt_requires_single_nonempty_matching_card_reply(path_id, monkeypatch):
    service = LearningService(LearningStore())
    monkeypatch.setattr(mastery_tools, "_new_service", lambda _path_id: service)
    await _course_quiz()
    pipeline = AgenticChatPipeline(language="en")
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline._new_service", lambda _path_id: service
    )

    assert _mint_course_receipt(
        pipeline,
        service,
        questions=[
            {"id": "q1", "prompt": "2+2?", "options": []},
            {"id": "q2", "prompt": "Another?", "options": []},
        ],
    ) is None
    assert _mint_course_receipt(pipeline, service, answer="   ") is None
    assert _mint_course_receipt(
        pipeline,
        service,
        questions=[{"id": "q1", "prompt": "different", "options": []}],
    ) is None
    receipt = _mint_course_receipt(pipeline, service)
    assert receipt is not None
    with pytest.raises(TypeError):
        json.dumps(receipt)


@pytest.mark.asyncio
async def test_course_quiz_preserves_pending_and_rejects_qualitative_objectives(path_id, monkeypatch):
    service = LearningService(LearningStore())
    monkeypatch.setattr(mastery_tools, "_new_service", lambda _path_id: service)
    await _course_quiz()
    pending = service.get_or_create("lp_crs_one").pending_question
    assert pending is not None

    overwrite = await MasteryQuizTool().execute(
        _mastery_path_id="lp_crs_one",
        knowledge_point_id=pending.knowledge_point_id,
        question="replacement?",
        expected_answer="x",
    )
    assert overwrite.success is False
    assert service.get_or_create("lp_crs_one").pending_question.question_id == pending.question_id

    status = json.loads(
        (await MasteryStatusTool().execute(_mastery_path_id="lp_crs_one", _course_id="crs_one")).content
    )
    assert status["pending_question"] == {
        "prompt": "2+2?",
        "question_type": "short",
        "options": [],
    }
    assert "expected_answer" not in json.dumps(status)

    service.clear_pending_question(service.get_or_create("lp_crs_one"))
    concept_id = service.get_or_create("lp_crs_one").modules[0].knowledge_points[1].id
    qualitative = await MasteryQuizTool().execute(
        _mastery_path_id="lp_crs_one",
        knowledge_point_id=concept_id,
        question="Explain XOR",
        expected_answer="an exclusive OR operation",
    )
    assert qualitative.success is False
    assert service.get_or_create("lp_crs_one").pending_question is None


@pytest.mark.asyncio
async def test_grade_syncs_mastery_attempt_to_question_bank(path_id, session_store):
    session = await session_store.create_session(title="Mastery Session")
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]
    await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="2+2?",
        expected_answer="4",
        question_type="short",
    )

    result = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                _session_id=session["id"],
                _turn_id="turn_mastery_1",
                answer="5",
            )
        ).content
    )

    assert result["is_correct"] is False
    wrong_entries = await session_store.list_notebook_entries(is_correct=False)
    assert wrong_entries["total"] == 1
    entry = wrong_entries["items"][0]
    assert entry["session_title"] == "Mastery Session"
    assert entry["turn_id"] == "turn_mastery_1"
    assert entry["question"] == "2+2?"
    assert entry["question_type"] == "short_answer"
    assert entry["user_answer"] == "5"
    assert entry["correct_answer"] == "4"
    assert entry["is_correct"] is False


@pytest.mark.asyncio
async def test_choice_quiz_rejects_bare_option_labels(path_id):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Which order is correct?",
        expected_answer="A",
        question_type="choice",
        options=["A", "B", "C", "D"],
    )

    assert result.success is False
    assert "full option bodies" in result.content


@pytest.mark.asyncio
async def test_choice_quiz_preserves_bodies_and_normalizes_answer(path_id, session_store):
    session = await session_store.create_session(title="Choice Mastery")
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    quiz = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Where is the stop condition added?",
        expected_answer="Step 6",
        question_type="choice",
        options=[
            "A: Step 2 — write the first tool",
            "B: Step 4 — test one call",
            "C: Step 6 — add the stop condition",
            "D: Step 7 — add another tool",
        ],
    )
    assert quiz.success is True

    grade = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                _session_id=session["id"],
                _turn_id="turn_choice_1",
                answer="C",
            )
        ).content
    )
    assert grade["is_correct"] is True

    entries = await session_store.list_notebook_entries()
    entry = entries["items"][0]
    assert entry["options"] == {
        "A": "Step 2 — write the first tool",
        "B": "Step 4 — test one call",
        "C": "Step 6 — add the stop condition",
        "D": "Step 7 — add another tool",
    }
    assert entry["correct_answer"] == "C"
    assert entry["user_answer"] == "C"
    assert entry["is_correct"] is True


# ── assess: the qualitative gate ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assess_passes_concept(path_id):
    await _build_basic(path_id)
    # Drive past the memory objective so status reaches the concept one.
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    mem_kp = status["next"]["knowledge_point_id"]
    for _ in range(3):
        await MasteryQuizTool().execute(
            _mastery_path_id=path_id, knowledge_point_id=mem_kp, question="q", expected_answer="a"
        )
        await MasteryGradeTool().execute(_mastery_path_id=path_id, answer="a")

    status2 = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    concept_kp = status2["next"]["knowledge_point_id"]
    assert status2["next"]["action"] == "probe"
    assert status2["next"]["knowledge_point_type"] == "concept"

    result = json.loads(
        (
            await MasteryAssessTool().execute(
                _mastery_path_id=path_id, knowledge_point_id=concept_kp, passed=True, feedback="ok"
            )
        ).content
    )
    assert result["mastered"] is True
    assert result["next"]["action"] == "complete"


@pytest.mark.asyncio
async def test_assess_rejects_quantitative_type(path_id):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    mem_kp = status["next"]["knowledge_point_id"]  # a memory objective
    result = await MasteryAssessTool().execute(
        _mastery_path_id=path_id, knowledge_point_id=mem_kp, passed=True
    )
    assert result.success is False
