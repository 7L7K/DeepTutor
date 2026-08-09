from __future__ import annotations

from contextlib import nullcontext
import hashlib
from pathlib import Path

import pytest

from deeptutor.courses.content_quality import (
    C3_BIOLOGY_PROFILE,
    ContentQualityError,
    validate_c3_output,
)
from deeptutor.courses.content_quality_repository import CourseContentQualityRepository
from deeptutor.courses.content_quality_service import CourseContentQualityService
from deeptutor.courses.attempt_repository import CourseAssessmentRepository
from deeptutor.courses.attempt_service import CourseAssessmentService
from deeptutor.courses.grading_repository import CourseGradingRepository
from deeptutor.courses.grading_service import CourseGradingService
from deeptutor.courses.flashcard_generation_models import (
    FlashcardCandidatePublication,
    FlashcardCitation,
    FlashcardSourceReceipt,
    GeneratedFlashcard,
    GeneratedFlashcardOutput,
)
from deeptutor.courses.flashcard_generation_repository import CourseFlashcardGenerationRepository
from deeptutor.courses.generation_models import (
    GeneratedPracticeOutput,
    GeneratedPracticeQuestion,
    GenerationSourceText,
    PracticeGenerationInput,
)
from deeptutor.courses.generation_provider import PracticeGenerationProvider
from deeptutor.courses.generation_repository import CoursePracticeGenerationRepository
from deeptutor.courses.generation_service import CoursePracticeGenerationService
from deeptutor.courses.practice_models import PracticeCitation, PracticeSourceReceipt
from deeptutor.courses.practice_repository import CoursePracticeRepository
from deeptutor.courses.practice_service import CoursePracticeService
from deeptutor.courses.repository import CourseRepository
from deeptutor.courses.repository import CourseConflictError
from deeptutor.courses.mastery_adapter import CourseMasteryAdapter
from deeptutor.learning.models import KnowledgePoint, KnowledgeType, LearningModule
from deeptutor.learning.storage import LearningStore


SOURCE_TEXT = (
    "[00:13:05] Oxygen is the terminal electron acceptor at the end of the "
    "aerobic electron transport chain. Oxygen accepts electrons and protons to form water."
)
SOURCE_HASH = hashlib.sha256(SOURCE_TEXT.encode()).hexdigest()


def _request() -> tuple[PracticeGenerationInput, GenerationSourceText]:
    receipt = PracticeSourceReceipt(
        source_id="src_" + "a" * 32,
        source_revision=1,
        content_sha256=SOURCE_HASH,
    )
    material = GenerationSourceText(receipt=receipt, text=SOURCE_TEXT)
    return (
        PracticeGenerationInput(
            operation_id="opg_" + "b" * 32,
            owner_user_id="u_alice",
            course_id="crs_" + "c" * 32,
            practice_set_id="prc_" + "d" * 32,
            practice_set_revision_id="prv_" + "e" * 32,
            source_material=[material],
            objective_ids=["OBJ-RESP-02"],
            item_limit=1,
            context_char_limit=12_000,
            focus="oxygen in aerobic respiration",
            difficulty="mixed",
            timing_mode="untimed",
            quality_profile=C3_BIOLOGY_PROFILE,
        ),
        material,
    )


def _output(*, prompt: str = "What is oxygen's role at the end of aerobic respiration?", objectives=None):
    request, material = _request()
    return request, material, GeneratedPracticeOutput(
        provider_label="openai",
        requested_model="gpt-5-mini",
        actual_model="gpt-5-mini-2026-07-01",
        request_id="resp_c3_quality",
        input_tokens=120,
        output_tokens=80,
        latency_ms=420,
        pricing_version="openai-gpt-5-mini-2026-08-01",
        questions=[
            GeneratedPracticeQuestion(
                question_type="short_answer",
                prompt=prompt,
                answer_contract={"kind": "exact", "answer": "It accepts electrons and protons to form water."},
                explanation="The packet says oxygen accepts electrons and protons to form water.",
                objective_ids=["OBJ-RESP-02"] if objectives is None else objectives,
                citations=[
                    PracticeCitation(
                        **material.receipt.model_dump(),
                        locator={"evidence_quote": "Oxygen accepts electrons and protons to form water."},
                    )
                ],
            )
        ],
    )


