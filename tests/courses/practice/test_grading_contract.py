"""P4-03 adversarial contracts for deterministic, replay-safe Course grading."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from deeptutor.courses.assessment_grading import grade_assessment_response
from deeptutor.courses.attempt_repository import CourseAssessmentRepository
from deeptutor.courses.attempt_service import CourseAssessmentService
from deeptutor.courses.content_quality_repository import CourseContentQualityRepository
from deeptutor.courses.grading_repository import CourseGradingRepository
from deeptutor.courses.grading_service import CourseGradingService
from deeptutor.courses.mastery_adapter import CourseMasteryAdapter
from deeptutor.courses.migrations import runner
from deeptutor.courses.migrations.runner import CourseMigrationError, ensure_course_schema
from deeptutor.courses.practice_models import ExactAnswerContract
from deeptutor.courses.practice_repository import CoursePracticeRepository
from deeptutor.courses.practice_service import CoursePracticeService
from deeptutor.courses.repository import CourseConflictError, CourseNotFoundError, CourseRepository
from deeptutor.learning.models import KnowledgePoint, KnowledgeType, LearningModule
from deeptutor.learning.storage import LearningConflictError, LearningStore
from scripts.c3_reviewer_amendment import verify_reviewer_answer_amendment


def _services(tmp_path: Path, owner: str = "u_alice"):
    courses = CourseRepository(tmp_path / "courses.db", owner)
    practice = CoursePracticeService(CoursePracticeRepository(courses))
    attempts = CourseAssessmentService(CourseAssessmentRepository(courses))
    adapter = CourseMasteryAdapter(LearningStore(root=tmp_path / "learning"))
    grading = CourseGradingService(CourseGradingRepository(courses), adapter)
    return courses, practice, attempts, adapter, grading


def _epoch(courses: CourseRepository, course_id: str) -> int:
    return courses.get_course(course_id).write_epoch


def _practice(
    courses,
    practice,
    course_id: str,
    *,
    objectives=("kp_one",),
    answer="yes",
    accepted_answers=(),
    raw_contract: str | None = None,
):
    epoch = _epoch(courses, course_id)
    practice_set = practice.create_practice_set(course_id, title="Quiz", expected_course_write_epoch=epoch)
    revision = practice.create_draft_revision(course_id, practice_set.id, expected_course_write_epoch=epoch)
    question = practice.add_question(
        course_id, practice_set.id, revision.id,
        question_type="short_answer", prompt="Answer?",
        answer_contract={
            "kind": "exact",
            "answer": answer,
            "accepted_answers": list(accepted_answers),
        },
        objective_ids=objectives,
        expected_course_write_epoch=epoch,
    )
    if raw_contract is not None:
        with courses._connect() as conn:
            conn.execute(
                "UPDATE practice_questions SET answer_contract_json = ? WHERE id = ?",
                (raw_contract, question.id),
            )
    practice.ready_revision(course_id, practice_set.id, revision.id, expected_course_write_epoch=epoch)
    return practice_set, revision, question


def _init_objectives(adapter: CourseMasteryAdapter, course_id: str, *objective_ids: str) -> None:
    progress = adapter.service.get_or_create(f"lp_{course_id}")
    adapter.service.init_modules(
        progress,
        [LearningModule(
            id="mod_one", name="Module", order=1,
            knowledge_points=[
                KnowledgePoint(id=item, name=item, type=KnowledgeType.MEMORY, module_id="mod_one")
                for item in objective_ids
            ],
        )],
    )
    adapter.service.save(progress)


def _submitted(courses, attempts, course_id: str, practice_set, revision, response):
    view = attempts.start_or_resume_attempt(
        course_id, practice_set.id, revision.id,
        expected_course_write_epoch=_epoch(courses, course_id), expected_practice_set_write_epoch=2,
    )
    item = view.items[0]
    attempts.autosave_answer(
        course_id, practice_set.id, view.attempt.id, item.id,
        response=response, expected_answer_revision=1, idempotency_token="answer-token",
        expected_course_write_epoch=_epoch(courses, course_id), expected_practice_set_write_epoch=2,
    )
    attempts.submit_attempt(
        course_id, practice_set.id, view.attempt.id,
        expected_course_write_epoch=_epoch(courses, course_id), expected_practice_set_write_epoch=2,
    )
    return view.attempt.id, item.id


def _grade(grading, courses, course_id: str, practice_set_id: str, attempt_id: str):
    return grading.grade_attempt(
        course_id, practice_set_id, attempt_id,
        expected_course_write_epoch=_epoch(courses, course_id), expected_practice_set_write_epoch=2,
    )


def _exact_is_correct(response: str, contract: ExactAnswerContract) -> bool:
    return grade_assessment_response(
        {"answer": response}, contract, []
    ).is_correct


@pytest.mark.parametrize("response, correct", [({"answer": "YES"}, True), ({"answer": "no"}, False), ({"answer": ""}, False)])
def test_exact_grading_is_server_contract_driven_for_correct_wrong_and_blank(tmp_path: Path, response, correct: bool) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Biology")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, response)

    result = _grade(grading, courses, course.id, practice_set.id, attempt_id)
    assert result.state == "graded"
    assert result.score == {"correct": int(correct), "total": 1, "fraction": float(correct)}
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    assert len(progress.quiz_attempts) == 1
    assert progress.quiz_attempts[0].is_correct is correct
    if correct:
        assert progress.mastery_levels["kp_one"] > 0
        assert progress.error_records == []
    else:
        assert progress.error_records[0].knowledge_point_id == "kp_one"
        assert progress.review_queue[0].knowledge_point_id == "kp_one"


def test_exact_grading_accepts_only_explicit_bounded_variants(tmp_path: Path) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Biology")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(
        courses,
        practice,
        course.id,
        answer="oxygen",
        accepted_answers=("O2", "molecular oxygen"),
    )

    accepted_attempt, _ = _submitted(
        courses, attempts, course.id, practice_set, revision, {"answer": "O2"}
    )
    accepted = _grade(grading, courses, course.id, practice_set.id, accepted_attempt)
    assert accepted.score == {"correct": 1, "total": 1, "fraction": 1.0}

    second_set, second_revision, _ = _practice(
        courses,
        practice,
        course.id,
        answer="oxygen",
        accepted_answers=("O2", "molecular oxygen"),
    )
    rejected_attempt, _ = _submitted(
        courses,
        attempts,
        course.id,
        second_set,
        second_revision,
        {"answer": "oxygen accepts electrons"},
    )
    rejected = _grade(grading, courses, course.id, second_set.id, rejected_attempt)
    assert rejected.score == {"correct": 0, "total": 1, "fraction": 0.0}


@pytest.mark.parametrize(
    ("response", "accepted"),
    [
        ("ACETYL-COA", True),
        ("acetyl CoA", True),
        ("acetyl coenzyme A", True),
        ("acetyl", False),
    ],
)
def test_exact_grader_requires_explicit_acetyl_coa_variants(
    response: str, accepted: bool
) -> None:
    contract = ExactAnswerContract(
        kind="exact",
        answer="acetyl-CoA",
        accepted_answers=["acetyl CoA", "acetyl coenzyme A"],
    )

    assert _exact_is_correct(response, contract) is accepted


def test_obj_resp_01_reviewer_amendment_is_bounded_and_artifact_bound() -> None:
    reference_root = Path(__file__).resolve().parents[3] / "evals" / "reference_course"
    amendment_path = (
        reference_root
        / "reviewer_amendments"
        / "obj-resp-01-answer-variants-v1.json"
    )
    amendment = json.loads(amendment_path.read_text(encoding="utf-8"))
    verified = verify_reviewer_answer_amendment(reference_root, amendment_path)
    artifact_path = reference_root / amendment["provider_artifact"]

    assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == amendment[
        "provider_artifact_sha256"
    ]
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["provider_runtime"]["raw_provider_output_sha256"] == amendment[
        "raw_provider_output_sha256"
    ]
    provider_contract = artifact["validated_output"]["questions"][0][
        "answer_contract"
    ]
    assert provider_contract["answer"] == amendment["primary_answer"]
    assert provider_contract["accepted_answers"] == amendment[
        "provider_accepted_answers"
    ]
    assert amendment["status"] == "PROPOSED_PENDING_HUMAN_SIGNATURE"
    assert amendment["reviewer"] is None
    assert amendment["reviewed_at"] is None
    assert amendment["signature"] is None
    assert verified.eligible_for_publication is False
    contract = verified.effective_answer_contract
    assert len(contract.accepted_answers) == 8

    for answer in [contract.answer, *contract.accepted_answers]:
        assert _exact_is_correct(answer, contract) is True
        assert _exact_is_correct(f"  {answer.swapcase()}  ", contract) is True

    for answer in (
        "Pyruvate enters the citric acid cycle unchanged.",
        "Pyruvate becomes lactate.",
        "Acetyl-CoA becomes pyruvate.",
        "Pyruvate is oxidized.",
        "Pyruvate becomes acetyl-CoA",
        "Pyruvate  becomes acetyl-CoA.",
        "Pyruvate becomes acetyl–CoA.",
        "",
    ):
        assert _exact_is_correct(answer, contract) is False


def test_obj_resp_01_unsigned_candidate_contract_round_trips_exact_grading(
    tmp_path: Path,
) -> None:
    reference_root = Path(__file__).resolve().parents[3] / "evals" / "reference_course"
    verified = verify_reviewer_answer_amendment(
        reference_root,
        reference_root
        / "reviewer_amendments"
        / "obj-resp-01-answer-variants-v1.json",
    )
    assert verified.eligible_for_publication is False
    contract = verified.effective_answer_contract
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Biology")
    _init_objectives(adapter, course.id, "OBJ-RESP-01")
    practice_set, revision, _ = _practice(
        courses,
        practice,
        course.id,
        objectives=("OBJ-RESP-01",),
        answer=contract.answer,
        accepted_answers=contract.accepted_answers,
    )
    attempt_id, _ = _submitted(
        courses,
        attempts,
        course.id,
        practice_set,
        revision,
        {"answer": "  PYRUVATE BECOMES ACETYL COA.  "},
    )

    result = _grade(grading, courses, course.id, practice_set.id, attempt_id)
    replay = _grade(grading, courses, course.id, practice_set.id, attempt_id)

    assert result.score == {"correct": 1, "total": 1, "fraction": 1.0}
    assert replay == result
    with courses._connect() as conn:
        evidence = json.loads(
            conn.execute(
                "SELECT grading_json FROM quiz_item_grading_evidence WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()[0]
        )
    assert evidence["algorithm"] == "exact-v1"
    assert evidence["contract_sha256"] == CourseGradingRepository._digest(
        contract.model_dump()
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "artifact_hash",
        "duplicate_variant",
        "ninth_variant",
        "partial_signature",
        "objective",
    ],
)
def test_obj_resp_01_reviewer_amendment_tampering_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    source_root = Path(__file__).resolve().parents[3] / "evals" / "reference_course"
    source_amendment = (
        source_root
        / "reviewer_amendments"
        / "obj-resp-01-answer-variants-v1.json"
    )
    payload = json.loads(source_amendment.read_text(encoding="utf-8"))
    root = tmp_path / mutation
    artifact = root / payload["provider_artifact"]
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes((source_root / payload["provider_artifact"]).read_bytes())
    amendment = root / "reviewer_amendments" / source_amendment.name
    amendment.parent.mkdir(parents=True)

    if mutation == "artifact_hash":
        payload["provider_artifact_sha256"] = "0" * 64
    elif mutation == "duplicate_variant":
        payload["additional_accepted_answers"][0] = payload[
            "provider_accepted_answers"
        ][0]
    elif mutation == "ninth_variant":
        payload["additional_accepted_answers"].append(
            "Conversion of pyruvate into acetyl-CoA."
        )
    elif mutation == "partial_signature":
        payload["reviewer"] = "reviewer-123"
    else:
        payload["objective_id"] = "OBJ-RESP-02"
    amendment.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        verify_reviewer_answer_amendment(root, amendment)


@pytest.mark.parametrize(
    "expected, response, correct",
    [
        ("Caf\u00e9", {"answer": "  CAF\u0045\u0301  "}, True),
        ("yes", {"answer": "  yes  "}, True),
        ("yes", {"answer": "The answer is yes"}, False),
        ("1,000", {"answer": "1000"}, False),
        ("ATP", {"answer": "ATP."}, False),
    ],
)
def test_exact_v1_normalization_is_explicit_and_does_not_accept_extra_wording(
    tmp_path: Path, expected: str, response: dict[str, str], correct: bool,
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Normalization")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(
        courses, practice, course.id, answer=expected,
    )
    attempt_id, _ = _submitted(
        courses, attempts, course.id, practice_set, revision, response,
    )
    result = _grade(grading, courses, course.id, practice_set.id, attempt_id)
    assert result.score == {
        "correct": int(correct),
        "total": 1,
        "fraction": float(correct),
    }


def test_unsupported_contract_fails_closed_before_any_evidence(tmp_path: Path) -> None:
    courses, practice, _attempts, _adapter, _grading = _services(tmp_path)
    course = courses.create_course("Chemistry")
    with pytest.raises(
        sqlite3.IntegrityError, match="practice question answer contract is invalid"
    ):
        _practice(
            courses,
            practice,
            course.id,
            raw_contract='{"kind":"unsupported"}',
        )
    with courses._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM quiz_item_grading_evidence").fetchone()[0] == 0


def test_response_must_be_the_exact_answer_object_before_any_grading_receipt(tmp_path: Path) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Linguistics")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    view = attempts.start_or_resume_attempt(
        course.id, practice_set.id, revision.id,
        expected_course_write_epoch=_epoch(courses, course.id),
        expected_practice_set_write_epoch=2,
    )
    with pytest.raises(ValueError, match="response"):
        attempts.autosave_answer(
            course.id, practice_set.id, view.attempt.id, view.items[0].id,
            response="yes", expected_answer_revision=1,
            idempotency_token="malformed-answer-token",
            expected_course_write_epoch=_epoch(courses, course.id),
            expected_practice_set_write_epoch=2,
        )
    with courses._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM quiz_item_grading_evidence WHERE attempt_id = ?", (view.attempt.id,)
        ).fetchone()[0] == 0


def test_grading_is_submitted_owned_and_foreign_or_missing_ids_are_uniform(tmp_path: Path) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    first = courses.create_course("Physics")
    second = courses.create_course("Physics")
    _init_objectives(adapter, first.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, first.id)
    view = attempts.start_or_resume_attempt(first.id, practice_set.id, revision.id, expected_course_write_epoch=_epoch(courses, first.id), expected_practice_set_write_epoch=2)
    for call in (
        lambda: _grade(grading, courses, first.id, practice_set.id, view.attempt.id),
        lambda: _grade(grading, courses, second.id, practice_set.id, view.attempt.id),
        lambda: _grade(grading, courses, first.id, practice_set.id, "att_missing"),
    ):
        with pytest.raises((CourseConflictError, CourseNotFoundError)) as raised:
            call()
        if isinstance(raised.value, CourseNotFoundError):
            assert str(raised.value) == "Assessment resource not found"


def test_multiple_objectives_are_server_resolved_once_each_and_double_grade_is_idempotent(tmp_path: Path) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Math")
    _init_objectives(adapter, course.id, "kp_one", "kp_two")
    practice_set, revision, _ = _practice(courses, practice, course.id, objectives=("kp_one", "kp_two"))
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})
    first = _grade(grading, courses, course.id, practice_set.id, attempt_id)
    second = _grade(grading, courses, course.id, practice_set.id, attempt_id)
    assert first.id == second.id and second.state == "graded"
    with courses._connect() as conn:
        rows = conn.execute("SELECT objective_id, state FROM quiz_item_grading_evidence WHERE attempt_id = ? ORDER BY objective_id", (attempt_id,)).fetchall()
    assert [(row["objective_id"], row["state"]) for row in rows] == [("kp_one", "applied"), ("kp_two", "applied")]
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    assert len(progress.quiz_attempts) == 2
    assert set(progress.mastery_levels) >= {"kp_one", "kp_two"}


def test_unresolved_objective_is_immutable_unmapped_evidence_with_no_learning_effect(tmp_path: Path) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Law")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id, objectives=("kp_one", "kp_missing"))
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})
    assert _grade(grading, courses, course.id, practice_set.id, attempt_id).state == "graded"
    with courses._connect() as conn:
        rows = conn.execute(
            "SELECT objective_id, state FROM quiz_item_grading_evidence WHERE attempt_id = ? ORDER BY objective_id",
            (attempt_id,),
        ).fetchall()
    assert [(row["objective_id"], row["state"]) for row in rows] == [
        ("kp_missing", "unmapped"), ("kp_one", "applied")
    ]
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    assert [item.knowledge_point_id for item in progress.quiz_attempts] == ["kp_one"]


def test_attempt_projection_saves_learning_and_acknowledges_sqlite_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Batching")
    objectives = ("kp_one", "kp_two", "kp_three")
    _init_objectives(adapter, course.id, *objectives)
    practice_set, revision, _ = _practice(
        courses, practice, course.id, objectives=objectives
    )
    attempt_id, _ = _submitted(
        courses, attempts, course.id, practice_set, revision, {"answer": "yes"}
    )
    save_calls = 0
    ack_calls = 0
    original_save = adapter.service.save
    original_ack = grading.repository.acknowledge_applied_batch

    def counted_save(progress):
        nonlocal save_calls
        save_calls += 1
        return original_save(progress)

    def counted_ack(*args, **kwargs):
        nonlocal ack_calls
        ack_calls += 1
        return original_ack(*args, **kwargs)

    monkeypatch.setattr(adapter.service, "save", counted_save)
    monkeypatch.setattr(grading.repository, "acknowledge_applied_batch", counted_ack)
    assert _grade(grading, courses, course.id, practice_set.id, attempt_id).state == "graded"
    assert save_calls == 1
    assert ack_calls == 1


def test_crash_after_learning_save_before_sql_ack_recovers_without_double_effect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("History")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})

    def crash(*_args, **_kwargs):
        raise RuntimeError("after learning save")

    monkeypatch.setattr(grading, "_mark_effect_applied", crash)
    with pytest.raises(RuntimeError, match="after learning save"):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    assert len(progress.quiz_attempts) == 1
    monkeypatch.undo()
    result = _grade(grading, courses, course.id, practice_set.id, attempt_id)
    assert result.state == "graded"
    assert len(adapter.service.get_or_create(f"lp_{course.id}").quiz_attempts) == 1


@pytest.mark.parametrize("seam", ["_apply_effect_to_learning", "_finalize_attempt"])
def test_crash_before_learning_effect_or_before_finalization_recovers_from_pending_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seam: str
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Sociology")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})

    def crash(*_args, **_kwargs):
        raise RuntimeError(seam)

    monkeypatch.setattr(grading, seam, crash)
    with pytest.raises(RuntimeError, match=seam):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    monkeypatch.undo()
    assert _grade(grading, courses, course.id, practice_set.id, attempt_id).state == "graded"
    assert len(adapter.service.get_or_create(f"lp_{course.id}").quiz_attempts) == 1


def test_invalidated_pending_evidence_is_excluded_from_retry_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Invalidated retry")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, question = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(
        courses,
        attempts,
        course.id,
        practice_set,
        revision,
        {"answer": "no"},
    )

    def fail_delivery(_evidence):
        raise RuntimeError("pending delivery failed")

    monkeypatch.setattr(grading, "_apply_effect_to_learning", fail_delivery)
    with pytest.raises(RuntimeError, match="pending delivery failed"):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    pending = grading.repository.pending(course.id, practice_set.id, attempt_id)
    assert len(pending) == 1 and pending[0].state == "pending"

    quality = CourseContentQualityRepository(courses)
    report = quality.report_question(
        course.id,
        practice_set.id,
        revision.id,
        question.id,
        reason="The retained answer contract is no longer authoritative.",
    )
    resolved, invalidated_evidence_ids = quality.resolve_report(
        course.id,
        report["id"],
        decision="invalidate",
        reviewer_user_id="u_alice",
        note="Reviewed against the authoritative source.",
    )
    assert resolved["state"] == "invalidated"
    assert invalidated_evidence_ids == [pending[0].id]
    assert grading.repository.pending(course.id, practice_set.id, attempt_id) == []

    monkeypatch.undo()
    assert _grade(grading, courses, course.id, practice_set.id, attempt_id).state == "graded"
    projected = adapter.service.get_or_create(f"lp_{course.id}")
    assert projected.quiz_attempts == []
    assert projected.error_records == []
    assert projected.grading_evidence_receipts == {}
    with courses._connect() as conn:
        assert conn.execute(
            "SELECT state FROM quiz_item_grading_evidence WHERE id = ?",
            (pending[0].id,),
        ).fetchone()[0] == "pending"


def test_direct_sql_evidence_is_immutable_and_attempt_cannot_grade_without_all_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Ecology")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, item_id = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})
    def crash(_evidence):
        raise RuntimeError("after sqlite grade")

    monkeypatch.setattr(grading, "_apply_effect_to_learning", crash)
    with pytest.raises(RuntimeError, match="after sqlite grade"):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    with courses._connect() as conn:
        evidence_id = conn.execute("SELECT id FROM quiz_item_grading_evidence WHERE attempt_id = ?", (attempt_id,)).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE quiz_item_grading_evidence SET is_correct = 0 WHERE id = ?", (evidence_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM quiz_item_grading_evidence WHERE id = ?", (evidence_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE quiz_attempts SET state = 'graded', score_json = '{}', graded_at = 1 WHERE id = ?", (attempt_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE quiz_attempt_items SET grading_json = '{}', graded_at = 1 WHERE id = ?", (item_id,))


def test_crash_before_sqlite_commit_rolls_back_evidence_and_leaves_attempt_submitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Geography")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})

    def crash(*_args, **_kwargs):
        raise RuntimeError("before sqlite commit")

    monkeypatch.setattr(grading.repository, "_records", crash)
    with pytest.raises(RuntimeError, match="before sqlite commit"):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    assert attempts.get_attempt(course.id, practice_set.id, attempt_id).attempt.state == "submitted"
    with courses._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM quiz_item_grading_evidence WHERE attempt_id = ?", (attempt_id,)).fetchone()[0] == 0


def test_sqlite_grade_commits_before_json_projection_and_delivery_order_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Economics")
    _init_objectives(adapter, course.id, "kp_one", "kp_two")
    practice_set, revision, _ = _practice(courses, practice, course.id, objectives=("kp_two", "kp_one"))
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})

    monkeypatch.setattr(grading, "_apply_effect_to_learning", lambda _evidence: (_ for _ in ()).throw(RuntimeError("after sqlite commit")))
    with pytest.raises(RuntimeError, match="after sqlite commit"):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    assert attempts.get_attempt(course.id, practice_set.id, attempt_id).attempt.state == "graded"
    pending = grading.repository.pending(course.id, practice_set.id, attempt_id)
    assert [(item.objective_id, item.state) for item in pending] == [("kp_one", "pending"), ("kp_two", "pending")]

    monkeypatch.undo()
    assert _grade(grading, courses, course.id, practice_set.id, attempt_id).state == "graded"
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    assert [item.knowledge_point_id for item in progress.quiz_attempts] == ["kp_one", "kp_two"]


def test_blank_answer_is_mapped_to_metacognitive_error_and_zero_objectives_still_grade_item(
    tmp_path: Path,
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Psychology")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id, objectives=())
    attempt_id, item_id = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": ""})
    assert _grade(grading, courses, course.id, practice_set.id, attempt_id).state == "graded"
    with courses._connect() as conn:
        row = conn.execute(
            "SELECT objective_id, state, error_type FROM quiz_item_grading_evidence WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        item = conn.execute("SELECT grading_json, error_type, graded_at FROM quiz_attempt_items WHERE id = ?", (item_id,)).fetchone()
    assert tuple(row) == ("", "unmapped", "metacognitive")
    assert item["grading_json"] is not None and item["error_type"] == "metacognitive" and item["graded_at"] is not None
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    assert progress.quiz_attempts == [] and progress.error_records == [] and progress.review_queue == []


def test_evidence_payload_digest_conflict_is_rejected_by_learning_projection(tmp_path: Path) -> None:
    _courses, _practice_service, _attempts, adapter, _grading = _services(tmp_path)
    progress = adapter.service.get_or_create("lp_crs_digest")
    adapter.service.init_modules(
        progress,
        [LearningModule(id="mod", name="Module", order=1, knowledge_points=[
            KnowledgePoint(id="kp", name="KP", type=KnowledgeType.MEMORY, module_id="mod")
        ])],
    )
    adapter.service.save(progress)
    adapter.service.record_course_grading_evidence(
        progress, evidence_id="grd_same", payload_sha256="a" * 64, question_id="qst", knowledge_point_id="kp",
        module_id="mod", is_correct=True, user_answer="yes", knowledge_type=KnowledgeType.MEMORY,
    )
    with pytest.raises(LearningConflictError, match="payload conflicts"):
        adapter.service.record_course_grading_evidence(
            progress, evidence_id="grd_same", payload_sha256="b" * 64, question_id="qst", knowledge_point_id="kp",
            module_id="mod", is_correct=True, user_answer="yes", knowledge_type=KnowledgeType.MEMORY,
        )


def test_captured_mapping_survives_later_plan_replacement_and_unmapped_never_revives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Art")
    _init_objectives(adapter, course.id, "kp_old")
    practice_set, revision, _ = _practice(courses, practice, course.id, objectives=("kp_old", "kp_never"))
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})
    monkeypatch.setattr(grading, "_apply_effect_to_learning", lambda _evidence: (_ for _ in ()).throw(RuntimeError("after sqlite")))
    with pytest.raises(RuntimeError, match="after sqlite"):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    adapter.service.replace_modules(
        progress,
        [LearningModule(id="mod_new", name="New", order=1, knowledge_points=[
            KnowledgePoint(id="kp_never", name="Later", type=KnowledgeType.PROCEDURE, module_id="mod_new")
        ])],
    )
    adapter.service.save(progress)
    monkeypatch.undo()
    assert _grade(grading, courses, course.id, practice_set.id, attempt_id).state == "graded"
    replayed = adapter.service.get_or_create(f"lp_{course.id}")
    assert [(item.knowledge_point_id, item.module_id) for item in replayed.quiz_attempts] == [("kp_old", "mod_one")]
    with courses._connect() as conn:
        rows = conn.execute(
            "SELECT objective_id, module_id, knowledge_type, state FROM quiz_item_grading_evidence WHERE attempt_id = ? ORDER BY objective_id",
            (attempt_id,),
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("kp_never", None, None, "unmapped"), ("kp_old", "mod_one", "memory", "applied")
    ]


def test_archive_after_sqlite_grade_preserves_pending_ack_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Music")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})
    monkeypatch.setattr(grading, "_apply_effect_to_learning", lambda _evidence: (_ for _ in ()).throw(RuntimeError("after sqlite")))
    with pytest.raises(RuntimeError):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    courses.archive_course(course.id, expected_revision=courses.get_course(course.id).revision)
    monkeypatch.undo()
    assert _grade(grading, courses, course.id, practice_set.id, attempt_id).state == "graded"
    assert len(adapter.service.get_or_create(f"lp_{course.id}").quiz_attempts) == 1


def test_sqlite_evidence_blocks_reset_even_before_learning_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Ethics")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(
        courses, attempts, course.id, practice_set, revision, {"answer": "yes"}
    )
    monkeypatch.setattr(
        grading,
        "_apply_effect_to_learning",
        lambda _evidence: (_ for _ in ()).throw(RuntimeError("after sqlite")),
    )
    with pytest.raises(RuntimeError, match="after sqlite"):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)

    assert grading.repository.has_course_evidence(course.id) is True
    assert (
        adapter.service.get_or_create(f"lp_{course.id}").grading_evidence_receipts
        == {}
    )


def test_0002_upgrade_applies_grading_and_generation_migrations_preserves_rows_and_tamper_or_rollback_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "p4_03"
    path = root / "courses.db"
    artifacts = runner.discover_migrations()
    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts[:3])
    assert ensure_course_schema(path) == (0, 1, 2)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO courses (id, owner_user_id, title, state, revision, write_epoch, managed_kb_ref, created_at, updated_at, archived_at) VALUES ('crs_keep', 'u_alice', 'Keep', 'active', 1, 1, NULL, 1, 1, NULL)")
    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts)
    assert ensure_course_schema(path) == tuple(range(3, 18))
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT title FROM courses WHERE id = 'crs_keep'").fetchone()[0] == "Keep"

    tampered = runner.MigrationArtifact.from_resource(
        artifacts[3].filename, artifacts[3].content + b"\n-- changed bytes\n"
    )
    monkeypatch.setattr(runner, "discover_migrations", lambda: (*artifacts[:3], tampered, *artifacts[4:]))
    with pytest.raises(CourseMigrationError, match="receipt mismatch"):
        ensure_course_schema(path)

    broken = runner.MigrationArtifact.from_resource(
        "0003_grading_evidence.sql", b"CREATE TABLE should_rollback (id INTEGER);\nNOT VALID SQL;"
    )
    monkeypatch.setattr(runner, "discover_migrations", lambda: (*artifacts[:3], broken))
    fresh = tmp_path / "broken.db"
    with pytest.raises(CourseMigrationError, match="0003_grading_evidence.sql failed"):
        ensure_course_schema(fresh)
    with sqlite3.connect(fresh) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'should_rollback'").fetchone()[0] == 0


def test_exact_p4_03_upgrade_applies_generation_and_flashcard_migrations_and_preserves_learning_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P4-05/06 must be no-rewrite upgrades from the accepted P4-03 ledger."""
    root = tmp_path / "p4_03_upgrade"
    path = root / "courses.db"
    artifacts = runner.discover_migrations()
    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts[:4])
    courses, practice, attempts, _adapter, _grading = _services(root, "u_alice")
    course = courses.create_course("Biology")
    practice_set = practice.create_practice_set(
        course.id,
        title="Historical exact grading",
        expected_course_write_epoch=course.write_epoch,
    )
    revision = practice.create_draft_revision(
        course.id,
        practice_set.id,
        expected_course_write_epoch=course.write_epoch,
    )
    with courses._connect() as conn:
        conn.execute(
            """INSERT INTO practice_questions
               (id, practice_set_revision_id, question_type, prompt,
                answer_contract_json, explanation, objective_ids_json,
                citation_json, ordinal, created_at)
               VALUES ('qst_historical_exact', ?, 'short_answer', 'Type yes',
                       '{"kind":"exact","answer":"yes"}', '', '["kp_one"]',
                       '[]', 1, 1)""",
            (revision.id,),
        )
    practice.ready_revision(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=course.write_epoch,
    )
    _question = practice.list_questions(course.id, practice_set.id, revision.id)[0]
    attempt_id, _item_id = _submitted(
        courses, attempts, course.id, practice_set, revision, {"answer": "yes"}
    )
    with courses._connect() as conn:
        row = conn.execute(
            """SELECT attempts.owner_user_id, attempts.submitted_at,
                      items.question_id, answers.response_json,
                      questions.answer_contract_json
               FROM quiz_attempts AS attempts
               JOIN quiz_attempt_items AS items ON items.attempt_id = attempts.id
               JOIN quiz_attempt_answers AS answers
                 ON answers.attempt_item_id = items.id
               JOIN practice_questions AS questions ON questions.id = items.question_id
               WHERE attempts.id = ? AND items.id = ?""",
            (attempt_id, _item_id),
        ).fetchone()
        payload = {
            "algorithm": "exact-v1",
            "attempt_id": attempt_id,
            "attempt_item_id": _item_id,
            "question_id": row["question_id"],
            "objective_id": "kp_one",
            "module_id": "mod_one",
            "knowledge_type": "memory",
            "contract_sha256": CourseGradingRepository._digest(
                json.loads(row["answer_contract_json"])
            ),
            "response_sha256": CourseGradingRepository._digest(
                json.loads(row["response_json"])
            ),
            "is_correct": True,
            "error_type": None,
        }
        grading_json = CourseGradingRepository._json(payload)
        graded_at = float(row["submitted_at"]) + 1
        conn.execute(
            """INSERT INTO quiz_item_grading_evidence
               (id, owner_user_id, course_id, practice_set_id, attempt_id,
                attempt_item_id, question_id, objective_id, module_id,
                knowledge_type, algorithm, payload_sha256, is_correct,
                grading_json, error_type, state, created_at, applied_at)
               VALUES ('grd_historical_exact', ?, ?, ?, ?, ?, ?, 'kp_one',
                       'mod_one', 'memory', 'exact-v1', ?, 1, ?, NULL,
                       'pending', ?, NULL)""",
            (
                row["owner_user_id"],
                course.id,
                practice_set.id,
                attempt_id,
                _item_id,
                row["question_id"],
                hashlib.sha256(grading_json.encode("utf-8")).hexdigest(),
                grading_json,
                graded_at,
            ),
        )
        conn.execute(
            """UPDATE quiz_attempt_items
               SET grading_json = ?, error_type = NULL, graded_at = ?
               WHERE id = ?""",
            (
                CourseGradingRepository._json(
                    {
                        "algorithm": "exact-v1",
                        "is_correct": True,
                        "evidence_ids": ["grd_historical_exact"],
                    }
                ),
                graded_at,
                _item_id,
            ),
        )
        conn.execute(
            """UPDATE quiz_attempts
               SET state = 'graded', score_json = ?, graded_at = ?,
                   revision = revision + 1, updated_at = ?
               WHERE id = ?""",
            (
                CourseGradingRepository._json(
                    {"correct": 1, "total": 1, "fraction": 1.0}
                ),
                graded_at,
                graded_at,
                attempt_id,
            ),
        )
    with courses._connect() as conn:
        before = {
            table: conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            for table in (
                "courses",
                "practice_sets",
                "practice_set_revisions",
                "practice_questions",
                "quiz_attempts",
                "quiz_attempt_items",
                "quiz_attempt_answers",
                "quiz_item_grading_evidence",
            )
        }

    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts)
    assert ensure_course_schema(path) == tuple(range(4, 18))
    assert ensure_course_schema(path) == ()
    with courses._connect() as conn:
        after = {
            table: conn.execute(
                f"""SELECT {", ".join(f'"{column}"' for column in before[table][0].keys())}
                    FROM "{table}" ORDER BY rowid"""
            ).fetchall()
            for table in before
        }
        assert conn.execute(
            "SELECT workspace_kind FROM courses WHERE id = ?", (course.id,)
        ).fetchone()[0] == "academic_course"
        assert conn.execute("SELECT COUNT(*) FROM practice_generation_operations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM flashcard_reviews").fetchone()[0] == 0
        effective_triggers = {
            str(row[0])
            for row in conn.execute(
                """SELECT name FROM sqlite_master
                   WHERE type = 'trigger' AND name LIKE 'practice_generation_%'"""
            )
        }
        assert {
            "practice_generation_operations_terminal_immutable",
            "practice_generation_generated_revision_question_fence",
            "practice_generation_generated_revision_ready_fence",
            "practice_generation_practice_set_mode_immutable",
        } <= effective_triggers
        assert tuple(
            row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        ) == tuple(range(18))
        assert conn.execute(
            "SELECT options_json FROM practice_questions WHERE id = ?",
            (_question.id,),
        ).fetchone()[0] == "[]"
    assert after == before


