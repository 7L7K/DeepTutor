"""Adversarial P4-02A contract checks for Course-owned Practice authoring."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from deeptutor.courses.migrations import runner
from deeptutor.courses.migrations.runner import CourseMigrationError, ensure_course_schema
from deeptutor.courses.practice_repository import CoursePracticeRepository
from deeptutor.courses.practice_service import CoursePracticeService
from deeptutor.courses.repository import (
    CourseConflictError,
    CourseNotFoundError,
    CourseRepository,
)


def _service(db_path: Path, owner: str) -> tuple[CourseRepository, CoursePracticeService]:
    courses = CourseRepository(db_path, owner)
    return courses, CoursePracticeService(CoursePracticeRepository(courses))


def _epoch(service: CoursePracticeService, course_id: str) -> int:
    return service.repository.course_repository.get_course(course_id).write_epoch


def _ready_source(courses: CourseRepository, course_id: str):
    source = courses.create_source(
        course_id,
        kind="notes",
        display_name="source.pdf",
        manifest=[],
        content_sha256="a" * 64,
    )
    return courses.transition_source(
        course_id,
        source.id,
        operation_id=source.operation_id or "",
        expected_source_revision=source.revision,
        expected_course_revision=courses.get_course(course_id).revision,
        expected_write_epoch=courses.get_course(course_id).write_epoch,
        state="ready",
    )


def _draft_with_question(
    service: CoursePracticeService,
    course_id: str,
    *,
    title: str = "Practice",
    source_ids: tuple[str, ...] = (),
):
    expected_epoch = _epoch(service, course_id)
    practice_set = service.create_practice_set(
        course_id,
        title=title,
        expected_course_write_epoch=expected_epoch,
    )
    revision = service.create_draft_revision(
        course_id,
        practice_set.id,
        source_ids=source_ids,
        objective_ids=("obj_cells",),
        expected_course_write_epoch=expected_epoch,
    )
    question = service.add_question(
        course_id,
        practice_set.id,
        revision.id,
        question_type="short_answer",
        prompt="What makes ATP?",
        answer_contract={"kind": "exact", "answer": "mitochondria"},
        explanation="Cellular respiration produces ATP.",
        objective_ids=("obj_cells",),
        citations=(),
        expected_course_write_epoch=expected_epoch,
    )
    return practice_set, revision, question


def test_same_title_courses_and_two_owners_never_share_practice_history(tmp_path: Path) -> None:
    alice_courses, alice = _service(tmp_path / "alice" / "courses.db", "u_alice")
    bob_courses, bob = _service(tmp_path / "bob" / "courses.db", "u_bob")
    alice_course = alice_courses.create_course("Calculus")
    bob_course = bob_courses.create_course("Calculus")

    alice_set, alice_revision, _ = _draft_with_question(
        alice, alice_course.id, title="Week 1"
    )
    bob_set, bob_revision, _ = _draft_with_question(
        bob, bob_course.id, title="Week 1"
    )
    alice.ready_revision(
        alice_course.id,
        alice_set.id,
        alice_revision.id,
        expected_course_write_epoch=alice_course.write_epoch,
    )
    bob.ready_revision(
        bob_course.id,
        bob_set.id,
        bob_revision.id,
        expected_course_write_epoch=bob_course.write_epoch,
    )

    assert alice_set.id != bob_set.id
    assert alice_revision.id != bob_revision.id
    assert [item.id for item in alice.list_practice_sets(alice_course.id)] == [alice_set.id]
    assert [item.id for item in bob.list_practice_sets(bob_course.id)] == [bob_set.id]
    with pytest.raises(CourseNotFoundError):
        bob.get_practice_set(bob_course.id, alice_set.id)
    with pytest.raises(CourseNotFoundError):
        bob.get_revision(bob_course.id, bob_set.id, alice_revision.id)


def test_missing_foreign_and_wrong_parent_child_ids_are_indistinguishable(tmp_path: Path) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    first_course = courses.create_course("Biology")
    second_course = courses.create_course("Biology")
    practice_set, revision, _ = _draft_with_question(service, first_course.id)

    for operation in (
        lambda: service.get_practice_set(first_course.id, "prc_missing"),
        lambda: service.get_practice_set(second_course.id, practice_set.id),
        lambda: service.get_revision(first_course.id, practice_set.id, "prv_missing"),
        lambda: service.get_revision(second_course.id, practice_set.id, revision.id),
        lambda: service.list_questions(first_course.id, practice_set.id, "prv_missing"),
        lambda: service.list_questions(second_course.id, practice_set.id, revision.id),
    ):
        with pytest.raises(CourseNotFoundError) as raised:
            operation()
        assert str(raised.value) == "Practice resource not found"


def test_ready_revision_and_its_questions_are_immutable_and_successor_keeps_history(
    tmp_path: Path,
) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Chemistry")
    practice_set, revision, question = _draft_with_question(service, course.id)
    ready = service.ready_revision(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=course.write_epoch,
    )

    with pytest.raises(CourseConflictError, match="(?i)ready"):
        service.add_question(
            course.id,
            practice_set.id,
            revision.id,
            question_type="short_answer",
            prompt="A forbidden rewrite",
            answer_contract={"kind": "exact", "answer": "no"},
            expected_course_write_epoch=course.write_epoch,
        )
    with pytest.raises(CourseConflictError, match="(?i)ready"):
        service.ready_revision(
            course.id,
            practice_set.id,
            revision.id,
            expected_course_write_epoch=course.write_epoch,
        )

    successor = service.create_successor_revision(
        course.id,
        practice_set.id,
        expected_course_write_epoch=course.write_epoch,
    )
    successor_question = service.add_question(
        course.id,
        practice_set.id,
        successor.id,
        question_type="short_answer",
        prompt="What is the pH of water?",
        answer_contract={"kind": "exact", "answer": "7"},
        expected_course_write_epoch=course.write_epoch,
    )
    successor_ready = service.ready_revision(
        course.id,
        practice_set.id,
        successor.id,
        expected_course_write_epoch=course.write_epoch,
    )
    after = service.get_practice_set(course.id, practice_set.id)

    assert ready.state == "ready"
    assert service.get_revision(course.id, practice_set.id, revision.id).state == "superseded"
    assert successor_ready.state == "ready"
    assert successor.revision_number == revision.revision_number + 1
    assert after.current_revision_id == successor.id
    historical_questions = service.list_questions(course.id, practice_set.id, revision.id)
    successor_questions = service.list_questions(course.id, practice_set.id, successor.id)
    assert [(item.id, item.prompt) for item in historical_questions] == [(question.id, "What makes ATP?")]
    assert [(item.id, item.prompt) for item in successor_questions] == [(successor_question.id, "What is the pH of water?")]


def test_ready_transition_is_atomic_when_the_draft_is_not_publishable(tmp_path: Path) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Astronomy")
    practice_set = service.create_practice_set(
        course.id,
        title="Empty draft",
        expected_course_write_epoch=course.write_epoch,
    )
    revision = service.create_draft_revision(
        course.id,
        practice_set.id,
        expected_course_write_epoch=course.write_epoch,
    )

    with pytest.raises((CourseConflictError, ValueError), match="question|empty|ready"):
        service.ready_revision(
            course.id,
            practice_set.id,
            revision.id,
            expected_course_write_epoch=course.write_epoch,
        )

    assert service.get_revision(course.id, practice_set.id, revision.id).state == "draft"
    assert service.get_practice_set(course.id, practice_set.id).current_revision_id is None


def test_database_rejects_question_insert_after_revision_is_ready(tmp_path: Path) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Geology")
    practice_set, revision, _ = _draft_with_question(service, course.id)
    service.ready_revision(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=course.write_epoch,
    )

    with sqlite3.connect(courses.db_path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO practice_questions
               (id, practice_set_revision_id, question_type, prompt,
                answer_contract_json, explanation, objective_ids_json, citation_json,
                ordinal, created_at)
               VALUES ('qst_late', ?, 'short_answer', 'late',
                       '{"kind":"exact","answer":"no"}', '', '[]', '[]', 2, 1)""",
            (revision.id,),
        )


