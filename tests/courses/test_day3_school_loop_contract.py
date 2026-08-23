"""Hermetic Day 3 contracts for the private, provider-free school loop.

These tests reconstruct service and repository objects over the same private
SQLite files.  That is a persistence boundary, not a process or browser restart.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.courses.attempt_repository import CourseAssessmentRepository
from deeptutor.courses.attempt_service import CourseAssessmentService
from deeptutor.courses.flashcard_repository import CourseFlashcardRepository
from deeptutor.courses.flashcard_service import CourseFlashcardService
from deeptutor.courses.grading_repository import CourseGradingRepository
from deeptutor.courses.grading_service import CourseGradingService
from deeptutor.courses.mastery_adapter import CourseMasteryAdapter
from deeptutor.courses.practice_repository import CoursePracticeRepository
from deeptutor.courses.practice_service import CoursePracticeService
from deeptutor.courses.repository import CourseNotFoundError, CourseRepository
from deeptutor.courses.service import (
    CourseService,
    get_current_course_service,
    source_kb_name,
)
from deeptutor.learning.storage import LearningStore
from deeptutor.multi_user.models import CurrentUser
from deeptutor.multi_user.paths import (
    get_personal_path_service,
    personal_scope_for_user,
    user_context,
)


@pytest.fixture
def school_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect every user-owned path used by this contract under ``tmp_path``."""

    from deeptutor.courses import service as course_service
    from deeptutor.multi_user import paths

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", tmp_path / "legacy-missing")
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(course_service, "is_pocketbase_enabled", lambda: False)
    course_service._repository_for.cache_clear()

    def learner(user_id: str) -> CurrentUser:
        return CurrentUser(
            id=user_id,
            username=user_id,
            role="user",
            scope=personal_scope_for_user(user_id),
        )

    yield learner
    course_service._repository_for.cache_clear()


