"""Focused C3-H2 contracts for bounded short answers and single choice."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.courses.assessment_grading import grade_assessment_response
from deeptutor.courses.attempt_repository import CourseAssessmentRepository
from deeptutor.courses.attempt_service import CourseAssessmentService
from deeptutor.courses.grading_repository import CourseGradingRepository
from deeptutor.courses.grading_service import CourseGradingService
from deeptutor.courses.mastery_adapter import CourseMasteryAdapter
from deeptutor.courses.migrations import runner
from deeptutor.courses.migrations.runner import ensure_course_schema
from deeptutor.courses.practice_models import (
    BoundedShortAnswerContract,
    SingleChoiceAnswerContract,
    SingleChoiceOption,
)
from deeptutor.courses.practice_repository import CoursePracticeRepository
from deeptutor.courses.practice_service import CoursePracticeService
from deeptutor.courses.repository import CourseConflictError, CourseRepository
from deeptutor.learning.models import (
    ErrorType,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
)
from deeptutor.learning.storage import LearningStore


REFERENCE_ROOT = Path(__file__).resolve().parents[3] / "evals/reference_course"
BOUNDED_AMENDMENT_PATH = (
    REFERENCE_ROOT
    / "reviewer_amendments/obj-resp-01-bounded-short-answer-v2.json"
)
BOUNDED_AMENDMENT = json.loads(BOUNDED_AMENDMENT_PATH.read_text(encoding="utf-8"))
BOUNDED_CONTRACT = BOUNDED_AMENDMENT["candidate_answer_contract"]

# Exact manual runtime projection of OBJ-RESP-02 v3. Evaluation-only role,
# entailed-claim, defect, and provider-qualification metadata is not persisted.
CHOICE_PROMPT = (
    "Which statement correctly describes both what oxygen accepts and forms at the "
    "end of the aerobic electron transport chain and why its terminal-acceptor role "
    "matters?"
)
CHOICE_OPTIONS = [
    {
        "option_id": "opt_resp02_correct",
        "text": (
            "Oxygen accepts electrons and protons to form water; as the final "
            "acceptor, it allows electron flow through the chain to continue."
        ),
    },
    {
        "option_id": "opt_resp02_wrong_product",
        "text": (
            "Oxygen accepts electrons and protons to form ATP; as the final "
            "acceptor, it allows electron flow through the chain to continue."
        ),
    },
    {
        "option_id": "opt_resp02_wrong_flow",
        "text": (
            "Oxygen accepts electrons and protons to form water; as the final "
            "acceptor, it causes electron flow through the chain to stop."
        ),
    },
    {
        "option_id": "opt_resp02_wrong_input",
        "text": (
            "Oxygen accepts ATP and protons to form water; as the final acceptor, "
            "it allows electron flow through the chain to continue."
        ),
    },
]
CHOICE_CONTRACT = {
    "kind": "single_choice_v1",
    "correct_option_id": "opt_resp02_correct",
}
CHOICE_CORRECT_TEXT = CHOICE_OPTIONS[0]["text"]
CHOICE_WRONG_PRODUCT_TEXT = CHOICE_OPTIONS[1]["text"]
CHOICE_WRONG_FLOW_TEXT = CHOICE_OPTIONS[2]["text"]
OPAQUE_OPTION_ID = re.compile(r"opt_[0-9a-f]{32}\Z")
SQL_CHOICE_OPTIONS = [
    {"option_id": f"opt_{index:032x}", "text": option["text"]}
    for index, option in enumerate(CHOICE_OPTIONS, start=1)
]
SQL_CHOICE_CONTRACT = {
    "kind": "single_choice_v1",
    "correct_option_id": SQL_CHOICE_OPTIONS[0]["option_id"],
}


def _choice_id(question: Any, text: str) -> str:
    return next(option.option_id for option in question.options if option.text == text)


def _choice_payload(question: Any) -> list[dict[str, str]]:
    return [option.model_dump(mode="json") for option in question.options]


def _services(tmp_path: Path):
    courses = CourseRepository(tmp_path / "courses.db", "u_alice")
    practice = CoursePracticeService(CoursePracticeRepository(courses))
    attempts = CourseAssessmentService(CourseAssessmentRepository(courses))
    grading = CourseGradingRepository(courses)
    return courses, practice, attempts, grading


def _epoch(courses: CourseRepository, course_id: str) -> int:
    return courses.get_course(course_id).write_epoch


def _build_mixed_assessment(tmp_path: Path):
    courses, practice, attempts, grading = _services(tmp_path)
    course = courses.create_course("Cellular respiration")
    practice_set = practice.create_practice_set(
        course.id,
        title="Bounded assessment",
        expected_course_write_epoch=course.write_epoch,
    )
    revision = practice.create_draft_revision(
        course.id,
        practice_set.id,
        expected_course_write_epoch=course.write_epoch,
    )
    short_question = practice.add_question(
        course.id,
        practice_set.id,
        revision.id,
        question_type="short_answer",
        prompt=(
            "What conversion during pyruvate oxidation links glycolysis-derived "
            "pyruvate to the citric acid cycle?"
        ),
        answer_contract=BOUNDED_CONTRACT,
        explanation=(
            "Pyruvate oxidation converts pyruvate to acetyl-CoA before the citric "
            "acid cycle."
        ),
        objective_ids=("OBJ-RESP-01",),
        ordinal=1,
        expected_course_write_epoch=course.write_epoch,
    )
    choice_question = practice.add_question(
        course.id,
        practice_set.id,
        revision.id,
        question_type="single_choice",
        prompt=CHOICE_PROMPT,
        options=CHOICE_OPTIONS,
        answer_contract=CHOICE_CONTRACT,
        explanation=(
            "Oxygen accepts electrons and protons to form water, allowing electron "
            "flow to continue."
        ),
        objective_ids=("OBJ-RESP-02",),
        ordinal=2,
        expected_course_write_epoch=course.write_epoch,
    )
    practice.ready_revision(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=course.write_epoch,
    )
    practice_set = practice.get_practice_set(course.id, practice_set.id)
    return (
        courses,
        practice,
        attempts,
        grading,
        course,
        practice_set,
        revision,
        short_question,
        choice_question,
    )


def _start_mixed(tmp_path: Path):
    values = _build_mixed_assessment(tmp_path)
    courses, _practice, attempts, _grading, course, practice_set, revision, *_ = values
    view = attempts.start_or_resume_attempt(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=_epoch(courses, course.id),
        expected_practice_set_write_epoch=practice_set.write_epoch,
    )
    return (*values, view)


def _canonical_sha256(value: str) -> str:
    canonical = json.dumps(
        json.loads(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_obj_resp_01_bounded_amendment_is_human_reviewed_and_successor_only() -> None:
    retained_path = (
        REFERENCE_ROOT
        / "reviewer_amendments/obj-resp-01-answer-variants-v1.json"
    )
    retained = json.loads(retained_path.read_text(encoding="utf-8"))

    assert BOUNDED_AMENDMENT["status"] == "APPROVED_HUMAN_REVIEWED"
    assert BOUNDED_AMENDMENT["reviewer"] == "King"
    assert BOUNDED_AMENDMENT["reviewed_at"] == "2026-08-09T21:33:40Z"
    assert len(BOUNDED_AMENDMENT["signature"]) == 64
    assert BOUNDED_AMENDMENT["signature_version"] == (
        "c3-canonical-review-payload-sha256-v1"
    )
    assert BOUNDED_AMENDMENT["agent_authority"] == "NON_DECISION_RECOMMENDATION"
    assert BOUNDED_AMENDMENT["supersedes_amendment_id"] == retained["amendment_id"]
    assert BOUNDED_AMENDMENT["superseded_amendment_sha256"] == hashlib.sha256(
        retained_path.read_bytes()
    ).hexdigest()
    assert BOUNDED_CONTRACT == BOUNDED_AMENDMENT["candidate_answer_contract"]
    assert "successor immutable Practice revision" in BOUNDED_AMENDMENT[
        "application_policy"
    ]


@pytest.mark.parametrize(
    ("answer", "correct"),
    [
        (
            "Pyruvate is converted to acetyl-CoA.",
            True,
        ),
        (
            "Pyruvate is converted to acetyl-CoA",
            True,
        ),
        (
            "PYRUVATE IS CONVERTED TO ACETYL-COA!",
            True,
        ),
        (
            "  Pyruvate\t is   converted to acetyl-CoA.  ",
            True,
        ),
        (
            "Pyruvate is converted to acetyl—CoA.",
            True,
        ),
        (
            "Conversion of pyruvate to acetyl-CoA.",
            True,
        ),
        (
            "Acetyl-CoA is converted to pyruvate.",
            False,
        ),
        (
            "Pyruvate is converted to lactate.",
            False,
        ),
        ("Pyruvate is converted.", False),
        ("", False),
    ],
    ids=[
        "canonical",
        "terminal-punctuation-missing",
        "case",
        "outer-and-internal-whitespace",
        "unicode-dash",
        "explicit-paraphrase",
        "wrong-reversal",
        "wrong-molecule",
        "incomplete",
        "blank",
    ],
)
def test_bounded_short_answer_v1_normalization_matrix(
    answer: str, correct: bool
) -> None:
    contract = BoundedShortAnswerContract.model_validate(BOUNDED_CONTRACT)

    decision = grade_assessment_response({"answer": answer}, contract, [])

    assert decision.is_correct is correct
    assert decision.error_type == (
        None if correct else ("metacognitive" if not answer.strip() else "application")
    )


def test_contract_shape_pairing_and_single_choice_order_are_stable(
    tmp_path: Path,
) -> None:
    reference = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "evals/reference_course/assessment_contracts_v3_evaluation_only.json"
        ).read_text(encoding="utf-8")
    )
    obj_resp_02 = next(
        item for item in reference["contracts"] if item["objective_id"] == "OBJ-RESP-02"
    )
    assert CHOICE_PROMPT == obj_resp_02["stem_contract"]
    assert CHOICE_CONTRACT["correct_option_id"] == obj_resp_02["correct_option_id"]
    assert CHOICE_OPTIONS == [
        {"option_id": item["option_id"], "text": item["text"]}
        for item in obj_resp_02["options"]
    ]
    assert all(set(item) == {"option_id", "text"} for item in CHOICE_OPTIONS)

    courses, practice, attempts, _grading = _services(tmp_path)
    course = courses.create_course("Biology")
    practice_set = practice.create_practice_set(
        course.id,
        title="Pairing",
        expected_course_write_epoch=course.write_epoch,
    )
    revision = practice.create_draft_revision(
        course.id,
        practice_set.id,
        expected_course_write_epoch=course.write_epoch,
    )

    with pytest.raises(ValueError, match="short-answer|single-choice"):
        practice.add_question(
            course.id,
            practice_set.id,
            revision.id,
            question_type="single_choice",
            prompt="Mismatched bounded question",
            answer_contract=BOUNDED_CONTRACT,
            expected_course_write_epoch=course.write_epoch,
        )
    with pytest.raises(ValueError, match="short-answer|single-choice"):
        practice.add_question(
            course.id,
            practice_set.id,
            revision.id,
            question_type="short_answer",
            prompt="Mismatched choice question",
            options=CHOICE_OPTIONS,
            answer_contract=CHOICE_CONTRACT,
            expected_course_write_epoch=course.write_epoch,
        )

    question = practice.add_question(
        course.id,
        practice_set.id,
        revision.id,
        question_type="single_choice",
        prompt=CHOICE_PROMPT,
        options=CHOICE_OPTIONS,
        answer_contract=CHOICE_CONTRACT,
        expected_course_write_epoch=course.write_epoch,
    )
    practice.ready_revision(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=course.write_epoch,
    )
    practice_set = practice.get_practice_set(course.id, practice_set.id)
    assert practice_set.mode == "manual"
    assert practice.get_revision(
        course.id, practice_set.id, revision.id
    ).generation_receipt is None
    reloaded = practice.list_questions(course.id, practice_set.id, revision.id)[0]
    authored_ids = [item["option_id"] for item in CHOICE_OPTIONS]
    authored_texts = [item["text"] for item in CHOICE_OPTIONS]
    expected_ids = [item.option_id for item in reloaded.options]
    persisted_texts = [item.text for item in reloaded.options]
    assert all(OPAQUE_OPTION_ID.fullmatch(option_id) for option_id in expected_ids)
    assert set(expected_ids).isdisjoint(authored_ids)
    assert set(persisted_texts) == set(authored_texts)
    assert persisted_texts != authored_texts
    assert persisted_texts[0] != authored_texts[0]
    assert reloaded.answer_contract.correct_option_id == _choice_id(
        reloaded, CHOICE_CORRECT_TEXT
    )
    assert reloaded.options[0].option_id != reloaded.answer_contract.correct_option_id
    persisted_ids = expected_ids + [reloaded.answer_contract.correct_option_id]
    assert not any(
        token in option_id
        for option_id in persisted_ids
        for token in ("correct", "wrong", "resp02", "answer")
    )

    with courses._connect() as conn:
        stored = conn.execute(
            "SELECT options_json, answer_contract_json FROM practice_questions WHERE id = ?",
            (question.id,),
        ).fetchone()
    assert all(imported_id not in stored[0] for imported_id in authored_ids)
    assert all(imported_id not in stored[1] for imported_id in authored_ids)

    view = attempts.start_or_resume_attempt(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=course.write_epoch,
        expected_practice_set_write_epoch=practice_set.write_epoch,
    )
    assert view.items[0].question_id == question.id
    assert set(view.items[0].option_order or []) == set(expected_ids)
    assert view.items[0].option_order != expected_ids
    assert view.items[0].option_order[0] != expected_ids[0]
    refreshed = attempts.get_attempt(
        course.id, practice_set.id, view.attempt.id
    )
    assert refreshed.items[0].option_order == view.items[0].option_order
    with courses._connect() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE practice_questions SET question_type = 'short_answer' WHERE id = ?",
            (question.id,),
        )


@pytest.mark.parametrize(
    "role_bearing_id",
    [
        "opt_resp02_correct",
        "opt_000000000000000000000000000wrong",
        "opt_ABCDEF0123456789ABCDEF0123456789",
    ],
)
def test_stored_single_choice_models_reject_role_bearing_or_noncanonical_ids(
    role_bearing_id: str,
) -> None:
    with pytest.raises(ValueError, match="canonical opaque option format"):
        SingleChoiceOption(option_id=role_bearing_id, text="Choice")
    with pytest.raises(ValueError, match="canonical opaque option format"):
        SingleChoiceAnswerContract(
            kind="single_choice_v1", correct_option_id=role_bearing_id
        )


def test_managed_sqlite_rejects_role_bearing_option_authority(tmp_path: Path) -> None:
    courses, practice, _attempts, _grading = _services(tmp_path)
    course = courses.create_course("Opaque option authority")
    practice_set = practice.create_practice_set(
        course.id,
        title="Managed option identities",
        expected_course_write_epoch=course.write_epoch,
    )
    revision = practice.create_draft_revision(
        course.id,
        practice_set.id,
        expected_course_write_epoch=course.write_epoch,
    )

    options_json = json.dumps(CHOICE_OPTIONS, separators=(",", ":"))
    contract_json = json.dumps(CHOICE_CONTRACT, separators=(",", ":"))
    with courses._connect() as conn:
        assert conn.execute(
            "SELECT teeechr_question_contract_valid('single_choice', ?, ?)",
            (contract_json, options_json),
        ).fetchone()[0] == 0
        with pytest.raises(
            sqlite3.IntegrityError,
            match="practice question answer contract is invalid",
        ):
            conn.execute(
                """INSERT INTO practice_questions
                   (id, practice_set_revision_id, question_type, prompt, options_json,
                    answer_contract_json, explanation, objective_ids_json, citation_json,
                    ordinal, created_at)
                   VALUES ('qst_role_bearing', ?, 'single_choice', 'Leaky IDs', ?, ?,
                           '', '[]', '[]', 1, 1)""",
                (revision.id, options_json, contract_json),
            )


@pytest.mark.parametrize(
    ("question_type", "contract", "options"),
    [
        (
            "short_answer",
            {
                **BOUNDED_CONTRACT,
                "accepted_normalized_answers": [
                    *BOUNDED_CONTRACT["accepted_normalized_answers"],
                    BOUNDED_CONTRACT["accepted_normalized_answers"][0],
                ],
            },
            [],
        ),
        (
            "single_choice",
            SQL_CHOICE_CONTRACT,
            [
                SQL_CHOICE_OPTIONS[0],
                {**SQL_CHOICE_OPTIONS[1], "text": SQL_CHOICE_OPTIONS[0]["text"]},
            ],
        ),
    ],
    ids=["bounded-duplicate-normalized-answer", "choice-duplicate-normalized-text"],
)
def test_managed_sqlite_rejects_malformed_new_question_contracts(
    tmp_path: Path,
    question_type: str,
    contract: dict[str, Any],
    options: list[dict[str, str]],
) -> None:
    courses, practice, _attempts, _grading = _services(tmp_path)
    course = courses.create_course("Malformed contracts")
    practice_set = practice.create_practice_set(
        course.id,
        title="Managed validation",
        expected_course_write_epoch=course.write_epoch,
    )
    revision = practice.create_draft_revision(
        course.id,
        practice_set.id,
        expected_course_write_epoch=course.write_epoch,
    )

    with courses._connect() as conn, pytest.raises(
        sqlite3.IntegrityError,
        match="practice question answer contract is invalid",
    ):
        conn.execute(
            """INSERT INTO practice_questions
               (id, practice_set_revision_id, question_type, prompt, options_json,
                answer_contract_json, explanation, objective_ids_json, citation_json,
                ordinal, created_at)
               VALUES (?, ?, ?, 'Malformed question', ?, ?, '', '[]', '[]', 1, 1)""",
            (
                f"qst_malformed_{question_type}",
                revision.id,
                question_type,
                json.dumps(options, separators=(",", ":")),
                json.dumps(contract, separators=(",", ":")),
            ),
        )


@pytest.mark.parametrize(
    ("question_type", "contract", "options"),
    [
        ("short_answer", BOUNDED_CONTRACT, []),
        ("single_choice", SQL_CHOICE_CONTRACT, SQL_CHOICE_OPTIONS),
    ],
    ids=["bounded", "choice"],
)
def test_unmanaged_sqlite_authoring_of_valid_new_contract_fails_without_udf(
    tmp_path: Path,
    question_type: str,
    contract: dict[str, Any],
    options: list[dict[str, str]],
) -> None:
    courses, practice, _attempts, _grading = _services(tmp_path)
    course = courses.create_course("Unmanaged authoring")
    practice_set = practice.create_practice_set(
        course.id,
        title="Fail closed",
        expected_course_write_epoch=course.write_epoch,
    )
    revision = practice.create_draft_revision(
        course.id,
        practice_set.id,
        expected_course_write_epoch=course.write_epoch,
    )

    with sqlite3.connect(courses.db_path) as conn, pytest.raises(
        sqlite3.OperationalError,
        match="no such function: teeechr_question_contract_valid",
    ):
        conn.execute(
            """INSERT INTO practice_questions
               (id, practice_set_revision_id, question_type, prompt, options_json,
                answer_contract_json, explanation, objective_ids_json, citation_json,
                ordinal, created_at)
               VALUES (?, ?, ?, 'Valid new contract', ?, ?, '', '[]', '[]', 1, 1)""",
            (
                f"qst_unmanaged_{question_type}",
                revision.id,
                question_type,
                json.dumps(options, separators=(",", ":")),
                json.dumps(contract, separators=(",", ":")),
            ),
        )


def test_mixed_short_and_choice_attempt_autosaves_and_resumes(
    tmp_path: Path,
) -> None:
    (
        courses,
        _practice,
        attempts,
        _grading,
        course,
        practice_set,
        revision,
        short_question,
        choice_question,
        view,
    ) = _start_mixed(tmp_path)
    items = {item.question_id: item for item in view.items}
    correct_option_id = _choice_id(choice_question, CHOICE_CORRECT_TEXT)
    attempts.autosave_answer(
        course.id,
        practice_set.id,
        view.attempt.id,
        items[short_question.id].id,
        response={
            "answer": " Pyruvate is converted to acetyl—CoA! "
        },
        expected_answer_revision=1,
        idempotency_token="mixed-short-answer",
        expected_course_write_epoch=course.write_epoch,
        expected_practice_set_write_epoch=practice_set.write_epoch,
    )
    attempts.autosave_answer(
        course.id,
        practice_set.id,
        view.attempt.id,
        items[choice_question.id].id,
        response={"option_id": correct_option_id},
        expected_answer_revision=1,
        idempotency_token="mixed-choice-answer",
        expected_course_write_epoch=course.write_epoch,
        expected_practice_set_write_epoch=practice_set.write_epoch,
    )

    reopened_courses = CourseRepository(courses.db_path, "u_alice")
    reopened_attempts = CourseAssessmentService(
        CourseAssessmentRepository(reopened_courses)
    )
    resumed = reopened_attempts.start_or_resume_attempt(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=course.write_epoch,
        expected_practice_set_write_epoch=practice_set.write_epoch,
    )

    assert resumed.attempt.id == view.attempt.id
    assert {answer.attempt_item_id: answer.response for answer in resumed.answers} == {
        items[short_question.id].id: {
            "answer": " Pyruvate is converted to acetyl—CoA! "
        },
        items[choice_question.id].id: {"option_id": correct_option_id},
    }
    resumed_items = {item.question_id: item for item in resumed.items}
    assert resumed_items[choice_question.id].option_order == items[
        choice_question.id
    ].option_order


def test_missing_answer_row_blocks_repository_and_sql_submit_and_partial_grade(
    tmp_path: Path,
) -> None:
    (
        courses,
        _practice,
        attempts,
        grading,
        course,
        practice_set,
        _revision,
        short_question,
        choice_question,
        view,
    ) = _start_mixed(tmp_path)
    items = {item.question_id: item for item in view.items}
    attempts.autosave_answer(
        course.id,
        practice_set.id,
        view.attempt.id,
        items[short_question.id].id,
        response={"answer": "Pyruvate is converted to acetyl-CoA."},
        expected_answer_revision=1,
        idempotency_token="complete-first-item-only",
        expected_course_write_epoch=course.write_epoch,
        expected_practice_set_write_epoch=practice_set.write_epoch,
    )

    with courses._connect() as conn:
        answer_retention_trigger = conn.execute(
            """SELECT sql FROM sqlite_master
               WHERE type = 'trigger' AND name = 'quiz_attempt_answers_no_delete'"""
        ).fetchone()[0]
        conn.execute("DROP TRIGGER quiz_attempt_answers_no_delete")
        conn.execute(
            "DELETE FROM quiz_attempt_answers WHERE attempt_item_id = ?",
            (items[choice_question.id].id,),
        )
        conn.execute(answer_retention_trigger)

    with pytest.raises(
        CourseConflictError,
        match="requires every answer before submission",
    ):
        attempts.submit_attempt(
            course.id,
            practice_set.id,
            view.attempt.id,
            expected_course_write_epoch=course.write_epoch,
            expected_practice_set_write_epoch=practice_set.write_epoch,
        )

    with courses._connect() as conn, pytest.raises(
        sqlite3.IntegrityError,
        match="requires every answer before submission",
    ):
        conn.execute(
            """UPDATE quiz_attempts
               SET state = 'submitted', submitted_at = started_at + 1,
                   revision = revision + 1, updated_at = started_at + 1
               WHERE id = ?""",
            (view.attempt.id,),
        )

    # Build a retained malformed submitted fixture by bypassing only the new
    # completeness trigger, then restore it before exercising grade authority.
    with courses._connect() as conn:
        completeness_trigger = conn.execute(
            """SELECT sql FROM sqlite_master
               WHERE type = 'trigger'
                 AND name = 'quiz_attempts_submit_requires_complete_answers'"""
        ).fetchone()[0]
        conn.execute("DROP TRIGGER quiz_attempts_submit_requires_complete_answers")
        conn.execute(
            """UPDATE quiz_attempts
               SET state = 'submitted', submitted_at = started_at + 1,
                   revision = revision + 1, updated_at = started_at + 1
               WHERE id = ?""",
            (view.attempt.id,),
        )
        conn.execute(completeness_trigger)

    with pytest.raises(
        CourseConflictError,
        match="every answer before grading",
    ):
        grading.grade(
            course.id,
            practice_set.id,
            view.attempt.id,
            objective_mapping={},
            expected_course_write_epoch=course.write_epoch,
            expected_practice_set_write_epoch=practice_set.write_epoch,
        )

    with courses._connect() as conn:
        assert conn.execute(
            "SELECT state FROM quiz_attempts WHERE id = ?", (view.attempt.id,)
        ).fetchone()[0] == "submitted"
        assert conn.execute(
            "SELECT COUNT(*) FROM quiz_attempt_items WHERE attempt_id = ?",
            (view.attempt.id,),
        ).fetchone()[0] == 2
        assert conn.execute(
            """SELECT COUNT(*) FROM quiz_attempt_answers AS answers
               JOIN quiz_attempt_items AS items ON items.id = answers.attempt_item_id
               WHERE items.attempt_id = ?""",
            (view.attempt.id,),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM quiz_item_grading_evidence WHERE attempt_id = ?",
            (view.attempt.id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            """SELECT COUNT(*) FROM quiz_attempt_items
               WHERE attempt_id = ? AND graded_at IS NOT NULL""",
            (view.attempt.id,),
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "response_kind",
    ["option-text", "unknown-option", "foreign-option", "more-than-one-selection"],
    ids=["option-text", "unknown-option", "foreign-option", "more-than-one-selection"],
)
def test_single_choice_rejects_non_authoritative_selections_before_persistence(
    tmp_path: Path, response_kind: str
) -> None:
    (
        courses,
        _practice,
        attempts,
        _grading,
        course,
        practice_set,
        _revision,
        _short_question,
        choice_question,
        view,
    ) = _start_mixed(tmp_path)
    choice_item = next(
        item for item in view.items if item.question_id == choice_question.id
    )
    correct_id = _choice_id(choice_question, CHOICE_CORRECT_TEXT)
    wrong_id = _choice_id(choice_question, CHOICE_WRONG_FLOW_TEXT)
    foreign_id = "opt_" + "f" * 32
    if foreign_id in {option.option_id for option in choice_question.options}:
        foreign_id = "opt_" + "e" * 32
    response = {
        "option-text": {"option_id": CHOICE_CORRECT_TEXT},
        "unknown-option": {"option_id": "opt_resp02_unknown"},
        "foreign-option": {"option_id": foreign_id},
        "more-than-one-selection": {
            "option_id": correct_id,
            "option_ids": [correct_id, wrong_id],
        },
    }[response_kind]

    with pytest.raises(ValueError, match="exactly|belong|presentation"):
        attempts.autosave_answer(
            course.id,
            practice_set.id,
            view.attempt.id,
            choice_item.id,
            response=response,
            expected_answer_revision=1,
            idempotency_token="rejected-choice-answer",
            expected_course_write_epoch=course.write_epoch,
            expected_practice_set_write_epoch=practice_set.write_epoch,
        )

    reloaded = attempts.get_attempt(course.id, practice_set.id, view.attempt.id)
    answer = next(
        item for item in reloaded.answers if item.attempt_item_id == choice_item.id
    )
    assert answer.response is None
    assert answer.revision == 1


def test_python_and_sqlite_grading_are_in_parity_and_sql_tamper_fails_closed(
    tmp_path: Path,
) -> None:
    (
        courses,
        _practice,
        attempts,
        grading,
        course,
        practice_set,
        _revision,
        short_question,
        choice_question,
        view,
    ) = _start_mixed(tmp_path)
    items = {item.question_id: item for item in view.items}
    wrong_flow_id = _choice_id(choice_question, CHOICE_WRONG_FLOW_TEXT)
    responses = {
        short_question.id: {"answer": "Pyruvate is converted to acetyl—CoA!"},
        choice_question.id: {"option_id": wrong_flow_id},
    }
    for index, (question_id, response) in enumerate(responses.items(), start=1):
        attempts.autosave_answer(
            course.id,
            practice_set.id,
            view.attempt.id,
            items[question_id].id,
            response=response,
            expected_answer_revision=1,
            idempotency_token=f"parity-answer-{index}",
            expected_course_write_epoch=course.write_epoch,
            expected_practice_set_write_epoch=practice_set.write_epoch,
        )
    attempts.submit_attempt(
        course.id,
        practice_set.id,
        view.attempt.id,
        expected_course_write_epoch=course.write_epoch,
        expected_practice_set_write_epoch=practice_set.write_epoch,
    )

    with courses._connect() as conn:
        row = conn.execute(
            """SELECT attempts.owner_user_id, items.id AS attempt_item_id,
                      items.option_order_json, answers.response_json,
                      questions.answer_contract_json
               FROM quiz_attempts AS attempts
               JOIN quiz_attempt_items AS items ON items.attempt_id = attempts.id
               JOIN quiz_attempt_answers AS answers
                 ON answers.attempt_item_id = items.id
               JOIN practice_questions AS questions ON questions.id = items.question_id
               WHERE attempts.id = ? AND questions.id = ?""",
            (view.attempt.id, short_question.id),
        ).fetchone()
        forged = {
            "algorithm": "bounded_short_answer_v1",
            "attempt_id": view.attempt.id,
            "attempt_item_id": row["attempt_item_id"],
            "question_id": short_question.id,
            "objective_id": "OBJ-RESP-01",
            "module_id": None,
            "knowledge_type": None,
            "contract_sha256": _canonical_sha256(row["answer_contract_json"]),
            "response_sha256": _canonical_sha256(row["response_json"]),
            "is_correct": False,
            "error_type": "application",
            "answer_contract_kind": "bounded_short_answer_v1",
            "normalization_version": "bounded-text-normalization-v1",
            "raw_response": responses[short_question.id]["answer"],
            "normalized_response": (
                "pyruvate is converted to acetyl-coa"
            ),
        }
        forged_json = json.dumps(
            forged,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO quiz_item_grading_evidence
                   (id, owner_user_id, course_id, practice_set_id, attempt_id,
                    attempt_item_id, question_id, objective_id, module_id,
                    knowledge_type, algorithm, payload_sha256, is_correct,
                    grading_json, error_type, state, created_at, applied_at)
                   VALUES ('grd_forged_bounded', ?, ?, ?, ?, ?, ?, 'OBJ-RESP-01', NULL, NULL,
                           'bounded_short_answer_v1', ?, 0, ?, 'application',
                           'unmapped', 1, 1)""",
                (
                    row["owner_user_id"],
                    course.id,
                    practice_set.id,
                    view.attempt.id,
                    row["attempt_item_id"],
                    short_question.id,
                    hashlib.sha256(forged_json.encode("utf-8")).hexdigest(),
                    forged_json,
                ),
            )

        choice_row = conn.execute(
            """SELECT attempts.owner_user_id, items.id AS attempt_item_id,
                      items.option_order_json, answers.response_json,
                      questions.answer_contract_json, questions.options_json
               FROM quiz_attempts AS attempts
               JOIN quiz_attempt_items AS items ON items.attempt_id = attempts.id
               JOIN quiz_attempt_answers AS answers
                 ON answers.attempt_item_id = items.id
               JOIN practice_questions AS questions ON questions.id = items.question_id
               WHERE attempts.id = ? AND questions.id = ?""",
            (view.attempt.id, choice_question.id),
        ).fetchone()
        choice_forgery = {
            "algorithm": "single_choice_v1",
            "attempt_id": view.attempt.id,
            "attempt_item_id": choice_row["attempt_item_id"],
            "question_id": choice_question.id,
            "objective_id": "OBJ-RESP-02",
            "module_id": None,
            "knowledge_type": None,
            "contract_sha256": _canonical_sha256(
                choice_row["answer_contract_json"]
            ),
            "response_sha256": _canonical_sha256(choice_row["response_json"]),
            "is_correct": False,
            "error_type": "application",
            "answer_contract_kind": "single_choice_v1",
            "selected_option_id": _choice_id(
                choice_question, CHOICE_WRONG_PRODUCT_TEXT
            ),
            "correct_option_id": _choice_id(
                choice_question, CHOICE_CORRECT_TEXT
            ),
            "options_sha256": _canonical_sha256(choice_row["options_json"]),
            "option_order_sha256": _canonical_sha256(
                choice_row["option_order_json"]
            ),
        }
        reversed_order_json = json.dumps(
            list(reversed(json.loads(choice_row["option_order_json"]))),
            separators=(",", ":"),
        )
        for evidence_id, payload in (
            ("grd_forged_choice_selected", choice_forgery),
            (
                "grd_forged_choice_order",
                {
                    **choice_forgery,
                    "selected_option_id": wrong_flow_id,
                    "option_order_sha256": _canonical_sha256(reversed_order_json),
                },
            ),
        ):
            payload_json = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """INSERT INTO quiz_item_grading_evidence
                       (id, owner_user_id, course_id, practice_set_id, attempt_id,
                        attempt_item_id, question_id, objective_id, module_id,
                        knowledge_type, algorithm, payload_sha256, is_correct,
                        grading_json, error_type, state, created_at, applied_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'OBJ-RESP-02', NULL, NULL,
                               'single_choice_v1', ?, 0, ?, 'application',
                               'unmapped', 1, 1)""",
                    (
                        evidence_id,
                        choice_row["owner_user_id"],
                        course.id,
                        practice_set.id,
                        view.attempt.id,
                        choice_row["attempt_item_id"],
                        choice_question.id,
                        hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                        payload_json,
                    ),
                )

    graded, evidence = grading.grade(
        course.id,
        practice_set.id,
        view.attempt.id,
        objective_mapping={},
        expected_course_write_epoch=course.write_epoch,
        expected_practice_set_write_epoch=practice_set.write_epoch,
    )
    evidence_by_question = {item.question_id: item for item in evidence}
    short_decision = grade_assessment_response(
        responses[short_question.id], short_question.answer_contract, short_question.options
    )
    choice_decision = grade_assessment_response(
        responses[choice_question.id],
        choice_question.answer_contract,
        choice_question.options,
    )

    assert graded.score == {"correct": 1, "total": 2, "fraction": 0.5}
    assert evidence_by_question[short_question.id].is_correct is short_decision.is_correct
    assert evidence_by_question[choice_question.id].is_correct is choice_decision.is_correct
    assert evidence_by_question[short_question.id].grading["normalized_response"] == (
        short_decision.normalized_response
    )
    assert evidence_by_question[choice_question.id].grading["selected_option_id"] == (
        choice_decision.raw_response
    )