def test_c3_validator_enriches_reachable_locator_and_preserves_no_id_prompt() -> None:
    request, material, output = _output()
    checked = validate_c3_output(request=request, output=output, material=[material])
    locator = checked.questions[0].citations[0].locator
    assert locator["evidence_quote"] in SOURCE_TEXT
    assert locator["start_char"] < locator["end_char"]
    assert locator["offsets_version"] == "exact-char-v1"
    assert "src_" not in checked.questions[0].prompt


def test_c3_validator_preserves_bounded_answer_variants_and_receipt_versions() -> None:
    request, material, output = _output()
    question = GeneratedPracticeQuestion.model_validate(
        output.questions[0].model_dump(mode="json")
        | {
            "answer_contract": {
                "kind": "exact",
                "answer": "water",
                "accepted_answers": ["the water molecule"],
            }
        }
    )
    checked = validate_c3_output(
        request=request,
        output=output.model_copy(update={"questions": [question]}),
        material=[material],
    )
    assert checked.questions[0].answer_contract.accepted_answers == ["the water molecule"]
    assert checked.questions[0].citations[0].locator["offsets_version"] == "exact-char-v1"


def test_c3_validator_accepts_collective_citations_and_short_polarity_answer() -> None:
    request, _original_material, output = _output(
        prompt="Does fermentation replace glycolysis?",
    )
    source_text = (
        "Fermentation does not replace glycolysis. "
        "It lets a cell keep glycolysis running by regenerating NAD+."
    )
    material = GenerationSourceText(
        receipt=PracticeSourceReceipt(
            source_id="src_" + "f" * 32,
            source_revision=1,
            content_sha256=hashlib.sha256(source_text.encode()).hexdigest(),
        ),
        text=source_text,
    )
    request = request.model_copy(update={"source_material": [material]})
    question = GeneratedPracticeQuestion.model_validate(
        output.questions[0].model_dump(mode="json")
        | {
            "answer_contract": {"kind": "exact", "answer": "No"},
            "explanation": "Fermentation does not replace glycolysis; it regenerates NAD+ so glycolysis can continue.",
            "citations": [
                {
                    **material.receipt.model_dump(mode="json"),
                    "locator": {"evidence_quote": "Fermentation does not replace glycolysis."},
                },
                {
                    **material.receipt.model_dump(mode="json"),
                    "locator": {"evidence_quote": "It lets a cell keep glycolysis running by regenerating NAD+."},
                },
            ],
        }
    )
    checked = validate_c3_output(
        request=request,
        output=output.model_copy(update={"questions": [question]}),
        material=[material],
    )
    assert checked.questions[0].citations[0].locator["offsets_version"] == "exact-char-v1"


@pytest.mark.parametrize(
    ("prompt", "objectives", "code"),
    [
        ("What does src_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa do?", ["OBJ-RESP-02"], "PRIVACY_ID_LEAK"),
        ("What is oxygen's role at the end of aerobic respiration?", [], "OBJECTIVE_EMPTY"),
        ("What is oxygen's role at the end of aerobic respiration?", ["OBJ-RESP-01"], "OBJECTIVE_INVALID"),
    ],
)
def test_c3_validator_rejects_unsafe_or_unmapped_output(prompt, objectives, code) -> None:
    request, material, output = _output(prompt=prompt, objectives=objectives)
    with pytest.raises(ContentQualityError) as raised:
        validate_c3_output(request=request, output=output, material=[material])
    assert code in {item.code for item in raised.value.findings}


class _Provider:
    def generate(self, request):
        _request_data, material, output = _output()
        assert request.quality_profile == C3_BIOLOGY_PROFILE
        # A real provider must cite the resolved snapshot, not the fixture's
        # standalone synthetic receipt.  Keep this fake provider aligned with
        # that contract so the integration test exercises the publication
        # fence rather than failing on a test-only source mismatch.
        resolved_material = request.source_material[0]
        question = output.questions[0].model_copy(
            update={
                "citations": [
                    PracticeCitation(
                        **resolved_material.receipt.model_dump(),
                        locator={"evidence_quote": "Oxygen accepts electrons and protons to form water."},
                    )
                ]
            }
        )
        return output.model_copy(update={"questions": [question]})


