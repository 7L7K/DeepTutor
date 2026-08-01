"""Cross-type allocation budgets for generated Practice and Flashcards."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest

from deeptutor.courses import generation_governance
from deeptutor.courses.flashcard_generation_provider import (
    UnavailableFlashcardGenerationProvider,
    flashcard_generation_provider_available,
)
from deeptutor.courses.flashcard_generation_repository import (
    CourseFlashcardGenerationRepository,
)
from deeptutor.courses.flashcard_generation_service import CourseFlashcardGenerationService
from deeptutor.courses.generation_provider import (
    UnavailablePracticeGenerationProvider,
    practice_generation_provider_available,
)
from deeptutor.courses.generation_repository import CoursePracticeGenerationRepository
from deeptutor.courses.generation_service import CoursePracticeGenerationService
from deeptutor.courses.repository import CourseConflictError, CourseRepository


def _ready_source(courses: CourseRepository, course_id: str):
    source = courses.create_source(
        course_id,
        kind="notes",
        display_name="notes.txt",
        manifest=[],
        content_sha256="a" * 64,
    )
    course = courses.get_course(course_id)
    return courses.transition_source(
        course_id,
        source.id,
        operation_id=source.operation_id or "",
        expected_source_revision=source.revision,
        expected_course_revision=course.revision,
        expected_write_epoch=course.write_epoch,
        state="ready",
    )


def _repositories(tmp_path: Path):
    courses = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Biology")
    source = _ready_source(courses, course.id)
    return (
        courses,
        course,
        source,
        CoursePracticeGenerationRepository(courses),
        CourseFlashcardGenerationRepository(courses),
    )


def _practice(repo, course, source, key: str):
    return repo.create_generated_practice(
        course.id,
        title="Quiz",
        source_ids=[source.id],
        idempotency_key=key,
        expected_course_write_epoch=course.write_epoch,
    )


def _flashcards(repo, course, source, key: str):
    return repo.create_generated_deck(
        course.id,
        title="Cards",
        source_ids=[source.id],
        idempotency_key=key,
        expected_course_write_epoch=course.write_epoch,
    )


def test_owner_wide_outstanding_limit_spans_types_and_preserves_exact_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        generation_governance, "MAX_OUTSTANDING_GENERATION_OPERATIONS_PER_OWNER", 2
    )
    monkeypatch.setattr(
        generation_governance, "MAX_RETAINED_GENERATION_OPERATIONS_PER_OWNER", 20
    )
    monkeypatch.setattr(generation_governance, "MAX_RETAINED_GENERATION_DRAFTS_PER_OWNER", 20)
    _courses, course, source, practice, flashcards = _repositories(tmp_path)

    first = _practice(practice, course, source, "practice-1")
    second = _flashcards(flashcards, course, source, "flashcard-1")
    assert first.operation.state == second.operation.state == "queued"
    assert _practice(practice, course, source, "practice-1").operation.id == first.operation.id
    with pytest.raises(CourseConflictError, match="outstanding-operation limit"):
        _practice(practice, course, source, "practice-2")


def test_owner_wide_outstanding_admission_is_transactional_across_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        generation_governance, "MAX_OUTSTANDING_GENERATION_OPERATIONS_PER_OWNER", 1
    )
    monkeypatch.setattr(
        generation_governance, "MAX_RETAINED_GENERATION_OPERATIONS_PER_OWNER", 20
    )
    monkeypatch.setattr(generation_governance, "MAX_RETAINED_GENERATION_DRAFTS_PER_OWNER", 20)
    courses, course, source, _practice_repo, _flashcards_repo = _repositories(tmp_path)
    barrier = threading.Barrier(2)

    def create_practice() -> str:
        repository = CoursePracticeGenerationRepository(
            CourseRepository(courses.db_path, "u_alice")
        )
        barrier.wait(timeout=5)
        try:
            _practice(repository, course, source, "concurrent-practice")
            return "admitted"
        except CourseConflictError as exc:
            return str(exc)

    def create_flashcards() -> str:
        repository = CourseFlashcardGenerationRepository(
            CourseRepository(courses.db_path, "u_alice")
        )
        barrier.wait(timeout=5)
        try:
            _flashcards(repository, course, source, "concurrent-flashcards")
            return "admitted"
        except CourseConflictError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda task: task(), (create_practice, create_flashcards)))
    assert outcomes.count("admitted") == 1
    assert outcomes.count("Generation outstanding-operation limit reached") == 1
    with courses._connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM practice_generation_operations"
        ).fetchone()[0] + conn.execute(
            "SELECT COUNT(*) FROM flashcard_generation_operations"
        ).fetchone()[0]
    assert count == 1


def test_retained_operation_and_draft_budgets_preserve_failed_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _courses, course, source, practice, flashcards = _repositories(tmp_path)
    first = _practice(practice, course, source, "practice-1")
    second = _flashcards(flashcards, course, source, "flashcard-1")
    practice.fail_operation(course.id, first.operation.id, "provider_failed")
    flashcards.fail_operation(course.id, second.operation.id, "provider_failed")

    monkeypatch.setattr(
        generation_governance, "MAX_RETAINED_GENERATION_OPERATIONS_PER_OWNER", 2
    )
    monkeypatch.setattr(generation_governance, "MAX_RETAINED_GENERATION_DRAFTS_PER_OWNER", 20)
    with pytest.raises(CourseConflictError, match="retained-operation limit"):
        _practice(practice, course, source, "practice-blocked-by-history")
    assert practice.get_operation(course.id, first.operation.id).state == "failed"
    assert flashcards.get_operation(course.id, second.operation.id).state == "failed"

    monkeypatch.setattr(
        generation_governance, "MAX_RETAINED_GENERATION_OPERATIONS_PER_OWNER", 20
    )
    monkeypatch.setattr(generation_governance, "MAX_RETAINED_GENERATION_DRAFTS_PER_OWNER", 2)
    with pytest.raises(CourseConflictError, match="retained-draft limit"):
        _flashcards(flashcards, course, source, "flashcard-blocked-by-drafts")
    with _courses._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM practice_set_revisions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM flashcard_decks").fetchone()[0] == 1


def test_unavailable_providers_report_false_and_allocate_no_generated_drafts(
    tmp_path: Path,
) -> None:
    courses = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Biology")
    practice_provider = UnavailablePracticeGenerationProvider()
    flashcard_provider = UnavailableFlashcardGenerationProvider()
    practice = CoursePracticeGenerationService(
        CoursePracticeGenerationRepository(courses),
        provider=practice_provider,
        account_active=lambda _user_id: True,
    )
    flashcards = CourseFlashcardGenerationService(
        CourseFlashcardGenerationRepository(courses),
        provider=flashcard_provider,
        account_active=lambda _user_id: True,
    )

    assert not practice_generation_provider_available(practice_provider)
    assert not flashcard_generation_provider_available(flashcard_provider)
    assert not practice.provider_available()
    assert not flashcards.provider_available()
    with pytest.raises(CourseConflictError, match="provider is unavailable"):
        practice.create_generated_practice(
            course.id,
            title="Quiz",
            source_ids=["src_never"],
            idempotency_key="unavailable-practice",
            expected_course_write_epoch=course.write_epoch,
        )
    with pytest.raises(CourseConflictError, match="provider is unavailable"):
        flashcards.create_generated_deck(
            course.id,
            title="Cards",
            source_ids=["src_never"],
            idempotency_key="unavailable-flashcards",
            expected_course_write_epoch=course.write_epoch,
        )
    with courses._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM practice_generation_operations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM flashcard_generation_operations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM practice_set_revisions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM flashcard_decks").fetchone()[0] == 0