def test_wrong_single_choice_error_type_remains_application_in_learning_projection(
    tmp_path: Path,
) -> None:
    (
        courses,
        _practice,
        attempts,
        grading_repository,
        course,
        practice_set,
        _revision,
        short_question,
        choice_question,
        view,
    ) = _start_mixed(tmp_path)
    items = {item.question_id: item for item in view.items}
    for token, question, response in (
        (
            "learning-short-correct",
            short_question,
            {"answer": "Pyruvate is converted to acetyl-CoA."},
        ),
        (
            "learning-choice-wrong",
            choice_question,
            {
                "option_id": _choice_id(
                    choice_question, CHOICE_WRONG_FLOW_TEXT
                )
            },
        ),
    ):
        attempts.autosave_answer(
            course.id,
            practice_set.id,
            view.attempt.id,
            items[question.id].id,
            response=response,
            expected_answer_revision=1,
            idempotency_token=token,
            expected_course_write_epoch=course.write_epoch,
            expected_practice_set_write_epoch=practice_set.write_epoch,
        )
    attempts.submit_attempt(
        course.id,
        practice_set.id,
        view.attempt.id,
        expected_course_write_epoch=course.write_epoch,
        expected_practice_set_write_epoch=practice_set.write_epoch,
    )

    adapter = CourseMasteryAdapter(LearningStore(root=tmp_path / "learning"))
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    adapter.service.init_modules(
        progress,
        [
            LearningModule(
                id="mod_resp",
                name="Respiration",
                order=1,
                knowledge_points=[
                    KnowledgePoint(
                        id="OBJ-RESP-02",
                        name="Terminal electron acceptor",
                        type=KnowledgeType.CONCEPT,
                        module_id="mod_resp",
                    )
                ],
            )
        ],
    )
    adapter.service.save(progress)
    grading = CourseGradingService(grading_repository, adapter)

    graded = grading.grade_attempt(
        course.id,
        practice_set.id,
        view.attempt.id,
        expected_course_write_epoch=course.write_epoch,
        expected_practice_set_write_epoch=practice_set.write_epoch,
    )

    assert graded.score == {"correct": 1, "total": 2, "fraction": 0.5}
    with courses._connect() as conn:
        evidence_error = conn.execute(
            """SELECT error_type FROM quiz_item_grading_evidence
               WHERE attempt_id = ? AND question_id = ?""",
            (view.attempt.id, choice_question.id),
        ).fetchone()[0]
        item_error = conn.execute(
            "SELECT error_type FROM quiz_attempt_items WHERE id = ?",
            (items[choice_question.id].id,),
        ).fetchone()[0]
    assert evidence_error == item_error == "application"

    projected = adapter.service.get_or_create(f"lp_{course.id}")
    choice_attempt = next(
        item for item in projected.quiz_attempts if item.question_id == choice_question.id
    )
    choice_error = next(
        item for item in projected.error_records if item.question_id == choice_question.id
    )
    assert choice_attempt.error_type is ErrorType.APPLICATION_ERROR
    assert choice_error.error_type is ErrorType.APPLICATION_ERROR