class _Resolver:
    def resolve(self, *, receipts, **_kwargs):
        return [GenerationSourceText(receipt=receipts[0], text=SOURCE_TEXT)]


def _ready_source(repo: CourseRepository, course_id: str):
    source = repo.create_source(
        course_id,
        kind="document",
        display_name="lecture_06_transcript.md",
        manifest=[],
        content_sha256=SOURCE_HASH,
        operation_id="op_source_c3",
    )
    return repo.transition_source(
        course_id,
        source.id,
        operation_id=source.operation_id or "",
        expected_source_revision=source.revision,
        expected_course_revision=repo.get_course(course_id).revision,
        expected_write_epoch=repo.get_course(course_id).write_epoch,
        state="ready",
    )


def test_c3_quality_profile_validates_before_ready_publication(tmp_path: Path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Biology 101")
    source = _ready_source(repo, course.id)
    service = CoursePracticeGenerationService(
        CoursePracticeGenerationRepository(repo),
        provider=_Provider(),
        source_text_resolver=_Resolver(),
        account_active=lambda _owner: True,
        identity_lock=lambda: nullcontext(),
    )
    request = service.create_generated_practice(
        course.id,
        title="Cellular respiration quality quiz",
        source_ids=[source.id],
        objective_ids=["OBJ-RESP-02"],
        idempotency_key="c3-quality-operation",
        expected_course_write_epoch=repo.get_course(course.id).write_epoch,
        item_limit=1,
        quality_profile=C3_BIOLOGY_PROFILE,
    )
    completed = service.run_operation(course.id, request.operation.id)
    assert completed.state == "completed"
    practice = CoursePracticeService(CoursePracticeRepository(repo))
    revision = practice.get_revision(course.id, completed.practice_set_id, completed.practice_set_revision_id)
    assert revision.state == "ready"
    assert revision.generation_receipt is not None
    assert revision.generation_receipt["content_quality"] == "passed"
    question = practice.list_questions(course.id, completed.practice_set_id, revision.id)[0]
    assert question.citations[0].locator["start_char"] >= 0


def test_quality_report_review_and_invalidation_are_append_only(tmp_path: Path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Biology 101")
    practice = CoursePracticeService(CoursePracticeRepository(repo))
    practice_set = practice.create_practice_set(
        course.id, title="Quality review", expected_course_write_epoch=course.write_epoch
    )
    revision = practice.create_draft_revision(
        course.id, practice_set.id, expected_course_write_epoch=repo.get_course(course.id).write_epoch
    )
    question = practice.add_question(
        course.id,
        practice_set.id,
        revision.id,
        question_type="short_answer",
        prompt="What does oxygen form?",
        answer_contract={"kind": "exact", "answer": "water"},
        objective_ids=["OBJ-RESP-02"],
        expected_course_write_epoch=repo.get_course(course.id).write_epoch,
    )
    practice.ready_revision(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=repo.get_course(course.id).write_epoch,
    )
    quality = CourseContentQualityRepository(repo)
    report = quality.report_question(
        course.id, practice_set.id, revision.id, question.id, reason="The answer key is flawed"
    )
    assert report["state"] == "reported"
    resolved, evidence_ids = quality.resolve_report(
        course.id,
        report["id"],
        decision="invalidate",
        reviewer_user_id="u_alice",
        note="Reviewed against the approved source packet",
    )
    assert resolved["state"] == "invalidated"
    assert evidence_ids == []
    assert quality.invalidated_question_ids(course.id) == {question.id}
    with pytest.raises(CourseConflictError):
        quality.resolve_report(
            course.id,
            report["id"],
            decision="reject",
            reviewer_user_id="u_alice",
            note="duplicate review",
        )


def test_invalidation_archives_already_derived_review_cards_and_keeps_history(
    tmp_path: Path,
) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Biology 101")
    source = _ready_source(repo, course.id)
    practice = CoursePracticeService(CoursePracticeRepository(repo))
    practice_set = practice.create_practice_set(
        course.id, title="Quality review", expected_course_write_epoch=course.write_epoch
    )
    revision = practice.create_draft_revision(
        course.id, practice_set.id, expected_course_write_epoch=repo.get_course(course.id).write_epoch
    )
    question = practice.add_question(
        course.id,
        practice_set.id,
        revision.id,
        question_type="short_answer",
        prompt="What does oxygen form?",
        answer_contract={"kind": "exact", "answer": "water"},
        objective_ids=["OBJ-RESP-02"],
        expected_course_write_epoch=repo.get_course(course.id).write_epoch,
    )
    practice.ready_revision(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=repo.get_course(course.id).write_epoch,
    )

    flashcards = CourseFlashcardGenerationRepository(repo)
    request = flashcards.create_generated_deck(
        course.id,
        title="Derived Review",
        source_ids=[source.id],
        objective_ids=["OBJ-RESP-02"],
        idempotency_key="derived-review-c3",
        expected_course_write_epoch=repo.get_course(course.id).write_epoch,
        item_limit=1,
        generation_brief={
            "focus": "oxygen",
            "desired_count": 1,
            "card_type_mix": ["recall"],
            "difficulty": "mixed",
            "answer_length": "short",
            "include_hints": False,
        },
        origin={
            "kind": "practice_remediation",
            "practice_attempt_id": "att_" + "a" * 32,
            "practice_set_id": practice_set.id,
            "practice_set_revision_id": revision.id,
            "practice_question_ids": [question.id],
        },
    )
    running, claimed = flashcards.claim_operation(course.id, request.operation.id)
    assert claimed and running.state == "running"
    receipt = FlashcardSourceReceipt(
        source_id=source.id,
        source_revision=source.revision,
        content_sha256=source.content_sha256,
    )
    staged = flashcards.stage_candidates(
        course.id,
        request.operation.id,
        GeneratedFlashcardOutput(
            provider_label="deterministic-local",
            cards=[
                GeneratedFlashcard(
                    prompt="What does oxygen form in aerobic respiration?",
                    answer="water",
                    citations=[FlashcardCitation(**receipt.model_dump())],
                )
            ],
        ),
        account_active=True,
        material_receipts=[receipt],
    )
    published = flashcards.publish_candidates(
        course.id,
        request.operation.id,
        FlashcardCandidatePublication(
            candidate_ids=[staged.candidates[0].candidate_id],
            expected_candidate_revision=staged.candidate_revision,
        ),
        account_active=True,
    )
    assert published.state == "completed"

    quality = CourseContentQualityRepository(repo)
    report = quality.report_question(
        course.id, practice_set.id, revision.id, question.id, reason="The answer key is flawed"
    )
    resolved, _evidence_ids = quality.resolve_report(
        course.id,
        report["id"],
        decision="invalidate",
        reviewer_user_id="u_alice",
        note="Reviewed against the approved source packet",
    )
    assert resolved["state"] == "invalidated"
    assert quality.invalidated_review_operation_ids(course.id, question.id) == [request.operation.id]
    with repo._connect() as conn:
        deck = conn.execute(
            "SELECT state FROM flashcard_decks WHERE id = ?", (request.deck_id,)
        ).fetchone()
        card = conn.execute(
            "SELECT state FROM flashcards WHERE deck_id = ?", (request.deck_id,)
        ).fetchone()
        operation = conn.execute(
            "SELECT state FROM flashcard_generation_operations WHERE id = ?",
            (request.operation.id,),
        ).fetchone()
    assert deck["state"] == "archived"
    assert card["state"] == "archived"
    assert operation["state"] == "completed"


def test_invalidation_removes_graded_learning_effect_and_remediation_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reviewed bad question is excluded without rewriting immutable grade rows."""
    courses = CourseRepository(tmp_path / "courses.db", "u_alice")
    practice = CoursePracticeService(CoursePracticeRepository(courses))
    attempts = CourseAssessmentService(CourseAssessmentRepository(courses))
    learning_root = tmp_path / "learning"
    adapter = CourseMasteryAdapter(LearningStore(root=learning_root))
    grading = CourseGradingService(CourseGradingRepository(courses), adapter)
    course = courses.create_course("Biology 101")
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    adapter.service.init_modules(
        progress,
        [LearningModule(
            id="mod_resp", name="Cellular respiration", order=1,
            knowledge_points=[KnowledgePoint(
                id="OBJ-RESP-02", name="Oxygen role", type=KnowledgeType.MEMORY,
                module_id="mod_resp",
            )],
        )],
    )
    adapter.service.save(progress)
    practice_set = practice.create_practice_set(
        course.id, title="C3 quality quiz", expected_course_write_epoch=course.write_epoch
    )
    revision = practice.create_draft_revision(
        course.id, practice_set.id,
        expected_course_write_epoch=courses.get_course(course.id).write_epoch,
    )
    question = practice.add_question(
        course.id, practice_set.id, revision.id,
        question_type="short_answer",
        prompt="What is oxygen's role at the end of the aerobic electron transport chain?",
        answer_contract={"kind": "exact", "answer": "water"},
        objective_ids=["OBJ-RESP-02"],
        expected_course_write_epoch=courses.get_course(course.id).write_epoch,
    )
    practice.ready_revision(
        course.id, practice_set.id, revision.id,
        expected_course_write_epoch=courses.get_course(course.id).write_epoch,
    )
    view = attempts.start_or_resume_attempt(
        course.id, practice_set.id, revision.id,
        expected_course_write_epoch=courses.get_course(course.id).write_epoch,
        expected_practice_set_write_epoch=2,
    )
    item = view.items[0]
    attempts.autosave_answer(
        course.id, practice_set.id, view.attempt.id, item.id,
        response={"answer": "electron donor"}, expected_answer_revision=1,
        idempotency_token="c3-quality-answer",
        expected_course_write_epoch=courses.get_course(course.id).write_epoch,
        expected_practice_set_write_epoch=2,
    )
    attempts.submit_attempt(
        course.id, practice_set.id, view.attempt.id,
        expected_course_write_epoch=courses.get_course(course.id).write_epoch,
        expected_practice_set_write_epoch=2,
    )
    graded = grading.grade_attempt(
        course.id, practice_set.id, view.attempt.id,
        expected_course_write_epoch=courses.get_course(course.id).write_epoch,
        expected_practice_set_write_epoch=2,
    )
    assert graded.score == {"correct": 0, "total": 1, "fraction": 0.0}

    class _Paths:
        def get_workspace_dir(self) -> Path:
            return tmp_path

    monkeypatch.setattr(
        "deeptutor.courses.content_quality_service.get_personal_path_service",
        lambda _owner: _Paths(),
    )
    quality_repository = CourseContentQualityRepository(courses)
    report = quality_repository.report_question(
        course.id, practice_set.id, revision.id, question.id,
        reason="The answer key does not match the approved source.",
    )
    _resolved, invalidated_evidence_ids = CourseContentQualityService(
        quality_repository
    ).resolve_report(
        course.id, report["id"], decision="invalidate", reviewer_user_id="u_alice",
        note="Reviewed against the approved Biology packet.",
    )
    assert invalidated_evidence_ids

    attempt_view = attempts.get_attempt(course.id, practice_set.id, view.attempt.id)
    effective = CourseContentQualityService(quality_repository).effective_result(
        course.id, practice_set.id, attempt_view
    )
    assert effective["score"] == {"correct": 0, "total": 0, "fraction": 0.0}
    assert effective["invalidated_question_ids"] == [question.id]
    with pytest.raises(CourseConflictError, match="no missed answers"):
        grading.remediation_scope(course.id, view.attempt.id)
    updated_progress = adapter.service.get_or_create(f"lp_{course.id}")
    assert updated_progress.quiz_attempts == []
    assert updated_progress.error_records == []
    assert updated_progress.grading_evidence_receipts == {}
