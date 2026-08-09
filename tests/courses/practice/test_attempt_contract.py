"""Adversarial P4-02B contracts for durable Course-owned quiz attempts.

These tests intentionally exercise the assessment service rather than an HTTP
adapter: the service is where opaque ownership, non-enumerating absence, and
the Course database transaction are jointly enforceable.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3

import pytest

from deeptutor.courses.attempt_repository import CourseAssessmentRepository
from deeptutor.courses.attempt_service import CourseAssessmentService
from deeptutor.courses.migrations import runner
from deeptutor.courses.migrations.runner import CourseMigrationError, ensure_course_schema
from deeptutor.courses.practice_repository import CoursePracticeRepository
from deeptutor.courses.practice_service import CoursePracticeService
from deeptutor.courses.repository import (
    CourseConflictError,
    CourseNotFoundError,
    CourseRepository,
)


def _services(
    db_path: Path, owner: str
) -> tuple[CourseRepository, CoursePracticeService, CourseAssessmentService]:
    courses = CourseRepository(db_path, owner)
    practice = CoursePracticeService(CoursePracticeRepository(courses))
    assessment = CourseAssessmentService(CourseAssessmentRepository(courses))
    return courses, practice, assessment


def _epoch(courses: CourseRepository, course_id: str) -> int:
    return courses.get_course(course_id).write_epoch


def _ready_practice(
    courses: CourseRepository,
    practice: CoursePracticeService,
    course_id: str,
    *,
    title: str = "Week 1",
    question_count: int = 2,
):
    epoch = _epoch(courses, course_id)
    practice_set = practice.create_practice_set(
        course_id, title=title, expected_course_write_epoch=epoch
    )
    revision = practice.create_draft_revision(
        course_id, practice_set.id, expected_course_write_epoch=epoch
    )
    questions = []
    for ordinal in range(1, question_count + 1):
        questions.append(
            practice.add_question(
                course_id,
                practice_set.id,
                revision.id,
                question_type="short_answer",
                prompt=f"Question {ordinal}?",
                answer_contract={"kind": "exact", "answer": str(ordinal)},
                ordinal=ordinal,
                expected_course_write_epoch=epoch,
            )
        )
    practice.ready_revision(
        course_id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=epoch,
    )
    return practice_set, revision, questions


def _start(
    service: CourseAssessmentService,
    courses: CourseRepository,
    course_id: str,
    practice_set_id: str,
    *,
    practice_set_revision_id: str,
):
    with courses._connect() as conn:
        practice_set = conn.execute(
            "SELECT write_epoch FROM practice_sets WHERE id = ? AND course_id = ?",
            (practice_set_id, course_id),
        ).fetchone()
    assert practice_set is not None
    return service.start_or_resume_attempt(
        course_id,
        practice_set_id,
        practice_set_revision_id,
        expected_course_write_epoch=_epoch(courses, course_id),
        expected_practice_set_write_epoch=int(practice_set["write_epoch"]),
    ).attempt


def _item_ids(courses: CourseRepository, attempt_id: str) -> list[str]:
    with courses._connect() as conn:
        return [
            str(row["id"])
            for row in conn.execute(
                "SELECT id FROM quiz_attempt_items WHERE attempt_id = ? ORDER BY display_ordinal, id",
                (attempt_id,),
            )
        ]


def _answer_row(courses: CourseRepository, item_id: str) -> sqlite3.Row:
    with courses._connect() as conn:
        row = conn.execute(
            "SELECT * FROM quiz_attempt_answers WHERE attempt_item_id = ?", (item_id,)
        ).fetchone()
    assert row is not None
    return row


def test_same_title_two_user_courses_never_share_attempts_or_items(tmp_path: Path) -> None:
    alice_courses, alice_practice, alice_attempts = _services(
        tmp_path / "alice" / "courses.db", "u_alice"
    )
    bob_courses, bob_practice, bob_attempts = _services(
        tmp_path / "bob" / "courses.db", "u_bob"
    )
    alice_course = alice_courses.create_course("Biology")
    bob_course = bob_courses.create_course("Biology")
    alice_set, alice_revision, _ = _ready_practice(
        alice_courses, alice_practice, alice_course.id
    )
    bob_set, bob_revision, _ = _ready_practice(
        bob_courses, bob_practice, bob_course.id
    )

    alice_attempt = _start(
        alice_attempts, alice_courses, alice_course.id, alice_set.id,
        practice_set_revision_id=alice_revision.id,
    )
    bob_attempt = _start(
        bob_attempts, bob_courses, bob_course.id, bob_set.id,
        practice_set_revision_id=bob_revision.id,
    )

    assert alice_attempt.id != bob_attempt.id
    assert alice_attempt.practice_set_revision_id == alice_revision.id
    assert bob_attempt.practice_set_revision_id == bob_revision.id
    assert len(_item_ids(alice_courses, alice_attempt.id)) == 2
    assert len(_item_ids(bob_courses, bob_attempt.id)) == 2
    with pytest.raises(CourseNotFoundError, match="Assessment resource not found"):
        bob_attempts.get_attempt(bob_course.id, bob_set.id, alice_attempt.id)


def test_foreign_and_missing_course_set_revision_attempt_and_item_ids_are_identical_404s(
    tmp_path: Path,
) -> None:
    courses, practice, attempts = _services(tmp_path / "courses.db", "u_alice")
    first = courses.create_course("Biology")
    second = courses.create_course("Biology")
    practice_set, revision, _ = _ready_practice(courses, practice, first.id)
    attempt = _start(
        attempts, courses, first.id, practice_set.id,
        practice_set_revision_id=revision.id,
    )
    item_id = _item_ids(courses, attempt.id)[0]

    operations = (
        lambda: attempts.start_or_resume_attempt(
            "crs_missing", practice_set.id, revision.id,
            expected_course_write_epoch=1, expected_practice_set_write_epoch=1,
        ),
        lambda: attempts.start_or_resume_attempt(
            second.id, practice_set.id, revision.id,
            expected_course_write_epoch=_epoch(courses, second.id), expected_practice_set_write_epoch=1,
        ),
        lambda: attempts.get_attempt(first.id, practice_set.id, "att_missing"),
        lambda: attempts.get_attempt(second.id, practice_set.id, attempt.id),
        lambda: attempts.get_attempt("crs_missing", practice_set.id, attempt.id),
        lambda: attempts.list_attempts("crs_missing", practice_set.id),
        lambda: attempts.autosave_answer(
            first.id, practice_set.id, attempt.id, "ati_missing", response={"answer": "1"},
            expected_answer_revision=1, idempotency_token="missing-item-token",
            expected_course_write_epoch=_epoch(courses, first.id), expected_practice_set_write_epoch=2,
        ),
        lambda: attempts.autosave_answer(
            second.id, practice_set.id, attempt.id, item_id, response={"answer": "1"},
            expected_answer_revision=1, idempotency_token="foreign-item-token",
            expected_course_write_epoch=_epoch(courses, second.id), expected_practice_set_write_epoch=2,
        ),
        lambda: attempts.start_or_resume_attempt(
            first.id, practice_set.id, "prv_missing",
            expected_course_write_epoch=_epoch(courses, first.id), expected_practice_set_write_epoch=2,
        ),
    )
    for operation in operations:
        with pytest.raises(CourseNotFoundError) as raised:
            operation()
        assert str(raised.value) == "Assessment resource not found"
    assert revision.id != "prv_missing"


def test_missing_attempt_does_not_leak_archived_parent_state(tmp_path: Path) -> None:
    courses, practice, attempts = _services(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Biology")
    practice_set, _, _ = _ready_practice(courses, practice, course.id)
    courses.archive_course(course.id, expected_revision=course.revision)

    with pytest.raises(CourseNotFoundError) as raised:
        attempts.submit_attempt(
            course.id,
            practice_set.id,
            "att_missing",
            expected_course_write_epoch=course.write_epoch,
            expected_practice_set_write_epoch=2,
        )
    assert str(raised.value) == "Assessment resource not found"


def test_start_binds_the_current_ready_revision_and_freezes_question_order(tmp_path: Path) -> None:
    courses, practice, attempts = _services(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Chemistry")
    practice_set, first_revision, first_questions = _ready_practice(
        courses, practice, course.id, question_count=3
    )
    first_attempt = _start(
        attempts, courses, course.id, practice_set.id,
        practice_set_revision_id=first_revision.id,
    )
    with courses._connect() as conn:
        initial = conn.execute(
            "SELECT question_id, display_ordinal FROM quiz_attempt_items WHERE attempt_id = ? ORDER BY display_ordinal",
            (first_attempt.id,),
        ).fetchall()
    assert [(row["question_id"], row["display_ordinal"]) for row in initial] == [
        (question.id, number) for number, question in enumerate(first_questions, start=1)
    ]
    attempts.abandon_attempt(
        course.id, practice_set.id, first_attempt.id,
        expected_course_write_epoch=_epoch(courses, course.id),
        expected_practice_set_write_epoch=2,
    )

    successor = practice.create_successor_revision(
        course.id, practice_set.id, expected_course_write_epoch=_epoch(courses, course.id)
    )
    practice.add_question(
        course.id,
        practice_set.id,
        successor.id,
        question_type="short_answer",
        prompt="Successor only?",
        answer_contract={"kind": "exact", "answer": "yes"},
        expected_course_write_epoch=_epoch(courses, course.id),
    )
    practice.ready_revision(
        course.id,
        practice_set.id,
        successor.id,
        expected_course_write_epoch=_epoch(courses, course.id),
    )
    second_attempt = _start(
        attempts, courses, course.id, practice_set.id,
        practice_set_revision_id=successor.id,
    )

    assert first_attempt.practice_set_revision_id == first_revision.id
    assert second_attempt.practice_set_revision_id == successor.id
    with courses._connect() as conn:
        original = conn.execute(
            "SELECT question_id, display_ordinal FROM quiz_attempt_items WHERE attempt_id = ? ORDER BY display_ordinal",
            (first_attempt.id,),
        ).fetchall()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE quiz_attempt_items SET display_ordinal = 99 WHERE attempt_id = ? AND display_ordinal = 1",
                (first_attempt.id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE quiz_attempts SET practice_set_revision_id = ? WHERE id = ?",
                (successor.id, first_attempt.id),
            )
    assert [(row["question_id"], row["display_ordinal"]) for row in original] == [
        (question.id, number) for number, question in enumerate(first_questions, start=1)
    ]


def test_item_presentations_cannot_reorder_or_change_revision_membership(tmp_path: Path) -> None:
    courses, practice, attempts = _services(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Anatomy")
    practice_set, revision, questions = _ready_practice(
        courses, practice, course.id, question_count=2
    )

    # Presentation metadata may add option/value rendering facts, but the
    # server-derived immutable revision remains the membership and order source.
    view = attempts.start_or_resume_attempt(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=_epoch(courses, course.id),
        expected_practice_set_write_epoch=2,
        item_presentations=(
            {
                "question_id": questions[0].id,
                "display_ordinal": 1,
                "option_order": ["b", "a"],
            },
            {
                "question_id": questions[1].id,
                "display_ordinal": 2,
                "randomized_values": {"variant": 3},
            },
        ),
    )
    assert [(item.question_id, item.display_ordinal) for item in view.items] == [
        (questions[0].id, 1),
        (questions[1].id, 2),
    ]
    assert view.items[0].option_order == ["b", "a"]
    assert view.items[1].randomized_values == {"variant": 3}

    abandoned = attempts.abandon_attempt(
        course.id,
        practice_set.id,
        view.attempt.id,
        expected_course_write_epoch=_epoch(courses, course.id),
        expected_practice_set_write_epoch=2,
    )
    assert abandoned.state == "abandoned"
    with pytest.raises(ValueError, match="server-derived|cover each"):
        attempts.start_or_resume_attempt(
            course.id,
            practice_set.id,
            revision.id,
            expected_course_write_epoch=_epoch(courses, course.id),
            expected_practice_set_write_epoch=2,
            item_presentations=(
                {"question_id": questions[0].id, "display_ordinal": 1},
                {"question_id": "qst_forged", "display_ordinal": 2},
            ),
        )


def test_start_auto_resumes_one_in_progress_attempt_and_rejects_noncurrent_revisions(tmp_path: Path) -> None:
    courses, practice, attempts = _services(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Physics")
    practice_set, revision, _ = _ready_practice(courses, practice, course.id)

    first = _start(
        attempts, courses, course.id, practice_set.id,
        practice_set_revision_id=revision.id,
    )
    replay = _start(
        attempts, courses, course.id, practice_set.id,
        practice_set_revision_id=revision.id,
    )
    resume = _start(
        attempts, courses, course.id, practice_set.id,
        practice_set_revision_id=revision.id,
    )
    assert replay.id == first.id == resume.id
    assert [item.id for item in attempts.list_attempts(course.id, practice_set.id)] == [first.id]

    with pytest.raises(CourseNotFoundError, match="Assessment resource not found"):
        attempts.start_or_resume_attempt(
            course.id,
            practice_set.id,
            "prv_foreign_or_missing",
            expected_course_write_epoch=_epoch(courses, course.id),
            expected_practice_set_write_epoch=2,
        )


def test_publishing_successor_archives_stale_in_progress_attempt_before_new_start(
    tmp_path: Path,
) -> None:
    courses, practice, attempts = _services(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Physics")
    practice_set, revision, _ = _ready_practice(courses, practice, course.id)
    first = _start(
        attempts,
        courses,
        course.id,
        practice_set.id,
        practice_set_revision_id=revision.id,
    )

    successor = practice.create_successor_revision(
        course.id,
        practice_set.id,
        expected_course_write_epoch=_epoch(courses, course.id),
    )
    practice.add_question(
        course.id,
        practice_set.id,
        successor.id,
        question_type="short_answer",
        prompt="Successor?",
        answer_contract={"kind": "exact", "answer": "yes"},
        expected_course_write_epoch=_epoch(courses, course.id),
    )
    practice.ready_revision(
        course.id,
        practice_set.id,
        successor.id,
        expected_course_write_epoch=_epoch(courses, course.id),
    )

    assert attempts.get_attempt(
        course.id, practice_set.id, first.id
    ).attempt.state == "archived"
    second = _start(
        attempts,
        courses,
        course.id,
        practice_set.id,
        practice_set_revision_id=successor.id,
    )
    assert second.state == "in_progress"
    assert second.id != first.id
    assert [
        item.state
        for item in attempts.list_attempts(
            course.id, practice_set.id, include_archived=True
        )
    ].count("in_progress") == 1


def test_autosave_is_compare_and_swap_and_replay_is_idempotent(tmp_path: Path) -> None:
    courses, practice, attempts = _services(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Algebra")
    practice_set, _, _ = _ready_practice(courses, practice, course.id, question_count=1)
    attempt = _start(
        attempts, courses, course.id, practice_set.id,
        practice_set_revision_id=practice.get_practice_set(course.id, practice_set.id).current_revision_id,
    )
    item_id = _item_ids(courses, attempt.id)[0]

    saved = attempts.autosave_answer(
        course.id,
        practice_set.id,
        attempt.id,
        item_id,
        response={"answer": "1"},
        expected_answer_revision=1,
        idempotency_token="answer-token-0001",
        expected_course_write_epoch=_epoch(courses, course.id),
        expected_practice_set_write_epoch=2,
    )
    replay = attempts.autosave_answer(
        course.id,
        practice_set.id,
        attempt.id,
        item_id,
        response={"answer": "1"},
        expected_answer_revision=1,
        idempotency_token="answer-token-0001",
        expected_course_write_epoch=_epoch(courses, course.id),
        expected_practice_set_write_epoch=2,
    )
    assert saved.revision == replay.revision == 2
    with pytest.raises(CourseConflictError, match="[Ss]tale|[Rr]evision"):
        attempts.autosave_answer(
            course.id,
            practice_set.id,
            attempt.id,
            item_id,
            response={"answer": "stale overwrite"},
            expected_answer_revision=1,
            idempotency_token="answer-token-0002",
            expected_course_write_epoch=_epoch(courses, course.id),
            expected_practice_set_write_epoch=2,
        )
    with pytest.raises(CourseConflictError, match="[Ii]dempotency"):
        attempts.autosave_answer(
            course.id,
            practice_set.id,
            attempt.id,
            item_id,
            response={"answer": "different"},
            expected_answer_revision=1,
            idempotency_token="answer-token-0001",
            expected_course_write_epoch=_epoch(courses, course.id),
            expected_practice_set_write_epoch=2,
        )
    assert _answer_row(courses, item_id)["revision"] == 2


@pytest.mark.parametrize(
    "response, message",
    [
        ("not-an-object", "exactly"),
        ({"answer": "yes", "extra": True}, "exactly"),
        ({"answer": 7}, "exactly"),
        ({"answer": "x" * 4_001}, "too large"),
    ],
)
def test_autosave_rejects_malformed_or_oversized_exact_answers_before_persistence(
    tmp_path: Path, response, message: str,
) -> None:
    courses, practice, attempts = _services(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Biology")
    practice_set, revision, _ = _ready_practice(
        courses, practice, course.id, question_count=1,
    )
    attempt = _start(
        attempts,
        courses,
        course.id,
        practice_set.id,
        practice_set_revision_id=revision.id,
    )
    item_id = _item_ids(courses, attempt.id)[0]
    with pytest.raises(ValueError, match=message):
        attempts.autosave_answer(
            course.id,
            practice_set.id,
            attempt.id,
            item_id,
            response=response,
            expected_answer_revision=1,
            idempotency_token="invalid-answer-token",
            expected_course_write_epoch=_epoch(courses, course.id),
            expected_practice_set_write_epoch=2,
        )
    assert _answer_row(courses, item_id)["response_json"] is None
    with courses._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM quiz_attempt_autosave_receipts WHERE attempt_id = ?",
            (attempt.id,),
        ).fetchone()[0] == 0


def test_old_autosave_token_replays_its_original_result_after_a_newer_save(
    tmp_path: Path,
) -> None:
    courses, practice, attempts = _services(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Algebra")
    practice_set, revision, _ = _ready_practice(
        courses, practice, course.id, question_count=1
    )
    attempt = _start(
        attempts,
        courses,
        course.id,
        practice_set.id,
        practice_set_revision_id=revision.id,
    )
    item_id = _item_ids(courses, attempt.id)[0]
    first = attempts.autosave_answer(
        course.id,
        practice_set.id,
        attempt.id,
        item_id,
        response={"answer": "first"},
        expected_answer_revision=1,
        idempotency_token="answer-token-first",
        expected_course_write_epoch=_epoch(courses, course.id),
        expected_practice_set_write_epoch=2,
    )
    later = attempts.autosave_answer(
        course.id,
        practice_set.id,
        attempt.id,
        item_id,
        response={"answer": "later"},
        expected_answer_revision=first.revision,
        idempotency_token="answer-token-later",
        expected_course_write_epoch=_epoch(courses, course.id),
        expected_practice_set_write_epoch=2,
    )
    replay = attempts.autosave_answer(
        course.id,
        practice_set.id,
        attempt.id,
        item_id,
        response={"answer": "first"},
        expected_answer_revision=1,
        idempotency_token="answer-token-first",
        expected_course_write_epoch=_epoch(courses, course.id),
        expected_practice_set_write_epoch=2,
    )

    assert (first.response, first.revision) == ({"answer": "first"}, 2)
    assert (later.response, later.revision) == ({"answer": "later"}, 3)
    assert (replay.response, replay.revision, replay.answered_at) == (
        first.response,
        first.revision,
        first.answered_at,
    )
    assert _answer_row(courses, item_id)["revision"] == 3


def test_submit_is_idempotent_freezes_answers_and_abandon_is_idempotent(tmp_path: Path) -> None:
    courses, practice, attempts = _services(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("History")
    practice_set, _, _ = _ready_practice(courses, practice, course.id, question_count=1)
    attempt = _start(
        attempts, courses, course.id, practice_set.id,
        practice_set_revision_id=practice.get_practice_set(course.id, practice_set.id).current_revision_id,
    )
    item_id = _item_ids(courses, attempt.id)[0]
    answer = attempts.autosave_answer(
        course.id,
        practice_set.id,
        attempt.id,
        item_id,
        response={"answer": "1"},
        expected_answer_revision=1,
        idempotency_token="answer-before-submit",
        expected_course_write_epoch=_epoch(courses, course.id),
        expected_practice_set_write_epoch=2,
    )

    submitted = attempts.submit_attempt(
        course.id, practice_set.id, attempt.id,
        expected_course_write_epoch=_epoch(courses, course.id), expected_practice_set_write_epoch=2,
    )
    replay = attempts.submit_attempt(
        course.id, practice_set.id, attempt.id,
        expected_course_write_epoch=_epoch(courses, course.id), expected_practice_set_write_epoch=2,
    )
    assert submitted.id == replay.id == attempt.id
    assert submitted.state == replay.state == "submitted"
    with pytest.raises(CourseConflictError, match="[Ss]ubmit|[Ff]rozen"):
        attempts.autosave_answer(
            course.id,
            practice_set.id,
            attempt.id,
            item_id,
            response={"answer": "rewrite"},
            expected_answer_revision=answer.revision,
            idempotency_token="answer-after-submit",
            expected_course_write_epoch=_epoch(courses, course.id),
            expected_practice_set_write_epoch=2,
        )

    abandoned = _start(
        attempts, courses, course.id, practice_set.id,
        practice_set_revision_id=practice.get_practice_set(course.id, practice_set.id).current_revision_id,
    )
    first_abandon = attempts.abandon_attempt(
        course.id, practice_set.id, abandoned.id,
        expected_course_write_epoch=_epoch(courses, course.id), expected_practice_set_write_epoch=2,
    )
    second_abandon = attempts.abandon_attempt(
        course.id, practice_set.id, abandoned.id,
        expected_course_write_epoch=_epoch(courses, course.id), expected_practice_set_write_epoch=2,
    )
    assert first_abandon.state == second_abandon.state == "abandoned"


def test_course_and_practice_archive_terminalize_active_attempts_and_restore_does_not_revive(
    tmp_path: Path,
) -> None:
    courses, practice, attempts = _services(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Geology")
    practice_set, _, _ = _ready_practice(courses, practice, course.id, question_count=1)
    attempt = _start(
        attempts, courses, course.id, practice_set.id,
        practice_set_revision_id=practice.get_practice_set(course.id, practice_set.id).current_revision_id,
    )
    archived_set = practice.archive_practice_set(
        course.id,
        practice_set.id,
        expected_revision=practice_set.revision + 1,
        expected_course_write_epoch=_epoch(courses, course.id),
    )
    assert attempts.get_attempt(course.id, practice_set.id, attempt.id).attempt.state == "archived"
    practice.restore_practice_set(
        course.id,
        practice_set.id,
        expected_revision=archived_set.revision,
        expected_course_write_epoch=_epoch(courses, course.id),
    )
    assert attempts.get_attempt(course.id, practice_set.id, attempt.id).attempt.state == "archived"

    next_attempt = _start(
        attempts, courses, course.id, practice_set.id,
        practice_set_revision_id=practice.get_practice_set(course.id, practice_set.id).current_revision_id,
    )
    archived_course = courses.archive_course(course.id, expected_revision=courses.get_course(course.id).revision)
    assert attempts.get_attempt(course.id, practice_set.id, next_attempt.id).attempt.state == "archived"
    courses.restore_course(course.id, expected_revision=archived_course.revision)
    assert attempts.get_attempt(course.id, practice_set.id, next_attempt.id).attempt.state == "archived"


def test_restart_and_two_repository_wrappers_preserve_one_attempt_and_no_lost_autosave(
    tmp_path: Path,
) -> None:
    path = tmp_path / "courses.db"
    courses, practice, attempts = _services(path, "u_alice")
    course = courses.create_course("Statistics")
    practice_set, revision, _ = _ready_practice(courses, practice, course.id, question_count=1)

    # Reinstantiation is the restart boundary; all identity and answer state is
    # read from the same migrated private database rather than process memory.
    restarted_courses, _, restarted_attempts = _services(path, "u_alice")

    def start(wrapper: CourseAssessmentService):
        return wrapper.start_or_resume_attempt(
            course.id,
            practice_set.id,
            revision.id,
            expected_course_write_epoch=_epoch(courses, course.id),
            expected_practice_set_write_epoch=2,
        ).attempt

    with ThreadPoolExecutor(max_workers=2) as pool:
        started = list(pool.map(start, (attempts, restarted_attempts)))
    assert len({attempt.id for attempt in started}) == 1
    attempt = started[0]
    item_id = _item_ids(courses, attempt.id)[0]
    assert restarted_attempts.get_attempt(course.id, practice_set.id, attempt.id).attempt.id == attempt.id

    def save(wrapper: CourseAssessmentService, value: str):
        return wrapper.autosave_answer(
            course.id,
            practice_set.id,
            attempt.id,
            item_id,
            response={"answer": value},
            expected_answer_revision=1,
            idempotency_token=f"concurrent-answer-{value}",
            expected_course_write_epoch=_epoch(courses, course.id),
            expected_practice_set_write_epoch=2,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, attempts, "first"), pool.submit(save, restarted_attempts, "second")]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(("saved", future.result()))
            except CourseConflictError:
                outcomes.append(("conflict", None))
    assert [kind for kind, _ in outcomes].count("saved") == 1
    assert [kind for kind, _ in outcomes].count("conflict") == 1
    assert _answer_row(restarted_courses, item_id)["revision"] == 2


def test_database_enforces_attempt_ownership_state_immutability_and_no_delete(tmp_path: Path) -> None:
    courses, practice, attempts = _services(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Ecology")
    practice_set, revision, _ = _ready_practice(courses, practice, course.id, question_count=1)
    attempt = _start(
        attempts, courses, course.id, practice_set.id,
        practice_set_revision_id=practice.get_practice_set(course.id, practice_set.id).current_revision_id,
    )
    item_id = _item_ids(courses, attempt.id)[0]
    with courses._connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE quiz_attempts SET owner_user_id = 'u_bob' WHERE id = ?", (attempt.id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE quiz_attempts SET course_id = 'crs_forged' WHERE id = ?", (attempt.id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE quiz_attempts SET practice_set_revision_id = ? WHERE id = ?", (revision.id, attempt.id))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE quiz_attempt_items SET question_id = 'qst_forged' WHERE id = ?", (item_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """UPDATE quiz_attempt_answers
                   SET response_json = '{"answer":"reset"}', revision = 1, answered_at = 2
                   WHERE attempt_item_id = ?""",
                (item_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """UPDATE quiz_attempt_answers
                   SET response_json = '"predates-start"',
                       revision = revision + 1, answered_at = 0
                   WHERE attempt_item_id = ?""",
                (item_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM quiz_attempt_answers WHERE attempt_item_id = ?", (item_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM quiz_attempt_items WHERE id = ?", (item_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM quiz_attempts WHERE id = ?", (attempt.id,))


def test_database_enforces_initial_state_timestamps_captured_epochs_and_terminal_fields(
    tmp_path: Path,
) -> None:
    courses, practice, attempts = _services(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Meteorology")
    practice_set, revision, _ = _ready_practice(courses, practice, course.id, question_count=1)
    attempt = _start(
        attempts, courses, course.id, practice_set.id,
        practice_set_revision_id=revision.id,
    )
    with courses._connect() as conn:
        stored = conn.execute("SELECT * FROM quiz_attempts WHERE id = ?", (attempt.id,)).fetchone()
        assert stored is not None
        assert stored["state"] == "in_progress"
        assert stored["course_write_epoch"] == course.write_epoch
        assert stored["practice_set_write_epoch"] == 2
        assert stored["started_at"] is not None
        assert stored["submitted_at"] is None
        assert stored["graded_at"] is None
        assert stored["archived_at"] is None
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE quiz_attempts SET submitted_at = 1 WHERE id = ?", (attempt.id,)
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE quiz_attempts SET state = 'graded', submitted_at = 1, graded_at = NULL WHERE id = ?",
                (attempt.id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE quiz_attempts SET state = 'abandoned' WHERE id = ?",
                (attempt.id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """UPDATE quiz_attempts
                   SET state = 'submitted', submitted_at = 0,
                       revision = revision + 1, updated_at = updated_at + 1
                   WHERE id = ?""",
                (attempt.id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE quiz_attempts SET score_json = '{}' WHERE id = ?",
                (attempt.id,),
            )


def test_database_freezes_answers_after_submit_or_parent_archive_and_receipts_cannot_cross_attempts(
    tmp_path: Path,
) -> None:
    courses, practice, attempts = _services(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Oceanography")
    first_set, first_revision, _ = _ready_practice(courses, practice, course.id, title="First", question_count=1)
    second_set, second_revision, _ = _ready_practice(courses, practice, course.id, title="Second", question_count=1)
    first = _start(
        attempts, courses, course.id, first_set.id, practice_set_revision_id=first_revision.id
    )
    second = _start(
        attempts, courses, course.id, second_set.id, practice_set_revision_id=second_revision.id
    )
    first_item = _item_ids(courses, first.id)[0]
    second_item = _item_ids(courses, second.id)[0]
    attempts.autosave_answer(
        course.id,
        first_set.id,
        first.id,
        first_item,
        response={"answer": "1"},
        expected_answer_revision=1,
        idempotency_token="first-answer-before-submit",
        expected_course_write_epoch=_epoch(courses, course.id),
        expected_practice_set_write_epoch=2,
    )
    attempts.submit_attempt(
        course.id, first_set.id, first.id,
        expected_course_write_epoch=_epoch(courses, course.id), expected_practice_set_write_epoch=2,
    )
    with courses._connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE quiz_attempt_answers SET response_json = '{\"answer\":\"rewrite\"}' WHERE attempt_item_id = ?",
                (first_item,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO quiz_attempt_autosave_receipts "
                "(attempt_id, idempotency_token, attempt_item_id, payload_sha256, "
                "response_json, answer_revision, answered_at, created_at) "
                "VALUES (?, 'cross-attempt-token', ?, ?, 'null', 1, 1, 1)",
                (first.id, second_item, "a" * 64),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO quiz_attempt_autosave_receipts
                   (attempt_id, idempotency_token, attempt_item_id, payload_sha256,
                    response_json, answer_revision, answered_at, created_at)
                   VALUES (?, 'forged-revision-token', ?, ?, 'null', 999, 1, 1)""",
                (second.id, second_item, "a" * 64),
            )

    archived = courses.archive_course(course.id, expected_revision=courses.get_course(course.id).revision)
    courses.restore_course(course.id, expected_revision=archived.revision)
    assert attempts.get_attempt(course.id, second_set.id, second.id).attempt.state == "archived"
    with courses._connect() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE quiz_attempt_answers SET response_json = '{\"answer\":\"rewrite\"}' WHERE attempt_item_id = ?",
            (second_item,),
        )