@pytest.fixture
def bounded_practice_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import courses as course_router
    from deeptutor.courses import service as course_service
    from deeptutor.multi_user import identity, paths
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.auth import TokenPayload

    admin_root = (tmp_path / "data").resolve()
    users_root = admin_root / "users"
    system_root = admin_root / "system"
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "USERS_ROOT", users_root)
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(
        identity, "LEGACY_USERS_FILE", tmp_path / "missing-users.json"
    )
    monkeypatch.setattr(
        identity, "LEGACY_SECRET_FILE", tmp_path / "missing-secret"
    )

    alice = save_user("alice", "$2b$12$placeholder", role="admin")
    token = TokenPayload("alice", "admin", alice["id"])
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth_router, "decode_token", lambda supplied: token if supplied == "alice" else None
    )
    monkeypatch.setattr(course_service, "is_pocketbase_enabled", lambda: False)
    course_service._repository_for.cache_clear()

    app = FastAPI()
    app.include_router(
        course_router.router,
        prefix="/api/v1/courses",
        dependencies=[Depends(auth_router.require_auth)],
    )
    app.state.alice_id = alice["id"]
    return TestClient(app)


def test_api_hides_answers_and_citations_until_results(
    bounded_practice_client: TestClient,
) -> None:
    from deeptutor.multi_user.paths import get_personal_path_service

    client = bounded_practice_client
    headers = {"Authorization": "Bearer alice"}
    created = client.post(
        "/api/v1/courses", headers=headers, json={"title": "Biology"}
    )
    assert created.status_code == 200
    course_payload = created.json()
    courses = CourseRepository(
        get_personal_path_service(client.app.state.alice_id).get_courses_db(),
        client.app.state.alice_id,
    )
    practice = CoursePracticeService(CoursePracticeRepository(courses))
    source = courses.create_source(
        course_payload["id"],
        kind="notes",
        display_name="respiration-notes.txt",
        manifest=[],
        content_sha256="a" * 64,
    )
    source = courses.transition_source(
        course_payload["id"],
        source.id,
        operation_id=source.operation_id or "",
        expected_source_revision=source.revision,
        expected_course_revision=course_payload["revision"],
        expected_write_epoch=course_payload["write_epoch"],
        state="ready",
    )
    practice_set = practice.create_practice_set(
        course_payload["id"],
        title="Safe choice",
        expected_course_write_epoch=course_payload["write_epoch"],
    )
    revision = practice.create_draft_revision(
        course_payload["id"],
        practice_set.id,
        source_ids=(source.id,),
        expected_course_write_epoch=course_payload["write_epoch"],
    )
    explanation = (
        "Oxygen accepts electrons and protons to form water, allowing electron flow "
        "through the chain to continue."
    )
    citation_quote = (
        "Oxygen accepts electrons and protons to form water; without that final "
        "acceptor, electron flow cannot continue normally."
    )
    question = practice.add_question(
        course_payload["id"],
        practice_set.id,
        revision.id,
        question_type="single_choice",
        prompt=CHOICE_PROMPT,
        options=CHOICE_OPTIONS,
        answer_contract=CHOICE_CONTRACT,
        explanation=explanation,
        objective_ids=("OBJ-RESP-02",),
        citations=(
            {
                "source_id": source.id,
                "source_revision": source.revision,
                "content_sha256": source.content_sha256,
                "locator": {"page": 7, "quote": citation_quote},
            },
        ),
        expected_course_write_epoch=course_payload["write_epoch"],
    )
    practice.ready_revision(
        course_payload["id"],
        practice_set.id,
        revision.id,
        expected_course_write_epoch=course_payload["write_epoch"],
    )
    practice_set = practice.get_practice_set(course_payload["id"], practice_set.id)
    questions_url = (
        f"/api/v1/courses/{course_payload['id']}/practice/{practice_set.id}/"
        f"revisions/{revision.id}/questions"
    )

    pre_grade = client.get(questions_url, headers=headers)
    assert pre_grade.status_code == 200
    learner_question = pre_grade.json()["questions"][0]
    assert learner_question["id"] == question.id
    expected_options = _choice_payload(question)
    assert learner_question["options"] == expected_options
    assert all(set(option) == {"option_id", "text"} for option in learner_question["options"])
    for hidden in ("answer_contract", "explanation", "citations"):
        assert hidden not in learner_question
    assert "correct_option_id" not in pre_grade.text
    assert explanation not in pre_grade.text
    assert citation_quote not in pre_grade.text
    assert source.id not in pre_grade.text

    attempts_url = (
        f"/api/v1/courses/{course_payload['id']}/practice/{practice_set.id}/attempts"
    )
    started = client.post(
        attempts_url,
        headers=headers,
        json={
            "practice_set_revision_id": revision.id,
            "expected_course_write_epoch": course_payload["write_epoch"],
            "expected_practice_set_write_epoch": practice_set.write_epoch,
        },
    )
    assert started.status_code == 200
    view = started.json()
    attempt_url = f"{attempts_url}/{view['attempt']['id']}"
    saved = client.patch(
        attempt_url,
        headers={**headers, "Idempotency-Key": "safe-choice-answer"},
        json={
            "attempt_item_id": view["items"][0]["id"],
            "response": {
                "option_id": _choice_id(question, CHOICE_CORRECT_TEXT)
            },
            "expected_answer_revision": 1,
            "expected_course_write_epoch": course_payload["write_epoch"],
            "expected_practice_set_write_epoch": practice_set.write_epoch,
        },
    )
    assert saved.status_code == 200
    mutation = {
        "expected_course_write_epoch": course_payload["write_epoch"],
        "expected_practice_set_write_epoch": practice_set.write_epoch,
    }
    assert client.post(
        f"{attempt_url}/submit", headers=headers, json=mutation
    ).status_code == 200
    assert client.post(
        f"{attempt_url}/grade", headers=headers, json=mutation
    ).status_code == 200

    results = client.get(f"{attempt_url}/results", headers=headers)
    assert results.status_code == 200
    result_question = results.json()["questions"][0]
    assert result_question["options"] == expected_options
    assert result_question["answer_contract"] == question.answer_contract.model_dump(
        mode="json"
    )
    assert result_question["explanation"] == explanation
    assert result_question["citations"] == [
        {
            "source_id": source.id,
            "source_revision": source.revision,
            "content_sha256": source.content_sha256,
            "locator": {"page": 7, "quote": citation_quote},
        }
    ]


