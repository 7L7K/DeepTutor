"""P4-07 durable grounded Flashcard generation contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading

import pytest

from deeptutor.courses.flashcard_generation_models import (
    FlashcardCitation,
    FlashcardSourceReceipt,
    GeneratedFlashcard,
    GeneratedFlashcardOutput,
)
from deeptutor.courses.flashcard_generation_repository import (
    CourseFlashcardGenerationRepository,
)
from deeptutor.courses.repository import CourseConflictError, CourseNotFoundError, CourseRepository


def _setup(path: Path, owner: str = "u_alice"):
    courses = CourseRepository(path, owner)
    course = courses.create_course("Biology")
    source = courses.create_source(
        course.id, kind="notes", display_name="notes.txt", manifest=[], content_sha256="a" * 64
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
    return courses, course, source, CourseFlashcardGenerationRepository(courses)


def _output(source) -> GeneratedFlashcardOutput:
    receipt = FlashcardSourceReceipt(
        source_id=source.id, source_revision=source.revision, content_sha256=source.content_sha256
    )
    return GeneratedFlashcardOutput(
        provider_label="deterministic-local",
        cards=[
            GeneratedFlashcard(
                prompt="What is ATP?",
                answer="Energy",
                citations=[FlashcardCitation(**receipt.model_dump())],
            )
        ],
    )


def _complete(repo, course, source, request):
    operation, claimed = repo.claim_operation(course.id, request.operation.id)
    assert claimed
    return repo.complete_operation(
        course.id,
        operation.id,
        _output(source),
        account_active=True,
        material_receipts=[
            FlashcardSourceReceipt(
                source_id=source.id,
                source_revision=source.revision,
                content_sha256=source.content_sha256,
            )
        ],
    )


def test_idempotency_atomic_publication_and_successor_lineage(tmp_path: Path) -> None:
    courses, course, source, repo = _setup(tmp_path / "courses.db")
    request = repo.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key="same-request",
        expected_course_write_epoch=course.write_epoch,
    )
    same = repo.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key="same-request",
        expected_course_write_epoch=course.write_epoch,
    )
    assert (same.deck_id, same.operation.id) == (request.deck_id, request.operation.id)
    unavailable_replay = repo.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key="same-request",
        expected_course_write_epoch=course.write_epoch,
        provider_available=False,
    )
    assert (unavailable_replay.deck_id, unavailable_replay.operation.id) == (
        request.deck_id,
        request.operation.id,
    )
    with pytest.raises(CourseConflictError, match="provider is unavailable"):
        repo.create_generated_deck(
            course.id,
            title="Other terms",
            source_ids=[source.id],
            idempotency_key="new-unavailable-request",
            expected_course_write_epoch=course.write_epoch,
            provider_available=False,
        )
    # A same-key replay after the exact source receipt changes is not silently
    # treated as the old request.
    with courses._write_lock, courses._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE course_sources SET revision=revision+1 WHERE id=?", (source.id,))
    with pytest.raises(CourseConflictError, match="Idempotency"):
        repo.create_generated_deck(
            course.id,
            title="Terms",
            source_ids=[source.id],
            idempotency_key="same-request",
            expected_course_write_epoch=course.write_epoch,
        )
    # Restore the exact frozen receipt only for the happy-path publication.
    with courses._write_lock, courses._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE course_sources SET revision=revision-1 WHERE id=?", (source.id,))
    with sqlite3.connect(tmp_path / "courses.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM flashcards").fetchone()[0] == 0
    assert _complete(repo, course, source, request).state == "completed"
    successor = repo.create_generated_deck(
        course.id,
        title="Updated terms",
        source_ids=[source.id],
        idempotency_key="new-request",
        expected_course_write_epoch=course.write_epoch,
        supersedes_deck_id=request.deck_id,
    )
    assert successor.deck_id != request.deck_id
    assert successor.operation.supersedes_deck_id == request.deck_id
    with sqlite3.connect(tmp_path / "courses.db") as conn:
        assert (
            conn.execute(
                "SELECT supersedes_deck_id FROM flashcard_decks WHERE id=?", (successor.deck_id,)
            ).fetchone()[0]
            == request.deck_id
        )


def test_foreign_ids_and_changed_sources_are_safe(tmp_path: Path) -> None:
    courses, course, source, repo = _setup(tmp_path / "alice.db")
    _other_courses, other_course, _other_source, other = _setup(tmp_path / "bob.db", "u_bob")
    request = repo.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key="source-change",
        expected_course_write_epoch=course.write_epoch,
    )
    with pytest.raises(CourseNotFoundError):
        other.get_operation(other_course.id, request.operation.id)
    # Replacing a source revision fences the final publication and leaves no card.
    operation, _ = repo.claim_operation(course.id, request.operation.id)
    with courses._write_lock, courses._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE course_sources SET revision=revision+1 WHERE id=?", (source.id,))
    receipt = FlashcardSourceReceipt(
        source_id=source.id, source_revision=source.revision, content_sha256=source.content_sha256
    )
    with pytest.raises(CourseConflictError, match="sources"):
        repo.complete_operation(
            course.id,
            operation.id,
            _output(source),
            account_active=True,
            material_receipts=[receipt],
        )
    assert repo.fail_operation(course.id, operation.id, "source_changed").state == "failed"


def test_invalid_citation_and_restart_orphan_never_publish(tmp_path: Path) -> None:
    _courses, course, source, repo = _setup(tmp_path / "courses.db")
    request = repo.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key="bad-output",
        expected_course_write_epoch=course.write_epoch,
    )
    operation, _ = repo.claim_operation(course.id, request.operation.id)
    bad = GeneratedFlashcardOutput(
        provider_label="deterministic-local",
        cards=[
            GeneratedFlashcard(
                prompt="p",
                answer="a",
                citations=[
                    FlashcardCitation(
                        source_id="src_" + "b" * 32, source_revision=1, content_sha256="b" * 64
                    )
                ],
            )
        ],
    )
    receipt = FlashcardSourceReceipt(
        source_id=source.id, source_revision=source.revision, content_sha256=source.content_sha256
    )
    with pytest.raises(ValueError, match="citation"):
        repo.complete_operation(
            course.id, operation.id, bad, account_active=True, material_receipts=[receipt]
        )
    assert repo.fail_operation(course.id, operation.id, "invalid_output").state == "failed"
    with sqlite3.connect(tmp_path / "courses.db") as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE flashcard_generation_operations SET updated_at=updated_at+1 WHERE id=?",
                (operation.id,),
            )
    orphan = repo.create_generated_deck(
        course.id,
        title="Second",
        source_ids=[source.id],
        idempotency_key="orphan",
        expected_course_write_epoch=course.write_epoch,
    )
    assert repo.reconcile_orphaned_operations(course.id, live_operation_ids=set()) == 1
    assert repo.get_operation(course.id, orphan.operation.id).error_code == "interrupted"


def test_concurrent_same_key_creates_one_operation(tmp_path: Path) -> None:
    path = tmp_path / "courses.db"
    _courses, course, source, _repo = _setup(path)
    barrier = threading.Barrier(2)

    def create() -> str:
        repo = CourseFlashcardGenerationRepository(CourseRepository(path, "u_alice"))
        barrier.wait(timeout=5)
        return repo.create_generated_deck(
            course.id,
            title="Terms",
            source_ids=[source.id],
            idempotency_key="same-key",
            expected_course_write_epoch=course.write_epoch,
        ).operation.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(lambda _: create(), range(2)))) == 1
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM flashcard_generation_operations").fetchone()[0] == 1
        )


def test_direct_sql_cannot_publish_or_mutate_terminal_generated_authority(
    tmp_path: Path,
) -> None:
    path = tmp_path / "courses.db"
    _courses, course, source, repo = _setup(path)
    request = repo.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key="sql-fence",
        expected_course_write_epoch=course.write_epoch,
    )
    with sqlite3.connect(path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE flashcard_decks SET state='ready', ready_at=1 WHERE id=?",
                (request.deck_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO flashcards
                   (id,deck_id,prompt,answer,objective_ids_json,citation_json,ordinal,
                    revision,state,created_at,updated_at,archived_at)
                   VALUES ('crd_forged',?,'p','a','[]','[]',1,1,'active',1,1,NULL)""",
                (request.deck_id,),
            )
    _complete(repo, course, source, request)
    with sqlite3.connect(path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE flashcard_generation_operations SET error_code='provider_failed' WHERE id=?",
                (request.operation.id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE flashcard_generation_operations SET updated_at=updated_at+1 WHERE id=?",
                (request.operation.id,),
            )
