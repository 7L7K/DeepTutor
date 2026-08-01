"""Bounded, append-only resource contracts for Phase 4 assessments."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from deeptutor.courses import attempt_repository, flashcard_repository, grading_repository
from deeptutor.courses.attempt_repository import CourseAssessmentRepository
from deeptutor.courses.attempt_service import CourseAssessmentService
from deeptutor.courses.flashcard_repository import CourseFlashcardRepository
from deeptutor.courses.flashcard_service import CourseFlashcardService
from deeptutor.courses.grading_repository import CourseGradingRepository
from deeptutor.courses.grading_service import CourseGradingService
from deeptutor.courses.mastery_adapter import CourseMasteryAdapter
from deeptutor.courses.practice_repository import CoursePracticeRepository
from deeptutor.courses.practice_service import CoursePracticeService
from deeptutor.courses.repository import CourseConflictError, CourseRepository
from deeptutor.learning.models import KnowledgePoint, KnowledgeType, LearningModule
from deeptutor.learning.storage import LearningStore


def _services(tmp_path: Path):
    courses = CourseRepository(tmp_path / "courses.db", "u_alice")
    practice = CoursePracticeService(CoursePracticeRepository(courses))
    attempts = CourseAssessmentService(CourseAssessmentRepository(courses))
    adapter = CourseMasteryAdapter(LearningStore(root=tmp_path / "learning"))
    grading = CourseGradingService(CourseGradingRepository(courses), adapter)
    flashcards = CourseFlashcardService(CourseFlashcardRepository(courses))
    return courses, practice, attempts, adapter, grading, flashcards


def _epoch(courses: CourseRepository, course_id: str) -> int:
    return courses.get_course(course_id).write_epoch


def _ready_practice(courses: CourseRepository, practice: CoursePracticeService, course_id: str, *, objectives=("kp_one",)):
    practice_set = practice.create_practice_set(
        course_id, title="Quiz", expected_course_write_epoch=_epoch(courses, course_id)
    )
    revision = practice.create_draft_revision(
        course_id, practice_set.id, expected_course_write_epoch=_epoch(courses, course_id)
    )
    practice.add_question(
        course_id,
        practice_set.id,
        revision.id,
        question_type="short_answer",
        prompt="Answer?",
        answer_contract={"kind": "exact", "answer": "yes"},
        objective_ids=objectives,
        expected_course_write_epoch=_epoch(courses, course_id),
    )
    practice.ready_revision(
        course_id, practice_set.id, revision.id, expected_course_write_epoch=_epoch(courses, course_id)
    )
    return practice_set, revision


def _start(courses: CourseRepository, attempts: CourseAssessmentService, course_id: str, practice_set_id: str, revision_id: str):
    return attempts.start_or_resume_attempt(
        course_id,
        practice_set_id,
        revision_id,
        expected_course_write_epoch=_epoch(courses, course_id),
        expected_practice_set_write_epoch=2,
    )


def test_attempt_and_deck_lists_are_bounded_and_paginated(tmp_path: Path) -> None:
    courses, practice, attempts, _adapter, _grading, flashcards = _services(tmp_path)
    course = courses.create_course("Physics")
    practice_set, revision = _ready_practice(courses, practice, course.id)
    first = _start(courses, attempts, course.id, practice_set.id, revision.id)
    attempts.abandon_attempt(
        course.id, practice_set.id, first.attempt.id,
        expected_course_write_epoch=_epoch(courses, course.id), expected_practice_set_write_epoch=2,
    )
    second = _start(courses, attempts, course.id, practice_set.id, revision.id)
    all_attempts = attempts.list_attempts(course.id, practice_set.id, limit=2)
    assert {item.id for item in all_attempts} == {first.attempt.id, second.attempt.id}
    assert len(attempts.list_attempts(course.id, practice_set.id, limit=1, offset=1)) == 1

    decks = [
        flashcards.create_deck(course.id, title=f"Deck {index}", expected_course_write_epoch=_epoch(courses, course.id))
        for index in range(3)
    ]
    page_one = flashcards.list_decks(course.id, limit=2)
    page_two = flashcards.list_decks(course.id, limit=2, offset=2)
    assert {item.id for item in page_one + page_two} == {item.id for item in decks}
    with pytest.raises(ValueError, match="limit"):
        attempts.list_attempts(course.id, practice_set.id, limit=101)
    with pytest.raises(ValueError, match="offset"):
        flashcards.list_decks(course.id, offset=-1)


def test_attempt_retention_limit_rejects_new_attempt_without_mutating_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses, practice, attempts, _adapter, _grading, _flashcards = _services(tmp_path)
    course = courses.create_course("Physics")
    practice_set, revision = _ready_practice(courses, practice, course.id)
    first = _start(courses, attempts, course.id, practice_set.id, revision.id)
    attempts.abandon_attempt(
        course.id, practice_set.id, first.attempt.id,
        expected_course_write_epoch=_epoch(courses, course.id), expected_practice_set_write_epoch=2,
    )
    monkeypatch.setattr(attempt_repository, "_MAX_RETAINED_ATTEMPTS_PER_PRACTICE_SET", 1)
    with pytest.raises(CourseConflictError, match="retained attempt limit"):
        _start(courses, attempts, course.id, practice_set.id, revision.id)
    assert [item.id for item in attempts.list_attempts(course.id, practice_set.id)] == [first.attempt.id]


def test_autosave_and_grading_reject_oversize_aggregates_before_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    courses, practice, attempts, adapter, grading, _flashcards = _services(tmp_path)
    course = courses.create_course("Biology")
    practice_set, revision = _ready_practice(courses, practice, course.id, objectives=("kp_one", "kp_two"))
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    adapter.service.init_modules(
        progress,
        [LearningModule(
            id="mod", name="Module", order=1,
            knowledge_points=[
                KnowledgePoint(id="kp_one", name="One", type=KnowledgeType.MEMORY, module_id="mod"),
                KnowledgePoint(id="kp_two", name="Two", type=KnowledgeType.MEMORY, module_id="mod"),
            ],
        )],
    )
    adapter.service.save(progress)
    view = _start(courses, attempts, course.id, practice_set.id, revision.id)
    item_id = view.items[0].id
    monkeypatch.setattr(attempt_repository, "_MAX_AUTOSAVE_RECEIPTS_PER_ATTEMPT", 1)
    attempts.autosave_answer(
        course.id, practice_set.id, view.attempt.id, item_id,
        response={"answer": "first"}, expected_answer_revision=1, idempotency_token="one",
        expected_course_write_epoch=_epoch(courses, course.id), expected_practice_set_write_epoch=2,
    )
    with pytest.raises(CourseConflictError, match="receipt limit"):
        attempts.autosave_answer(
            course.id, practice_set.id, view.attempt.id, item_id,
            response={"answer": "second"}, expected_answer_revision=2, idempotency_token="two",
            expected_course_write_epoch=_epoch(courses, course.id), expected_practice_set_write_epoch=2,
        )
    with courses._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM quiz_attempt_autosave_receipts WHERE attempt_id = ?", (view.attempt.id,)).fetchone()[0] == 1

    attempts.submit_attempt(
        course.id, practice_set.id, view.attempt.id,
        expected_course_write_epoch=_epoch(courses, course.id), expected_practice_set_write_epoch=2,
    )
    monkeypatch.setattr(grading_repository, "_MAX_EVIDENCE_RECORDS_PER_ATTEMPT", 1)
    with pytest.raises(CourseConflictError, match="evidence record limit"):
        grading.grade_attempt(
            course.id, practice_set.id, view.attempt.id,
            expected_course_write_epoch=_epoch(courses, course.id), expected_practice_set_write_epoch=2,
        )
    with courses._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM quiz_item_grading_evidence WHERE attempt_id = ?", (view.attempt.id,)).fetchone()[0] == 0
    monkeypatch.setattr(grading_repository, "_MAX_EVIDENCE_RECORDS_PER_ATTEMPT", 4_096)
    monkeypatch.setattr(grading_repository, "_MAX_EVIDENCE_BYTES_PER_ATTEMPT", 1)
    with pytest.raises(CourseConflictError, match="evidence byte limit"):
        grading.grade_attempt(
            course.id, practice_set.id, view.attempt.id,
            expected_course_write_epoch=_epoch(courses, course.id), expected_practice_set_write_epoch=2,
        )
    with courses._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM quiz_item_grading_evidence WHERE attempt_id = ?", (view.attempt.id,)).fetchone()[0] == 0


def test_review_cap_preserves_idempotent_replay_and_schema_guards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    courses, _practice, _attempts, _adapter, _grading, flashcards = _services(tmp_path)
    course = courses.create_course("Chemistry")
    deck = flashcards.create_deck(course.id, title="Terms", expected_course_write_epoch=course.write_epoch)
    card = flashcards.add_card(
        course.id, deck.id, prompt="H2O", answer="Water", expected_deck_revision=deck.revision,
        expected_course_write_epoch=_epoch(courses, course.id),
    )
    deck = flashcards.get_deck(course.id, deck.id, at=0).deck
    deck = flashcards.ready_deck(
        course.id, deck.id, expected_revision=deck.revision, expected_course_write_epoch=_epoch(courses, course.id)
    )
    monkeypatch.setattr(flashcard_repository, "_MAX_REVIEWS_PER_DECK", 1)
    args = dict(
        card_id=card.id, rating="good", idempotency_key="one", expected_deck_revision=deck.revision,
        expected_card_revision=card.revision, expected_course_write_epoch=_epoch(courses, course.id), now=1,
    )
    first, _schedule, _summary = flashcards.record_review(course.id, deck.id, **args)
    replay, _schedule, _summary = flashcards.record_review(course.id, deck.id, **args)
    assert replay.id == first.id
    with pytest.raises(CourseConflictError, match="review limit"):
        flashcards.record_review(course.id, deck.id, **{**args, "idempotency_key": "two", "rating": "easy", "now": 2})
    with sqlite3.connect(courses.db_path) as conn:
        triggers = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    assert {
        "quiz_attempts_retained_attempt_limit",
        "quiz_attempt_autosave_receipts_retention_limit",
        "quiz_grading_evidence_retention_limit",
        "flashcard_reviews_retention_limit",
    } <= triggers
