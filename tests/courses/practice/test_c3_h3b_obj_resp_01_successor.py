"""H3B-1 proof for the human-approved OBJ-RESP-01 successor revision."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from deeptutor.courses.assessment_grading import grade_assessment_response
from deeptutor.courses.attempt_repository import CourseAssessmentRepository
from deeptutor.courses.attempt_service import CourseAssessmentService
from deeptutor.courses.grading_repository import CourseGradingRepository
from deeptutor.courses.grading_service import CourseGradingService
from deeptutor.courses.mastery_adapter import CourseMasteryAdapter
from deeptutor.courses.practice_models import BoundedShortAnswerContract
from deeptutor.courses.practice_repository import CoursePracticeRepository
from deeptutor.courses.practice_service import CoursePracticeService
from deeptutor.courses.repository import CourseConflictError, CourseRepository
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
)
from deeptutor.learning.storage import LearningStore


REFERENCE_ROOT = Path(__file__).resolve().parents[3] / "evals/reference_course"
PROVIDER_ARTIFACT = (
    REFERENCE_ROOT
    / "provider_runs/2026-08-09-gpt-5.6-luna-c3-evidence-roles-v2/obj-resp-01.json"
)
AMENDMENT = (
    REFERENCE_ROOT
    / "reviewer_amendments/obj-resp-01-bounded-short-answer-v2.json"
)
QUALIFICATION = (
    REFERENCE_ROOT / "objective_qualifications/obj-resp-01-h3b1.json"
)


def _provider_question() -> dict[str, object]:
    payload = json.loads(PROVIDER_ARTIFACT.read_text(encoding="utf-8"))
    return payload["validated_output"]["questions"][0]


def _bounded_contract() -> dict[str, object]:
    payload = json.loads(AMENDMENT.read_text(encoding="utf-8"))
    return payload["candidate_answer_contract"]


def _services(tmp_path: Path):
    courses = CourseRepository(tmp_path / "courses.db", "u_king_h3b")
    practice = CoursePracticeService(CoursePracticeRepository(courses))
    attempts = CourseAssessmentService(CourseAssessmentRepository(courses))
    mastery = CourseMasteryAdapter(LearningStore(root=tmp_path / "learning"))
    grading = CourseGradingService(CourseGradingRepository(courses), mastery)
    return courses, practice, attempts, mastery, grading


def _initialize_objective(mastery: CourseMasteryAdapter, course_id: str) -> None:
    progress = mastery.service.get_or_create(f"lp_{course_id}")
    mastery.service.init_modules(
        progress,
        [
            LearningModule(
                id="mod_respiration",
                name="Cellular respiration",
                order=1,
                knowledge_points=[
                    KnowledgePoint(
                        id="OBJ-RESP-01",
                        name="Pyruvate oxidation transition",
                        type=KnowledgeType.CONCEPT,
                        module_id="mod_respiration",
                    )
                ],
            )
        ],
    )
    mastery.service.save(progress)


def test_obj_resp_01_successor_preserves_history_and_grades_canonical_answer(
    tmp_path: Path,
) -> None:
    courses, practice, attempts, mastery, grading = _services(tmp_path)
    course = courses.create_course("Biology 101")
    question_fixture = _provider_question()
    original_citations = question_fixture["citations"]
    assert isinstance(original_citations, list)
    source = courses.create_source(
        course.id,
        kind="transcript",
        display_name="lecture_06_transcript.md",
        manifest=[],
        content_sha256=original_citations[0]["content_sha256"],
    )
    source = courses.transition_source(
        course.id,
        source.id,
        operation_id=source.operation_id or "",
        expected_source_revision=source.revision,
        expected_course_revision=course.revision,
        expected_write_epoch=course.write_epoch,
        state="ready",
    )
    citations = tuple(
        {
            **citation,
            "source_id": source.id,
            "source_revision": source.revision,
        }
        for citation in original_citations
    )
    practice_set = practice.create_practice_set(
        course.id,
        title="Cellular respiration qualification",
        expected_course_write_epoch=course.write_epoch,
    )
    original_revision = practice.create_draft_revision(
        course.id,
        practice_set.id,
        source_ids=(source.id,),
        objective_ids=("OBJ-RESP-01",),
        expected_course_write_epoch=course.write_epoch,
    )
    original_question = practice.add_question(
        course.id,
        practice_set.id,
        original_revision.id,
        question_type="short_answer",
        prompt=question_fixture["prompt"],
        answer_contract=question_fixture["answer_contract"],
        explanation=question_fixture["explanation"],
        objective_ids=question_fixture["objective_ids"],
        citations=citations,
        ordinal=1,
        expected_course_write_epoch=course.write_epoch,
    )
    practice.ready_revision(
        course.id,
        practice_set.id,
        original_revision.id,
        expected_course_write_epoch=course.write_epoch,
    )
    original_snapshot = original_question.model_dump(mode="json")

    successor_revision = practice.create_successor_revision(
        course.id,
        practice_set.id,
        source_ids=(source.id,),
        objective_ids=("OBJ-RESP-01",),
        expected_course_write_epoch=course.write_epoch,
    )
    successor_question = practice.add_question(
        course.id,
        practice_set.id,
        successor_revision.id,
        question_type="short_answer",
        prompt=question_fixture["prompt"],
        answer_contract=_bounded_contract(),
        explanation=question_fixture["explanation"],
        objective_ids=question_fixture["objective_ids"],
        citations=citations,
        ordinal=1,
        expected_course_write_epoch=course.write_epoch,
    )
    practice.ready_revision(
        course.id,
        practice_set.id,
        successor_revision.id,
        expected_course_write_epoch=course.write_epoch,
    )

    retained_original = practice.list_questions(
        course.id, practice_set.id, original_revision.id
    )[0]
    retained_successor = practice.list_questions(
        course.id, practice_set.id, successor_revision.id
    )[0]
    assert retained_original.model_dump(mode="json") == original_snapshot
    assert retained_original.answer_contract.kind == "exact"
    assert practice.get_revision(
        course.id, practice_set.id, original_revision.id
    ).state == "superseded"
    assert practice.get_revision(
        course.id, practice_set.id, successor_revision.id
    ).state == "ready"
    assert successor_revision.revision_number == original_revision.revision_number + 1
    assert practice.get_practice_set(
        course.id, practice_set.id
    ).current_revision_id == successor_revision.id
    assert retained_successor.id == successor_question.id
    assert retained_successor.answer_contract.kind == "bounded_short_answer_v1"
    for field in ("prompt", "explanation", "objective_ids", "citations", "ordinal"):
        assert getattr(retained_successor, field) == getattr(retained_original, field)

    with pytest.raises(CourseConflictError, match="immutable"):
        practice.add_question(
            course.id,
            practice_set.id,
            successor_revision.id,
            question_type="short_answer",
            prompt="Forbidden mutation",
            answer_contract=_bounded_contract(),
            expected_course_write_epoch=course.write_epoch,
        )

    _initialize_objective(mastery, course.id)
    current_set = practice.get_practice_set(course.id, practice_set.id)
    attempt = attempts.start_or_resume_attempt(
        course.id,
        practice_set.id,
        successor_revision.id,
        expected_course_write_epoch=course.write_epoch,
        expected_practice_set_write_epoch=current_set.write_epoch,
    )
    attempts.autosave_answer(
        course.id,
        practice_set.id,
        attempt.attempt.id,
        attempt.items[0].id,
        response={"answer": "Pyruvate is converted to acetyl-CoA."},
        expected_answer_revision=1,
        idempotency_token="h3b1-canonical-answer",
        expected_course_write_epoch=course.write_epoch,
        expected_practice_set_write_epoch=current_set.write_epoch,
    )
    attempts.submit_attempt(
        course.id,
        practice_set.id,
        attempt.attempt.id,
        expected_course_write_epoch=course.write_epoch,
        expected_practice_set_write_epoch=current_set.write_epoch,
    )
    graded = grading.grade_attempt(
        course.id,
        practice_set.id,
        attempt.attempt.id,
        expected_course_write_epoch=course.write_epoch,
        expected_practice_set_write_epoch=current_set.write_epoch,
    )
    assert graded.score == {"correct": 1, "total": 1, "fraction": 1.0}


@pytest.mark.parametrize(
    ("answer", "correct"),
    [
        ("Pyruvate is converted to acetyl-CoA.", True),
        ("Pyruvate becomes acetyl-CoA", True),
        ("Pyruvate is converted to acetyl coenzyme A", True),
        ("PYRUVATE IS CONVERTED TO ACETYL-COA!", True),
        ("Pyruvate is converted to acetyl—CoA.", True),
        ("Acetyl-CoA is converted to pyruvate.", False),
        ("Pyruvate is converted to lactate.", False),
        ("Pyruvate is converted.", False),
    ],
    ids=[
        "canonical",
        "approved-variant",
        "approved-expanded-name",
        "case-and-punctuation",
        "unicode-hyphen",
        "reversal",
        "wrong-molecule",
        "incomplete",
    ],
)
def test_obj_resp_01_successor_bounded_grading_matrix(
    answer: str, correct: bool
) -> None:
    contract = BoundedShortAnswerContract.model_validate(_bounded_contract())

    decision = grade_assessment_response({"answer": answer}, contract, [])

    assert decision.is_correct is correct


def test_obj_resp_01_qualification_receipt_binds_review_and_source_artifacts() -> None:
    receipt = json.loads(QUALIFICATION.read_text(encoding="utf-8"))

    assert receipt["status"] == "HUMAN_QUALIFIED"
    assert receipt["objective_id"] == "OBJ-RESP-01"
    assert receipt["provider_calls"] == 0
    assert receipt["successor_revision_materialization"] == (
        "HERMITIC_REPOSITORY_RUNTIME_PROOF"
    )
    for binding in receipt["artifact_bindings"]:
        path = REFERENCE_ROOT / binding["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"]
    assert receipt["proof"]["test_node"] == (
        "tests/courses/practice/test_c3_h3b_obj_resp_01_successor.py"
        "::test_obj_resp_01_successor_preserves_history_and_grades_canonical_answer"
    )