def _stage_source(
    course_service: CourseService,
    course_id: str,
    *,
    payload: bytes,
    idempotency_key: str,
) -> tuple[object, Path]:
    source = course_service.repository.create_source(
        course_id,
        kind="notes",
        display_name="lecture-notes.txt",
        manifest=[],
        content_sha256="0" * 64,
        idempotency_key=idempotency_key,
    )
    raw_root = (
        get_personal_path_service(course_service.owner_user_id)
        .get_knowledge_bases_root()
        / source_kb_name(course_id, source.id)
        / "raw"
    )
    source_root = raw_root / source.id
    source_root.mkdir(parents=True, exist_ok=True)
    uploaded_path = source_root / "lecture-notes.txt"
    uploaded_path.write_bytes(payload)
    manifest = [
        {
            "path": f"{source.id}/lecture-notes.txt",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    ]
    encoded = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    source = course_service.repository.update_processing_source_manifest(
        course_id,
        source.id,
        operation_id=source.operation_id or "",
        expected_revision=source.revision,
        manifest=manifest,
        content_sha256=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    )
    return source, uploaded_path


def _learning_services(
    courses: CourseRepository,
    learning_root: Path,
) -> tuple[
    CoursePracticeService,
    CourseAssessmentService,
    CourseGradingService,
    CourseFlashcardService,
]:
    return (
        CoursePracticeService(CoursePracticeRepository(courses)),
        CourseAssessmentService(CourseAssessmentRepository(courses)),
        CourseGradingService(
            CourseGradingRepository(courses),
            CourseMasteryAdapter(LearningStore(root=learning_root)),
        ),
        CourseFlashcardService(CourseFlashcardRepository(courses)),
    )


def _denial(operation) -> tuple[type[Exception], str]:
    with pytest.raises(CourseNotFoundError) as raised:
        operation()
    return type(raised.value), str(raised.value)


def test_two_learners_keep_same_titled_courses_and_same_named_source_bytes_isolated(
    school_runtime,
) -> None:
    alice = school_runtime("u_alice")
    bob = school_runtime("u_bob")

    with user_context(alice):
        alice_service = get_current_course_service()
        alice_course = alice_service.create("Biology")
        alice_source, alice_file = _stage_source(
            alice_service,
            alice_course.id,
            payload=b"alice-specific cell notes\n",
            idempotency_key="alice-lecture-notes",
        )

    with user_context(bob):
        bob_service = get_current_course_service()
        bob_course = bob_service.create("Biology")
        bob_source, bob_file = _stage_source(
            bob_service,
            bob_course.id,
            payload=b"bob-specific genetics notes\n",
            idempotency_key="bob-lecture-notes",
        )

        foreign_course = _denial(lambda: bob_service.get(alice_course.id))
        missing_course = _denial(lambda: bob_service.get("crs_" + "0" * 32))
        foreign_source = _denial(
            lambda: bob_service.repository.get_source(bob_course.id, alice_source.id)
        )
        missing_source = _denial(
            lambda: bob_service.repository.get_source(
                bob_course.id, "src_" + "0" * 32
            )
        )

    assert alice_course.title == bob_course.title == "Biology"
    assert alice_course.id != bob_course.id
    assert alice_service.repository.db_path != bob_service.repository.db_path
    assert alice_source.display_name == bob_source.display_name == "lecture-notes.txt"
    assert alice_source.content_sha256 != bob_source.content_sha256
    assert alice_file.name == bob_file.name == "lecture-notes.txt"
    assert alice_file != bob_file
    assert alice_file.read_bytes() == b"alice-specific cell notes\n"
    assert bob_file.read_bytes() == b"bob-specific genetics notes\n"
    assert alice_file.is_relative_to(
        get_personal_path_service(alice.id).get_knowledge_bases_root()
    )
    assert bob_file.is_relative_to(
        get_personal_path_service(bob.id).get_knowledge_bases_root()
    )
    assert foreign_course == missing_course
    assert foreign_source == missing_source


def test_manual_practice_grade_and_flashcard_review_survive_service_reconstruction(
    school_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alice = school_runtime("u_alice")
    bob = school_runtime("u_bob")

    with user_context(alice):
        course_service = get_current_course_service()
        course = course_service.create("Chemistry")
        orphan, _source_file = _stage_source(
            course_service,
            course.id,
            payload=b"water is H2O\n",
            idempotency_key="chemistry-notes",
        )
        db_path = course_service.repository.db_path
        learning_root = get_personal_path_service(alice.id).get_workspace_dir() / "learning"
        practice, attempts, grading, flashcards = _learning_services(
            course_service.repository, learning_root
        )

        practice_set = practice.create_practice_set(
            course.id,
            title="Manual review",
            expected_course_write_epoch=course.write_epoch,
        )
        revision = practice.create_draft_revision(
            course.id,
            practice_set.id,
            expected_course_write_epoch=course.write_epoch,
        )
        question = practice.add_question(
            course.id,
            practice_set.id,
            revision.id,
            question_type="short_answer",
            prompt="What is the formula for water?",
            answer_contract={"kind": "exact", "answer": "H2O"},
            expected_course_write_epoch=course.write_epoch,
        )
        practice.ready_revision(
            course.id,
            practice_set.id,
            revision.id,
            expected_course_write_epoch=course.write_epoch,
        )
        ready_set = practice.get_practice_set(course.id, practice_set.id)

        attempt_view = attempts.start_or_resume_attempt(
            course.id,
            practice_set.id,
            revision.id,
            expected_course_write_epoch=course.write_epoch,
            expected_practice_set_write_epoch=ready_set.write_epoch,
        )
        [attempt_item] = attempt_view.items
        saved_answer = attempts.autosave_answer(
            course.id,
            practice_set.id,
            attempt_view.attempt.id,
            attempt_item.id,
            response={"answer": "H2O"},
            expected_answer_revision=1,
            idempotency_token="manual-answer",
            expected_course_write_epoch=course.write_epoch,
            expected_practice_set_write_epoch=ready_set.write_epoch,
        )
        attempts.submit_attempt(
            course.id,
            practice_set.id,
            attempt_view.attempt.id,
            expected_course_write_epoch=course.write_epoch,
            expected_practice_set_write_epoch=ready_set.write_epoch,
        )
        graded = grading.grade_attempt(
            course.id,
            practice_set.id,
            attempt_view.attempt.id,
            expected_course_write_epoch=course.write_epoch,
            expected_practice_set_write_epoch=ready_set.write_epoch,
        )

        deck = flashcards.create_deck(
            course.id,
            title="Manual cards",
            expected_course_write_epoch=course.write_epoch,
        )
        card = flashcards.add_card(
            course.id,
            deck.id,
            prompt="Formula for water?",
            answer="H2O",
            expected_deck_revision=deck.revision,
            expected_course_write_epoch=course.write_epoch,
        )
        deck = flashcards.get_deck(course.id, deck.id, at=1_000).deck
        deck = flashcards.ready_deck(
            course.id,
            deck.id,
            expected_revision=deck.revision,
            expected_course_write_epoch=course.write_epoch,
        )
        review, schedule, _summary = flashcards.record_review(
            course.id,
            deck.id,
            card_id=card.id,
            rating="good",
            idempotency_key="manual-review",
            expected_deck_revision=deck.revision,
            expected_card_revision=card.revision,
            expected_course_write_epoch=course.write_epoch,
            now=1_000,
        )

        # Reconstruct every wrapper over the same durable files.  This does not
        # claim a new process, browser, or deployed-runtime restart.
        reopened_courses = CourseRepository(db_path, alice.id)
        reopened_practice, reopened_attempts, _reopened_grading, reopened_flashcards = (
            _learning_services(reopened_courses, learning_root)
        )
        restored_attempt = reopened_attempts.get_attempt(
            course.id, practice_set.id, attempt_view.attempt.id
        )
        restored_deck = reopened_flashcards.get_deck(course.id, deck.id, at=1_000)
        with reopened_courses._connect() as connection:
            autosave_receipts = connection.execute(
                """SELECT COUNT(*) FROM quiz_attempt_autosave_receipts
                   WHERE attempt_id = ? AND idempotency_token = ?""",
                (attempt_view.attempt.id, "manual-answer"),
            ).fetchone()[0]

        monkeypatch.setattr(
            "deeptutor.api.utils.task_id_manager.TaskIDManager.get_instance",
            lambda: SimpleNamespace(get_task_metadata=lambda _operation_id: None),
        )
        reconciled = CourseService(reopened_courses).reconcile_source_for_progress(
            course.id, orphan.id
        )

    with user_context(bob):
        bob_service = get_current_course_service()
        bob_course = bob_service.create("Chemistry")
        bob_practice, bob_attempts, _bob_grading, bob_flashcards = _learning_services(
            bob_service.repository,
            get_personal_path_service(bob.id).get_workspace_dir() / "learning",
        )
        assert _denial(
            lambda: bob_practice.get_practice_set(bob_course.id, practice_set.id)
        ) == _denial(
            lambda: bob_practice.get_practice_set(
                bob_course.id, "prc_" + "0" * 32
            )
        )
        assert _denial(
            lambda: bob_attempts.get_attempt(
                bob_course.id, practice_set.id, attempt_view.attempt.id
            )
        ) == _denial(
            lambda: bob_attempts.get_attempt(
                bob_course.id, "prc_" + "0" * 32, "att_" + "0" * 32
            )
        )
        assert _denial(
            lambda: bob_flashcards.get_deck(bob_course.id, deck.id)
        ) == _denial(
            lambda: bob_flashcards.get_deck(
                bob_course.id, "dck_" + "0" * 32
            )
        )

    assert question.prompt == "What is the formula for water?"
    assert saved_answer.response == {"answer": "H2O"}
    assert graded.state == "graded"
    assert graded.score == {"correct": 1, "total": 1, "fraction": 1.0}
    assert reopened_practice.get_revision(
        course.id, practice_set.id, revision.id
    ).state == "ready"
    assert restored_attempt.attempt.state == "graded"
    assert restored_attempt.attempt.score == graded.score
    assert restored_attempt.answers[0].response == {"answer": "H2O"}
    assert autosave_receipts == 1
    assert restored_deck.review_summary.review_count == 1
    assert restored_deck.schedules[0].last_review_id == review.id
    assert restored_deck.schedules[0].next_review_at == schedule.next_review_at
    assert reconciled.state == "failed"
