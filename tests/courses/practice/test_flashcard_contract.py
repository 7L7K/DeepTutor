"""P4-06 adversarial persistence contracts for Course-owned Flashcards."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading

import pytest

from deeptutor.courses.flashcard_repository import CourseFlashcardRepository
from deeptutor.courses.flashcard_service import CourseFlashcardService
from deeptutor.courses.migrations import runner
from deeptutor.courses.migrations.runner import discover_migrations, ensure_course_schema
from deeptutor.courses.repository import (
    CourseConflictError,
    CourseNotFoundError,
    CourseRepository,
)


def _service(db_path: Path, owner: str) -> tuple[CourseRepository, CourseFlashcardService]:
    courses = CourseRepository(db_path, owner)
    return courses, CourseFlashcardService(CourseFlashcardRepository(courses))


def _ready_deck(
    service: CourseFlashcardService,
    courses: CourseRepository,
    course_id: str,
    *,
    title: str = "Terms",
) -> tuple[object, object]:
    course = courses.get_course(course_id)
    deck = service.create_deck(
        course_id, title=title, expected_course_write_epoch=course.write_epoch
    )
    card = service.add_card(
        course_id,
        deck.id,
        prompt="What is ATP?",
        answer="Energy currency",
        objective_ids=("cell_energy",),
        expected_deck_revision=deck.revision,
        expected_course_write_epoch=course.write_epoch,
    )
    deck = service.get_deck(course_id, deck.id, at=0).deck
    return (
        service.ready_deck(
            course_id,
            deck.id,
            expected_revision=deck.revision,
            expected_course_write_epoch=course.write_epoch,
        ),
        card,
    )


def test_two_same_title_owners_and_foreign_or_wrong_parent_ids_are_uniform_404(tmp_path: Path) -> None:
    alice_courses, alice = _service(tmp_path / "alice" / "courses.db", "u_alice")
    bob_courses, bob = _service(tmp_path / "bob" / "courses.db", "u_bob")
    alice_course = alice_courses.create_course("Biology")
    bob_course = bob_courses.create_course("Biology")
    deck, card = _ready_deck(alice, alice_courses, alice_course.id)

    assert [item.id for item in alice.list_decks(alice_course.id)] == [deck.id]
    assert bob.list_decks(bob_course.id) == []
    for operation in (
        lambda: alice.get_deck(bob_course.id, deck.id),
        lambda: alice.get_deck(alice_course.id, "dck_missing"),
        lambda: alice.due_cards(bob_course.id, deck.id),
        lambda: bob.get_deck(bob_course.id, deck.id),
        lambda: bob.record_review(
            bob_course.id,
            deck.id,
            card_id=card.id,
            rating="good",
            idempotency_key="foreign-review",
            expected_deck_revision=deck.revision,
            expected_card_revision=card.revision,
            expected_course_write_epoch=bob_course.write_epoch,
            now=1,
        ),
    ):
        with pytest.raises(CourseNotFoundError) as raised:
            operation()
        assert str(raised.value) == "Flashcard resource not found"


def test_deterministic_schedule_restart_idempotency_and_180_day_cap(tmp_path: Path) -> None:
    path = tmp_path / "courses.db"
    courses, service = _service(path, "u_alice")
    course = courses.create_course("Physics")
    deck, card = _ready_deck(service, courses, course.id)
    args = dict(
        card_id=card.id,
        rating="again",
        idempotency_key="first-review",
        expected_deck_revision=deck.revision,
        expected_card_revision=card.revision,
        expected_course_write_epoch=course.write_epoch,
        now=1_000,
    )
    first, schedule, summary = service.record_review(course.id, deck.id, **args)
    repeated, repeated_schedule, _ = service.record_review(course.id, deck.id, **args)
    assert repeated == first
    assert repeated_schedule == schedule
    assert first.interval_seconds == 60
    assert first.next_review_at == 1_060
    assert summary.due_cards == 0
    assert service.due_cards(course.id, deck.id, at=1_059).cards == []
    assert [item.id for item in service.due_cards(course.id, deck.id, at=1_060).cards] == [card.id]

    # Reopening the exact file must preserve history and deterministic schedule.
    _, restarted = _service(path, "u_alice")
    restored = restarted.get_deck(course.id, deck.id, at=1_060)
    assert restored.review_summary.review_count == 1
    assert restored.schedules[0].next_review_at == 1_060

    now = 1_060
    for ordinal in range(2, 20):
        review, _, _ = restarted.record_review(
            course.id,
            deck.id,
            card_id=card.id,
            rating="easy",
            idempotency_key=f"easy-{ordinal}",
            expected_deck_revision=deck.revision,
            expected_card_revision=card.revision,
            expected_course_write_epoch=course.write_epoch,
            now=now,
        )
        now = review.next_review_at
    assert review.interval_seconds == 180 * 24 * 60 * 60


def test_concurrent_same_key_review_creates_one_event_and_schedule_increment(
    tmp_path: Path,
) -> None:
    path = tmp_path / "courses.db"
    courses, service = _service(path, "u_alice")
    course = courses.create_course("Physics")
    deck, card = _ready_deck(service, courses, course.id)
    barrier = threading.Barrier(2)

    def review_once() -> str:
        _, thread_service = _service(path, "u_alice")
        barrier.wait(timeout=5)
        review, schedule, _ = thread_service.record_review(
            course.id,
            deck.id,
            card_id=card.id,
            rating="good",
            idempotency_key="concurrent-review",
            expected_deck_revision=deck.revision,
            expected_card_revision=card.revision,
            expected_course_write_epoch=course.write_epoch,
            now=1_000,
        )
        assert schedule.review_count == 1
        return review.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        review_ids = list(pool.map(lambda _index: review_once(), range(2)))

    assert len(set(review_ids)) == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM flashcard_reviews").fetchone()[0] == 1
        assert conn.execute(
            "SELECT review_count FROM flashcard_review_states WHERE card_id = ?",
            (card.id,),
        ).fetchone()[0] == 1


def test_review_replay_revalidates_course_parent_and_exact_request_binding(tmp_path: Path) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    first_course = courses.create_course("Biology")
    second_course = courses.create_course("Biology")
    deck, card = _ready_deck(service, courses, first_course.id)
    args = dict(
        card_id=card.id,
        rating="good",
        idempotency_key="same-key",
        expected_deck_revision=deck.revision,
        expected_card_revision=card.revision,
        expected_course_write_epoch=first_course.write_epoch,
        now=1_000,
    )
    service.record_review(first_course.id, deck.id, **args)
    with pytest.raises(CourseNotFoundError):
        service.record_review(
            second_course.id,
            deck.id,
            **{**args, "expected_course_write_epoch": second_course.write_epoch},
        )
    with pytest.raises(CourseConflictError, match="Idempotency"):
        service.record_review(first_course.id, deck.id, **{**args, "rating": "easy"})
    with pytest.raises(CourseConflictError, match="stale|Idempotency"):
        service.record_review(first_course.id, deck.id, **{**args, "expected_card_revision": 2})


def test_card_cas_archive_retains_history_and_blocks_new_reviews(tmp_path: Path) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Chemistry")
    deck, card = _ready_deck(service, courses, course.id)
    review, _, _ = service.record_review(
        course.id,
        deck.id,
        card_id=card.id,
        rating="hard",
        idempotency_key="history",
        expected_deck_revision=deck.revision,
        expected_card_revision=card.revision,
        expected_course_write_epoch=course.write_epoch,
        now=1_000,
    )
    deck = service.get_deck(course.id, deck.id, at=1_000).deck
    changed = service.update_card(
        course.id,
        deck.id,
        card.id,
        prompt="What is pH?",
        answer="Acidity measure",
        objective_ids=("acids",),
        expected_card_revision=card.revision,
        expected_deck_revision=deck.revision,
        expected_course_write_epoch=course.write_epoch,
    )
    deck = service.get_deck(course.id, deck.id, at=1_000).deck
    with pytest.raises(CourseConflictError, match="stale"):
        service.update_card(
            course.id, deck.id, card.id, prompt="stale", answer="stale",
            expected_card_revision=card.revision, expected_deck_revision=deck.revision,
            expected_course_write_epoch=course.write_epoch,
        )
    archived_card = service.archive_card(
        course.id, deck.id, changed.id, expected_card_revision=changed.revision,
        expected_deck_revision=deck.revision, expected_course_write_epoch=course.write_epoch,
    )
    deck = service.get_deck(course.id, deck.id, at=1_000).deck
    assert archived_card.state == "archived"
    history = service.get_deck(course.id, deck.id, at=1_000)
    assert history.cards[0].state == "archived"
    assert history.review_summary.review_count == 1
    with pytest.raises(CourseConflictError, match="Archived Flashcards"):
        service.record_review(
            course.id, deck.id, card_id=card.id, rating="again", idempotency_key="blocked-card",
            expected_deck_revision=deck.revision, expected_card_revision=archived_card.revision,
            expected_course_write_epoch=course.write_epoch, now=2_000,
        )

    # Deck archival preserves the record but returns an empty study queue.
    archived_deck = service.archive_deck(
        course.id, deck.id, expected_revision=deck.revision,
        expected_course_write_epoch=course.write_epoch,
    )
    archived_view = service.due_cards(course.id, deck.id, at=9_999)
    assert archived_view.cards == []
    assert archived_view.review_summary.due_cards == 0
    assert archived_view.review_summary.review_count == 1
    with pytest.raises(CourseConflictError, match="not ready"):
        service.record_review(
            course.id, deck.id, card_id=card.id, rating="again", idempotency_key="blocked-deck",
            expected_deck_revision=archived_deck.revision, expected_card_revision=archived_card.revision,
            expected_course_write_epoch=course.write_epoch, now=2_000,
        )
    assert review.id in {
        row[0]
        for row in sqlite3.connect(courses.db_path).execute("SELECT id FROM flashcard_reviews")
    }


def test_archived_draft_restores_as_draft_without_implicit_publication(tmp_path: Path) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("History")
    draft = service.create_deck(
        course.id, title="Draft terms", expected_course_write_epoch=course.write_epoch
    )
    draft = service.archive_deck(
        course.id,
        draft.id,
        expected_revision=draft.revision,
        expected_course_write_epoch=course.write_epoch,
    )
    restored = service.restore_deck(
        course.id,
        draft.id,
        expected_revision=draft.revision,
        expected_course_write_epoch=course.write_epoch,
    )
    assert restored.state == "draft"
    assert restored.ready_at is None


def test_general_study_archive_restore_preserves_ready_deck_review_history(
    tmp_path: Path,
) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    general = courses.get_or_create_general_study()
    deck, card = _ready_deck(service, courses, general.id, title="Conversation cards")
    _review, schedule, summary = service.record_review(
        general.id,
        deck.id,
        card_id=card.id,
        rating="good",
        idempotency_key="general-study-review",
        expected_deck_revision=deck.revision,
        expected_card_revision=card.revision,
        expected_course_write_epoch=general.write_epoch,
        now=1_000,
    )
    current = service.get_deck(general.id, deck.id, at=1_000).deck
    archived = service.archive_deck(
        general.id,
        deck.id,
        expected_revision=current.revision,
        expected_course_write_epoch=general.write_epoch,
    )
    restored = service.restore_deck(
        general.id,
        deck.id,
        expected_revision=archived.revision,
        expected_course_write_epoch=general.write_epoch,
    )
    restored_view = service.get_deck(general.id, deck.id, at=1_000)

    assert restored.state == "ready"
    assert restored_view.review_summary.review_count == summary.review_count == 1
    restored_schedule = next(
        item for item in restored_view.schedules if item.card_id == card.id
    )
    assert restored_schedule.next_review_at == schedule.next_review_at


def test_sqlite_rejects_forged_review_delete_and_non_owned_state(tmp_path: Path) -> None:
    courses, service = _service(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Geology")
    deck, card = _ready_deck(service, courses, course.id)
    with sqlite3.connect(courses.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO flashcard_review_states
                   (card_id, owner_user_id, course_id, deck_id, review_count, interval_seconds,
                    next_review_at, last_review_id, updated_at)
                   VALUES ('crd_forged', 'other', ?, ?, 0, 0, 0, NULL, 0)""",
                (course.id, deck.id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM flashcard_decks WHERE id = ?", (deck.id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM flashcards WHERE id = ?", (card.id,))


def test_upgrade_from_exact_p4_05_receipts_applies_flashcards_then_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "courses.db"
    artifacts = discover_migrations()
    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts[:5])
    assert ensure_course_schema(path) == (0, 1, 2, 3, 4)
    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts[:6])
    assert ensure_course_schema(path) == (5,)
    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts[:7])
    assert ensure_course_schema(path) == (6,)
    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts)
    assert ensure_course_schema(path) == tuple(range(7, 19))
    assert ensure_course_schema(path) == ()
    with sqlite3.connect(path) as conn:
        ledger = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        assert [row[0] for row in ledger] == list(range(19))
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'flashcard_reviews'").fetchone()[0] == 1
        triggers = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'flashcard_%'")}
    assert {"flashcard_reviews_require_owned_ready_card", "flashcard_reviews_no_delete", "flashcard_review_state_requires_matching_review", "flashcard_generation_complete_requires_ready_deck"} <= triggers