def test_0015_preserves_legacy_essay_exact_runtime_but_new_authoring_is_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "legacy-exact.db"
    artifacts = runner.discover_migrations()
    assert next(artifact for artifact in artifacts if artifact.version == 15).filename == "0015_bounded_assessment_runtime.sql"
    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts[:15])
    assert ensure_course_schema(path) == tuple(range(15))
    with sqlite3.connect(path) as conn:
        conn.execute(
            """INSERT INTO courses
               (id, owner_user_id, title, state, revision, write_epoch,
                managed_kb_ref, created_at, updated_at, archived_at)
               VALUES ('crs_exact', 'u_alice', 'Legacy exact', 'active', 1, 1,
                       NULL, 1, 1, NULL)"""
        )
        conn.execute(
            """INSERT INTO practice_sets
               (id, owner_user_id, course_id, title, mode, state,
                current_revision_id, revision, write_epoch, created_at,
                updated_at, archived_at)
               VALUES ('prc_exact', 'u_alice', 'crs_exact', 'Legacy set', 'manual',
                       'draft', NULL, 1, 1, 1, 1, NULL)"""
        )
        conn.execute(
            """INSERT INTO practice_set_revisions
               (id, practice_set_id, revision_number, state,
                source_snapshot_json, objective_ids_json, generation_receipt_json,
                created_at, ready_at)
               VALUES ('prv_exact', 'prc_exact', 1, 'draft', '[]', '[]', NULL, 1, NULL)"""
        )
        conn.execute(
            """INSERT INTO practice_questions
               (id, practice_set_revision_id, question_type, prompt,
                answer_contract_json, explanation, objective_ids_json,
                citation_json, ordinal, created_at)
               VALUES ('qst_exact', 'prv_exact', 'essay', 'Type yes',
                       '{"kind":"exact","answer":"yes"}', 'Legacy explanation',
                       '[]', '[]', 1, 1)"""
        )
        conn.execute(
            """UPDATE practice_set_revisions
               SET state = 'ready', ready_at = 2 WHERE id = 'prv_exact'"""
        )
        conn.execute(
            """UPDATE practice_sets
               SET current_revision_id = 'prv_exact', revision = revision + 1,
                   write_epoch = write_epoch + 1, updated_at = 2
               WHERE id = 'prc_exact'"""
        )
        before = tuple(
            conn.execute(
                """SELECT id, practice_set_revision_id, question_type, prompt,
                          answer_contract_json, explanation, objective_ids_json,
                          citation_json, ordinal, created_at
                   FROM practice_questions WHERE id = 'qst_exact'"""
            ).fetchone()
        )

    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts)
    assert ensure_course_schema(path) == tuple(artifact.version for artifact in artifacts[15:])
    assert ensure_course_schema(path) == ()
    with sqlite3.connect(path) as conn:
        after = tuple(
            conn.execute(
                """SELECT id, practice_set_revision_id, question_type, prompt,
                          answer_contract_json, explanation, objective_ids_json,
                          citation_json, ordinal, created_at
                   FROM practice_questions WHERE id = 'qst_exact'"""
            ).fetchone()
        )
        assert before == after
        assert conn.execute(
            "SELECT options_json FROM practice_questions WHERE id = 'qst_exact'"
        ).fetchone()[0] == "[]"
        assert tuple(
            row[0]
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ) == tuple(artifact.version for artifact in artifacts)
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == len(artifacts)

    courses = CourseRepository(path, "u_alice")
    practice = CoursePracticeService(CoursePracticeRepository(courses))
    question = practice.list_questions("crs_exact", "prc_exact", "prv_exact")[0]
    assert question.question_type == "essay"
    assert question.options == []
    assert question.answer_contract.kind == "exact"
    assert grade_assessment_response(
        {"answer": "YES"}, question.answer_contract, question.options
    ).is_correct

    attempts = CourseAssessmentService(CourseAssessmentRepository(courses))
    practice_set = practice.get_practice_set("crs_exact", "prc_exact")
    view = attempts.start_or_resume_attempt(
        "crs_exact",
        practice_set.id,
        "prv_exact",
        expected_course_write_epoch=1,
        expected_practice_set_write_epoch=practice_set.write_epoch,
    )
    attempts.autosave_answer(
        "crs_exact",
        practice_set.id,
        view.attempt.id,
        view.items[0].id,
        response={"answer": "YES"},
        expected_answer_revision=1,
        idempotency_token="legacy-essay-answer",
        expected_course_write_epoch=1,
        expected_practice_set_write_epoch=practice_set.write_epoch,
    )
    attempts.submit_attempt(
        "crs_exact",
        practice_set.id,
        view.attempt.id,
        expected_course_write_epoch=1,
        expected_practice_set_write_epoch=practice_set.write_epoch,
    )
    graded, evidence = CourseGradingRepository(courses).grade(
        "crs_exact",
        practice_set.id,
        view.attempt.id,
        objective_mapping={},
        expected_course_write_epoch=1,
        expected_practice_set_write_epoch=practice_set.write_epoch,
    )
    assert graded.score == {"correct": 1, "total": 1, "fraction": 1.0}
    assert len(evidence) == 1 and evidence[0].algorithm == "exact-v1"

    authored_set = practice.create_practice_set(
        "crs_exact",
        title="Canonical authoring",
        expected_course_write_epoch=1,
    )
    authored_revision = practice.create_draft_revision(
        "crs_exact",
        authored_set.id,
        expected_course_write_epoch=1,
    )
    with pytest.raises(ValueError, match="question_type='short_answer'"):
        practice.add_question(
            "crs_exact",
            authored_set.id,
            authored_revision.id,
            question_type="essay",
            prompt="New essay question",
            answer_contract={"kind": "exact", "answer": "yes"},
            expected_course_write_epoch=1,
        )