def test_database_rejects_new_revision_or_question_below_archived_set(
    tmp_path: Path,
) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Geology")
    practice_set, revision, _ = _draft_with_question(service, course.id)
    service.archive_practice_set(
        course.id,
        practice_set.id,
        expected_revision=practice_set.revision,
        expected_course_write_epoch=course.write_epoch,
    )

    with sqlite3.connect(courses.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO practice_set_revisions
                   (id, practice_set_id, revision_number, state, source_snapshot_json,
                    objective_ids_json, generation_receipt_json, created_at, ready_at)
                   VALUES ('prv_late', ?, 2, 'draft', '[]', '[]', NULL, 2, NULL)""",
                (practice_set.id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO practice_questions
                   (id, practice_set_revision_id, question_type, prompt,
                    answer_contract_json, explanation, objective_ids_json,
                    citation_json, ordinal, created_at)
                   VALUES ('qst_late', ?, 'short_answer', 'late',
                           '{"kind":"exact","answer":"no"}', '', '[]', '[]', 2, 2)""",
                (revision.id,),
            )


def test_database_requires_draft_then_nonempty_publish_and_protects_current_pointer(
    tmp_path: Path,
) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Geology")
    practice_set, revision, _ = _draft_with_question(service, course.id)
    service.ready_revision(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=course.write_epoch,
    )

    with sqlite3.connect(courses.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO practice_set_revisions
                   (id, practice_set_id, revision_number, state, source_snapshot_json,
                    objective_ids_json, generation_receipt_json, created_at, ready_at)
                   VALUES ('prv_direct_ready', ?, 2, 'ready', '[]', '[]', NULL, 2, 2)""",
                (practice_set.id,),
            )
        conn.execute(
            """INSERT INTO practice_set_revisions
               (id, practice_set_id, revision_number, state, source_snapshot_json,
                objective_ids_json, generation_receipt_json, created_at, ready_at)
               VALUES ('prv_empty', ?, 2, 'draft', '[]', '[]', NULL, 2, NULL)""",
            (practice_set.id,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """UPDATE practice_set_revisions
                   SET state = 'ready', ready_at = 2
                   WHERE id = 'prv_empty'"""
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE practice_sets SET current_revision_id = NULL WHERE id = ?",
                (practice_set.id,),
            )


def test_database_rejects_two_ready_revisions_for_one_practice_set(
    tmp_path: Path,
) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Geology")
    practice_set, revision, _ = _draft_with_question(service, course.id)
    service.ready_revision(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=course.write_epoch,
    )

    with sqlite3.connect(courses.db_path) as conn:
        conn.execute(
            """INSERT INTO practice_set_revisions
               (id, practice_set_id, revision_number, state, source_snapshot_json,
                objective_ids_json, generation_receipt_json, created_at, ready_at)
               VALUES ('prv_two', ?, 2, 'draft', '[]', '[]', NULL, 2, NULL)""",
            (practice_set.id,),
        )
        conn.execute(
            """INSERT INTO practice_questions
               (id, practice_set_revision_id, question_type, prompt,
                answer_contract_json, explanation, objective_ids_json,
                citation_json, ordinal, created_at)
               VALUES ('qst_two', 'prv_two', 'short_answer', 'second',
                       '{"kind":"exact","answer":"yes"}', '', '[]', '[]', 1, 2)"""
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """UPDATE practice_set_revisions
                   SET state = 'ready', ready_at = 2
                   WHERE id = 'prv_two'"""
            )


def test_course_archive_restore_does_not_reauthorize_stale_draft_publish(
    tmp_path: Path,
) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Economics")
    practice_set, revision, _ = _draft_with_question(service, course.id)
    stale_epoch = course.write_epoch
    archived = courses.archive_course(course.id, expected_revision=course.revision)
    courses.restore_course(course.id, expected_revision=archived.revision)

    with pytest.raises(CourseConflictError, match="epoch"):
        service.ready_revision(
            course.id,
            practice_set.id,
            revision.id,
            expected_course_write_epoch=stale_epoch,
        )
    assert service.get_revision(course.id, practice_set.id, revision.id).state == "draft"


def test_revision_and_question_uniqueness_are_enforced_by_the_database(tmp_path: Path) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Physics")
    practice_set, revision, _ = _draft_with_question(service, course.id)

    with sqlite3.connect(courses.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO practice_set_revisions
                   (id, practice_set_id, revision_number, state, source_snapshot_json,
                    objective_ids_json, generation_receipt_json, created_at, ready_at)
                   VALUES ('prv_duplicate', ?, ?, 'draft', '[]', '[]', NULL, 1, NULL)""",
                (practice_set.id, revision.revision_number),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO practice_questions
                   (id, practice_set_revision_id, question_type, prompt,
                    answer_contract_json, explanation, objective_ids_json, citation_json,
                    ordinal, created_at)
                   VALUES ('qst_duplicate', ?, 'short_answer', 'duplicate', '{}', '', '[]', '[]', 1, 1)""",
                (revision.id,),
            )


@pytest.mark.parametrize(
    "field, value",
    [
        ("answer_contract", "not-an-object"),
        ("answer_contract", {"unexpected": "key"}),
        ("objective_ids", "not-a-list"),
        ("objective_ids", ("",)),
        ("citations", ({"source_id": "src_forged"},)),
        (
            "citations",
            (
                {
                    "source_id": "src_one",
                    "source_revision": 1,
                    "content_sha256": "a" * 64,
                    "extra": 1,
                },
            ),
        ),
    ],
)
def test_question_json_is_typed_bounded_and_rejects_untrusted_extra_or_provenance(
    tmp_path: Path, field: str, value: object
) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Writing")
    practice_set = service.create_practice_set(
        course.id,
        title="Week one",
        expected_course_write_epoch=course.write_epoch,
    )
    revision = service.create_draft_revision(
        course.id,
        practice_set.id,
        expected_course_write_epoch=course.write_epoch,
    )
    args = {
        "question_type": "short_answer",
        "prompt": "Explain a thesis.",
        "answer_contract": {"kind": "exact", "answer": "claim"},
        "objective_ids": (),
        "citations": (),
    }
    args[field] = value

    with pytest.raises(ValueError):
        service.add_question(
            course.id,
            practice_set.id,
            revision.id,
            expected_course_write_epoch=course.write_epoch,
            **args,
        )


def test_source_receipt_is_server_resolved_and_client_forgery_cannot_grant_authority(
    tmp_path: Path,
) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("History")
    ready_source = _ready_source(courses, course.id)
    practice_set = service.create_practice_set(
        course.id,
        title="Primary sources",
        expected_course_write_epoch=course.write_epoch,
    )

    revision = service.create_draft_revision(
        course.id,
        practice_set.id,
        source_ids=(ready_source.id,),
        expected_course_write_epoch=course.write_epoch,
    )
    assert [receipt.model_dump() for receipt in revision.source_snapshot] == [
        {
            "source_id": ready_source.id,
            "source_revision": ready_source.revision,
            "content_sha256": ready_source.content_sha256,
        }
    ]
    second_set = service.create_practice_set(
        course.id,
        title="Forged receipt",
        expected_course_write_epoch=course.write_epoch,
    )
    with pytest.raises((CourseNotFoundError, ValueError)):
        service.create_draft_revision(
            course.id,
            second_set.id,
            source_ids=("src_forged",),
            expected_course_write_epoch=course.write_epoch,
        )
    with pytest.raises(ValueError):
        service.add_question(
            course.id,
            practice_set.id,
            revision.id,
            question_type="short_answer",
            prompt="Can a title authorize a citation?",
            answer_contract={"kind": "exact", "answer": "no"},
            citations=(
                {
                    "source_id": ready_source.id,
                    "source_revision": ready_source.revision,
                    "content_sha256": ready_source.content_sha256,
                    "title": "forged title",
                    "kb_name": "foreign authority",
                },
            ),
            expected_course_write_epoch=course.write_epoch,
        )


def test_generated_authority_is_unavailable_until_the_server_operation_slice(
    tmp_path: Path,
) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Literature")
    with pytest.raises(ValueError, match="P4-02A"):
        service.create_practice_set(
            course.id,
            title="Forged generated set",
            mode="generated",
            expected_course_write_epoch=course.write_epoch,
        )

    practice_set = service.create_practice_set(
        course.id,
        title="Manual set",
        expected_course_write_epoch=course.write_epoch,
    )
    with pytest.raises(ValueError, match="P4-05"):
        service.create_draft_revision(
            course.id,
            practice_set.id,
            generation_receipt={"provider": "client-asserted"},
            expected_course_write_epoch=course.write_epoch,
        )


@pytest.mark.parametrize(
    "locator",
    [
        {"offset": float("nan")},
        {"offset": float("inf")},
        {f"k{index}": "x" * 500 for index in range(16)},
    ],
)
def test_citation_json_is_finite_and_total_payload_is_bounded(
    tmp_path: Path,
    locator: dict[str, object],
) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Law")
    source = _ready_source(courses, course.id)
    practice_set = service.create_practice_set(
        course.id,
        title="Cases",
        expected_course_write_epoch=course.write_epoch,
    )
    revision = service.create_draft_revision(
        course.id,
        practice_set.id,
        source_ids=(source.id,),
        expected_course_write_epoch=course.write_epoch,
    )
    citation = {
        "source_id": source.id,
        "source_revision": source.revision,
        "content_sha256": source.content_sha256,
        "locator": locator,
    }
    citations = (citation,) if "offset" in locator else (citation, citation, citation)
    with pytest.raises(ValueError):
        service.add_question(
            course.id,
            practice_set.id,
            revision.id,
            question_type="short_answer",
            prompt="What is the holding?",
            answer_contract={"kind": "exact", "answer": "bounded"},
            citations=citations,
            expected_course_write_epoch=course.write_epoch,
        )


def test_archive_restore_and_course_epoch_fence_preserve_history(tmp_path: Path) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Statistics")
    practice_set, revision, question = _draft_with_question(service, course.id)
    service.ready_revision(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=course.write_epoch,
    )
    ready_set = service.get_practice_set(course.id, practice_set.id)
    archived_set = service.archive_practice_set(
        course.id,
        practice_set.id,
        expected_revision=ready_set.revision,
        expected_course_write_epoch=course.write_epoch,
    )
    with pytest.raises(CourseConflictError, match="(?i)archived"):
        service.create_successor_revision(
            course.id,
            practice_set.id,
            expected_course_write_epoch=course.write_epoch,
        )
    restored_set = service.restore_practice_set(
        course.id,
        practice_set.id,
        expected_revision=archived_set.revision,
        expected_course_write_epoch=course.write_epoch,
    )
    assert restored_set.state == "draft"

    stale_epoch = course.write_epoch
    archived_course = courses.archive_course(course.id, expected_revision=course.revision)
    with pytest.raises(CourseConflictError, match="(?i)archived|epoch"):
        service.create_successor_revision(
            course.id, practice_set.id, expected_course_write_epoch=stale_epoch
        )
    restored_course = courses.restore_course(course.id, expected_revision=archived_course.revision)
    reopened = CoursePracticeService(
        CoursePracticeRepository(CourseRepository(courses.db_path, "u_alice"))
    )
    assert [
        item.id
        for item in reopened.list_questions(course.id, practice_set.id, revision.id)
    ] == [question.id]
    assert restored_course.write_epoch == stale_epoch + 2


def test_restart_replays_0001_once_and_tampering_its_exact_bytes_blocks_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "courses.db"
    CourseRepository(db_path, "u_alice")

    with sqlite3.connect(db_path) as conn:
        first_receipts = conn.execute(
            "SELECT version, name, checksum_sha256 FROM schema_migrations WHERE version = 1"
        ).fetchall()
    CourseRepository(db_path, "u_alice")
    with sqlite3.connect(db_path) as conn:
        second_receipts = conn.execute(
            "SELECT version, name, checksum_sha256 FROM schema_migrations WHERE version = 1"
        ).fetchall()
    assert first_receipts == second_receipts and len(second_receipts) == 1
    artifacts = runner.discover_migrations()
    altered = replace(
        artifacts[1],
        content=artifacts[1].content + b"\n-- byte rewrite\n",
    )
    altered = replace(
        altered,
        checksum_sha256=runner.hashlib.sha256(altered.content).hexdigest(),
    )
    monkeypatch.setattr(runner, "discover_migrations", lambda: (artifacts[0], altered, *artifacts[2:]))
    with pytest.raises(CourseMigrationError, match="receipt mismatch"):
        ensure_course_schema(db_path)


def test_0001_failure_rolls_back_its_tables_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = runner.discover_migrations()
    broken = replace(
        artifacts[1],
        content=b"CREATE TABLE practice_should_rollback (id INTEGER);\nNOT VALID SQL;",
    )
    broken = replace(
        broken,
        checksum_sha256=runner.hashlib.sha256(broken.content).hexdigest(),
    )
    monkeypatch.setattr(runner, "discover_migrations", lambda: (artifacts[0], broken, *artifacts[2:]))
    path = tmp_path / "courses.db"

    with pytest.raises(CourseMigrationError, match="0001_practice_authoring.sql failed"):
        ensure_course_schema(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 1"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'practice_should_rollback'"
        ).fetchone()[0] == 0