def test_raw_sql_cannot_forge_a_self_consistent_wrong_exact_grade(tmp_path: Path) -> None:
    courses, practice, attempts, adapter, _grading = _services(tmp_path)
    course = courses.create_course("Forensics")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, item_id = _submitted(
        courses, attempts, course.id, practice_set, revision, {"answer": "no"}
    )
    with courses._connect() as conn:
        row = conn.execute(
            """SELECT attempts.*, items.question_id, answers.response_json,
                      questions.answer_contract_json FROM quiz_attempts AS attempts
               JOIN quiz_attempt_items AS items ON items.attempt_id = attempts.id
               JOIN quiz_attempt_answers AS answers ON answers.attempt_item_id = items.id
               JOIN practice_questions AS questions ON questions.id = items.question_id
               WHERE attempts.id = ?""",
            (attempt_id,),
        ).fetchone()
        contract_sha = hashlib.sha256(
            json.dumps(json.loads(row["answer_contract_json"]), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        forged = {
            "algorithm": "exact-v1", "attempt_id": attempt_id,
            "attempt_item_id": item_id, "question_id": row["question_id"],
            "objective_id": "kp_one", "module_id": "mod_one", "knowledge_type": "memory",
            "contract_sha256": contract_sha,
            "response_sha256": hashlib.sha256(
                json.dumps(
                    {"answer": "no"},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            "is_correct": True, "error_type": None,
        }
        forged_json = json.dumps(forged, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO quiz_item_grading_evidence
                   (id, owner_user_id, course_id, practice_set_id, attempt_id,
                    attempt_item_id, question_id, objective_id, module_id, knowledge_type,
                    algorithm, payload_sha256, is_correct, grading_json, error_type,
                    state, created_at, applied_at)
                   VALUES ('grd_forged', ?, ?, ?, ?, ?, ?, 'kp_one', 'mod_one', 'memory',
                           'exact-v1', ?, 1, ?, NULL, 'pending', 1, NULL)""",
                (
                    row["owner_user_id"], course.id, practice_set.id, attempt_id, item_id,
                    row["question_id"], hashlib.sha256(forged_json.encode()).hexdigest(), forged_json,
                ),
            )
        unrelated = {
            **forged,
            "objective_id": "kp_forged",
            "module_id": None,
            "knowledge_type": None,
            "is_correct": False,
            "error_type": "application",
        }
        unrelated_json = json.dumps(unrelated, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO quiz_item_grading_evidence
                   (id, owner_user_id, course_id, practice_set_id, attempt_id,
                    attempt_item_id, question_id, objective_id, module_id, knowledge_type,
                    algorithm, payload_sha256, is_correct, grading_json, error_type,
                    state, created_at, applied_at)
                   VALUES ('grd_unrelated', ?, ?, ?, ?, ?, ?, 'kp_forged', NULL, NULL,
                           'exact-v1', ?, 0, ?, 'application', 'unmapped', 1, 1)""",
                (
                    row["owner_user_id"], course.id, practice_set.id, attempt_id, item_id,
                    row["question_id"], hashlib.sha256(unrelated_json.encode()).hexdigest(), unrelated_json,
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE quiz_attempt_items SET grading_json = ?, error_type = NULL, graded_at = 1 WHERE id = ?",
                (json.dumps({"algorithm": "exact-v1", "is_correct": True, "evidence_ids": ["grd_forged"]}), item_id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE quiz_attempts SET state = 'graded', score_json = ?, graded_at = 1, revision = revision + 1, updated_at = 1 WHERE id = ?",
                (json.dumps({"correct": 1, "total": 1, "fraction": 1.0}), attempt_id),
            )


@pytest.mark.parametrize("terminalize", ["course", "practice", "successor"])
def test_archive_and_successor_terminalize_submitted_ungraded_attempts(
    tmp_path: Path, terminalize: str
) -> None:
    courses, practice, attempts, adapter, _grading = _services(tmp_path)
    course = courses.create_course("Terminal")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(
        courses, attempts, course.id, practice_set, revision, {"answer": "yes"}
    )
    if terminalize == "course":
        archived = courses.archive_course(course.id, expected_revision=courses.get_course(course.id).revision)
        courses.restore_course(course.id, expected_revision=archived.revision)
    elif terminalize == "practice":
        current = practice.get_practice_set(course.id, practice_set.id)
        practice.archive_practice_set(
            course.id, practice_set.id, expected_revision=current.revision,
            expected_course_write_epoch=_epoch(courses, course.id),
        )
    else:
        epoch = _epoch(courses, course.id)
        successor = practice.create_successor_revision(
            course.id, practice_set.id, expected_course_write_epoch=epoch
        )
        practice.add_question(
            course.id, practice_set.id, successor.id, question_type="short_answer",
            prompt="Again?", answer_contract={"kind": "exact", "answer": "yes"},
            objective_ids=("kp_one",), expected_course_write_epoch=epoch,
        )
        practice.ready_revision(
            course.id, practice_set.id, successor.id, expected_course_write_epoch=epoch
        )
    assert attempts.get_attempt(course.id, practice_set.id, attempt_id).attempt.state == "archived"
    with pytest.raises(CourseConflictError):
        _grade(_grading, courses, course.id, practice_set.id, attempt_id)