def test_migration_0002_replay_tamper_and_rollback_are_transactional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "courses.db"
    assert ensure_course_schema(path) == tuple(range(16))
    assert ensure_course_schema(path) == ()
    artifacts = runner.discover_migrations()
    assessment = artifacts[2]
    tampered = runner.MigrationArtifact.from_resource(
        assessment.filename, assessment.content + b"\n-- altered bytes\n"
    )
    monkeypatch.setattr(runner, "discover_migrations", lambda: (*artifacts[:2], tampered, *artifacts[3:]))
    with pytest.raises(CourseMigrationError, match="receipt mismatch"):
        ensure_course_schema(path)

    broken = runner.MigrationArtifact.from_resource(
        "0002_attempts.sql", b"CREATE TABLE should_rollback (id INTEGER);\nNOT VALID SQL;"
    )
    monkeypatch.setattr(runner, "discover_migrations", lambda: (*artifacts[:2], broken, *artifacts[3:]))
    fresh = tmp_path / "broken.db"
    with pytest.raises(CourseMigrationError, match="0002_attempts.sql failed"):
        ensure_course_schema(fresh)
    with sqlite3.connect(fresh) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'should_rollback'"
        ).fetchone()[0] == 0


def test_upgrade_from_exact_p4_02b_state_applies_generation_migrations_and_preserves_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "courses.db"
    artifacts = runner.discover_migrations()
    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts[:3])
    assert ensure_course_schema(path) == (0, 1, 2)

    courses, practice, _ = _services(path, "u_alice")
    course = courses.create_course("Biology")
    practice_set = practice.create_practice_set(
        course.id,
        title="Historical exact Practice",
        expected_course_write_epoch=course.write_epoch,
    )
    revision = practice.create_draft_revision(
        course.id,
        practice_set.id,
        expected_course_write_epoch=course.write_epoch,
    )
    with courses._connect() as conn:
        for ordinal in (1, 2):
            conn.execute(
                """INSERT INTO practice_questions
                   (id, practice_set_revision_id, question_type, prompt,
                    answer_contract_json, explanation, objective_ids_json,
                    citation_json, ordinal, created_at)
                   VALUES (?, ?, 'short_answer', ?, ?, '', '[]', '[]', ?, ?)""",
                (
                    f"qst_historical_{ordinal}",
                    revision.id,
                    f"Question {ordinal}?",
                    json.dumps({"kind": "exact", "answer": str(ordinal)}),
                    ordinal,
                    float(ordinal),
                ),
            )
    practice.ready_revision(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=course.write_epoch,
    )
    questions = practice.list_questions(course.id, practice_set.id, revision.id)
    with courses._connect() as conn:
        before = {
            table: conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            for table in (
                "courses",
                "practice_sets",
                "practice_set_revisions",
                "practice_questions",
            )
        }

    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts)
    assert ensure_course_schema(path) == tuple(range(3, 16))
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
        assert conn.execute("SELECT COUNT(*) FROM quiz_attempts").fetchone()[0] == 0
        assert tuple(
            row[0]
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ) == tuple(range(16))
    assert before == after
    assert practice_set.id and revision.id and len(questions) == 2
