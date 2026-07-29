"""Course-rooted persistence for manual Flashcard decks and review history."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Iterable
from uuid import uuid4

from .flashcard_models import (
    Flashcard,
    FlashcardDeck,
    FlashcardDeckView,
    FlashcardRating,
    FlashcardReview,
    FlashcardReviewSummary,
    FlashcardSchedule,
)
from .repository import CourseConflictError, CourseNotFoundError, CourseRepository

_MAX_OBJECTIVES = 64
_MAX_JSON_BYTES = 16_384
_MAX_CARDS = 500
_MAX_INTERVAL_SECONDS = 180 * 24 * 60 * 60


def _deck_id() -> str:
    return f"dck_{uuid4().hex}"


def _card_id() -> str:
    return f"crd_{uuid4().hex}"


def _review_id() -> str:
    return f"rvw_{uuid4().hex}"


class CourseFlashcardRepository:
    """Persist Flashcards through the authenticated Course aggregate.

    Cards and review state live in the same private ``courses.db`` and reuse the
    parent's resolved-path lock. The public methods deliberately take no owner,
    database path, provider, or client-controlled clock authority.
    """

    def __init__(self, course_repository: CourseRepository) -> None:
        self.course_repository = course_repository

    @property
    def owner_user_id(self) -> str:
        return self.course_repository.owner_user_id

    @staticmethod
    def _not_found() -> CourseNotFoundError:
        return CourseNotFoundError("Flashcard resource not found")

    @staticmethod
    def _clean_text(value: str, field: str, *, maximum: int, required: bool = True) -> str:
        cleaned = " ".join(str(value or "").split())
        if required and not cleaned:
            raise ValueError(f"{field} is required")
        if len(cleaned) > maximum:
            raise ValueError(f"{field} must be {maximum} characters or fewer")
        return cleaned

    @classmethod
    def _objective_ids(cls, objective_ids: Iterable[str]) -> list[str]:
        if isinstance(objective_ids, (str, bytes)):
            raise ValueError("objective_ids must be a list of objective IDs")
        try:
            values = list(objective_ids)
        except TypeError as exc:
            raise ValueError("objective_ids must be a list of objective IDs") from exc
        if len(values) > _MAX_OBJECTIVES:
            raise ValueError("too many objective IDs")
        cleaned = [cls._clean_text(value, "Objective ID", maximum=160) for value in values]
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("objective_ids must not contain duplicates")
        return cleaned

    @staticmethod
    def _json(value: Any, *, field: str) -> str:
        try:
            encoded = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be strict JSON") from exc
        if len(encoded.encode("utf-8")) > _MAX_JSON_BYTES:
            raise ValueError(f"{field} is too large")
        return encoded

    def _course_for_write(
        self, conn: sqlite3.Connection, course_id: str, expected_course_write_epoch: int
    ) -> None:
        row = conn.execute(
            "SELECT state, write_epoch FROM courses WHERE id = ? AND owner_user_id = ?",
            (course_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        if str(row["state"]) != "active":
            raise CourseConflictError("Archived courses cannot change Flashcards")
        if int(row["write_epoch"]) != expected_course_write_epoch:
            raise CourseConflictError("Course write epoch is stale")

    @staticmethod
    def _deck_from_row(row: sqlite3.Row) -> FlashcardDeck:
        payload = dict(row)
        payload["source_snapshot"] = json.loads(payload.pop("source_snapshot_json") or "[]")
        receipt = payload.pop("generation_receipt_json")
        payload["generation_receipt"] = json.loads(receipt) if receipt else None
        return FlashcardDeck.model_validate(payload)

    @staticmethod
    def _card_from_row(row: sqlite3.Row) -> Flashcard:
        payload = dict(row)
        payload["objective_ids"] = json.loads(payload.pop("objective_ids_json") or "[]")
        payload["citations"] = json.loads(payload.pop("citation_json") or "[]")
        return Flashcard.model_validate(payload)

    @staticmethod
    def _review_from_row(row: sqlite3.Row) -> FlashcardReview:
        payload = dict(row)
        payload["was_due"] = bool(payload["was_due"])
        return FlashcardReview.model_validate(payload)

    @staticmethod
    def _schedule_from_row(row: sqlite3.Row) -> FlashcardSchedule:
        return FlashcardSchedule.model_validate(dict(row))

    def _owned_deck_row(self, conn: sqlite3.Connection, course_id: str, deck_id: str) -> sqlite3.Row:
        row = conn.execute(
            """SELECT flashcard_decks.* FROM flashcard_decks
               JOIN courses ON courses.id = flashcard_decks.course_id
               WHERE flashcard_decks.id = ? AND flashcard_decks.course_id = ?
                 AND courses.owner_user_id = ?""",
            (deck_id, course_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        return row

    def _owned_card_row(
        self, conn: sqlite3.Connection, course_id: str, deck_id: str, card_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            """SELECT flashcards.* FROM flashcards
               JOIN flashcard_decks ON flashcard_decks.id = flashcards.deck_id
               JOIN courses ON courses.id = flashcard_decks.course_id
               WHERE flashcards.id = ? AND flashcards.deck_id = ?
                 AND flashcard_decks.id = ? AND flashcard_decks.course_id = ?
                 AND courses.owner_user_id = ?""",
            (card_id, deck_id, deck_id, course_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        return row

    def _schedule_row(self, conn: sqlite3.Connection, card_id: str) -> sqlite3.Row:
        row = conn.execute(
            """SELECT card_id, review_count, interval_seconds, next_review_at, last_review_id
               FROM flashcard_review_states WHERE card_id = ?""",
            (card_id,),
        ).fetchone()
        if row is None:
            raise self._not_found()
        return row

    def create_deck(
        self, course_id: str, *, title: str, expected_course_write_epoch: int
    ) -> FlashcardDeck:
        now = time.time()
        deck_id = _deck_id()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            conn.execute(
                """INSERT INTO flashcard_decks
                   (id, owner_user_id, course_id, title, mode, state, source_snapshot_json,
                    generation_receipt_json, revision, write_epoch, created_at, updated_at,
                    ready_at, archived_at)
                   VALUES (?, ?, ?, ?, 'manual', 'draft', '[]', NULL, 1, 1, ?, ?, NULL, NULL)""",
                (deck_id, self.owner_user_id, course_id, self._clean_text(title, "Deck title", maximum=160), now, now),
            )
            row = conn.execute("SELECT * FROM flashcard_decks WHERE id = ?", (deck_id,)).fetchone()
        assert row is not None
        return self._deck_from_row(row)

    def list_decks(self, course_id: str, *, include_archived: bool = True) -> list[FlashcardDeck]:
        self.course_repository.get_course(course_id)
        sql = """SELECT flashcard_decks.* FROM flashcard_decks
                 JOIN courses ON courses.id = flashcard_decks.course_id
                 WHERE flashcard_decks.course_id = ? AND courses.owner_user_id = ?"""
        params: list[Any] = [course_id, self.owner_user_id]
        if not include_archived:
            sql += " AND flashcard_decks.state != 'archived'"
        sql += " ORDER BY flashcard_decks.updated_at DESC, flashcard_decks.id"
        with self.course_repository._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._deck_from_row(row) for row in rows]

    def _summary(self, conn: sqlite3.Connection, deck_id: str, *, at: float) -> FlashcardReviewSummary:
        total = int(conn.execute(
            "SELECT COUNT(*) FROM flashcards WHERE deck_id = ? AND state = 'active'", (deck_id,)
        ).fetchone()[0])
        deck_state = conn.execute(
            "SELECT state FROM flashcard_decks WHERE id = ?", (deck_id,)
        ).fetchone()
        due = 0 if deck_state is not None and str(deck_state["state"]) == "archived" else int(
            conn.execute(
                """SELECT COUNT(*) FROM flashcards JOIN flashcard_review_states
                   ON flashcard_review_states.card_id = flashcards.id
                   WHERE flashcards.deck_id = ? AND flashcards.state = 'active'
                     AND flashcard_review_states.next_review_at <= ?""",
                (deck_id, at),
            ).fetchone()[0]
        )
        review_count = int(conn.execute(
            "SELECT COUNT(*) FROM flashcard_reviews WHERE deck_id = ?", (deck_id,)
        ).fetchone()[0])
        return FlashcardReviewSummary(
            at=at,
            total_active_cards=total,
            due_cards=due,
            completed_cards=max(total - due, 0),
            review_count=review_count,
        )

    def _view(self, conn: sqlite3.Connection, deck: FlashcardDeck, *, at: float, due_only: bool = False) -> FlashcardDeckView:
        card_sql = "SELECT * FROM flashcards WHERE deck_id = ?"
        card_params: list[Any] = [deck.id]
        if due_only:
            card_sql = """SELECT flashcards.* FROM flashcards JOIN flashcard_review_states
                          ON flashcard_review_states.card_id = flashcards.id
                          WHERE flashcards.deck_id = ? AND flashcards.state = 'active'
                            AND flashcard_review_states.next_review_at <= ?"""
            card_params.append(at)
        card_sql += " ORDER BY ordinal, id"
        cards = [self._card_from_row(row) for row in conn.execute(card_sql, card_params).fetchall()]
        schedules = [
            self._schedule_from_row(row)
            for row in conn.execute(
                """SELECT card_id, review_count, interval_seconds, next_review_at, last_review_id
                   FROM flashcard_review_states WHERE deck_id = ? ORDER BY next_review_at, card_id""",
                (deck.id,),
            ).fetchall()
        ]
        return FlashcardDeckView(deck=deck, cards=cards, schedules=schedules, review_summary=self._summary(conn, deck.id, at=at))

    def get_deck(self, course_id: str, deck_id: str, *, at: float | None = None) -> FlashcardDeckView:
        at = time.time() if at is None else float(at)
        with self.course_repository._connect() as conn:
            deck = self._deck_from_row(self._owned_deck_row(conn, course_id, deck_id))
            return self._view(conn, deck, at=at)

    def _mutate_deck(
        self, conn: sqlite3.Connection, course_id: str, deck_id: str, *, expected_revision: int,
        expected_course_write_epoch: int, title: str | None = None, target_state: str | None = None,
    ) -> FlashcardDeck:
        self._course_for_write(conn, course_id, expected_course_write_epoch)
        row = self._owned_deck_row(conn, course_id, deck_id)
        deck = self._deck_from_row(row)
        if deck.revision != expected_revision:
            raise CourseConflictError("Flashcard deck revision is stale")
        now = time.time()
        if target_state == "ready":
            if deck.state != "draft":
                raise CourseConflictError("Flashcard deck is not a draft")
            if not conn.execute("SELECT 1 FROM flashcards WHERE deck_id = ? AND state = 'active'", (deck_id,)).fetchone():
                raise CourseConflictError("Flashcard deck needs at least one active card")
            conn.execute("""UPDATE flashcard_decks SET state = 'ready', revision = revision + 1,
                          write_epoch = write_epoch + 1, ready_at = ?, updated_at = ? WHERE id = ?""", (now, now, deck_id))
        elif target_state == "archived":
            if deck.state == "archived":
                raise CourseConflictError("Flashcard deck is already archived")
            conn.execute("""UPDATE flashcard_decks SET state = 'archived', revision = revision + 1,
                          write_epoch = write_epoch + 1, archived_at = ?, updated_at = ? WHERE id = ?""", (now, now, deck_id))
        elif target_state == "restore":
            if deck.state != "archived":
                raise CourseConflictError("Flashcard deck is active or its revision is stale")
            # Archive is a retention fence, not a publication side effect. A
            # deck archived while drafting resumes as a draft; only a formerly
            # ready deck resumes ready for study.
            restore_state = "ready" if deck.ready_at is not None else "draft"
            if restore_state == "ready" and not conn.execute(
                "SELECT 1 FROM flashcards WHERE deck_id = ? AND state = 'active'", (deck_id,)
            ).fetchone():
                raise CourseConflictError("Flashcard deck needs an active card to restore")
            conn.execute(
                """UPDATE flashcard_decks SET state = ?, revision = revision + 1,
                   write_epoch = write_epoch + 1, archived_at = NULL, updated_at = ? WHERE id = ?""",
                (restore_state, now, deck_id),
            )
        else:
            if deck.state == "archived":
                raise CourseConflictError("Archived Flashcard decks cannot be edited")
            assert title is not None
            conn.execute("""UPDATE flashcard_decks SET title = ?, revision = revision + 1,
                          write_epoch = write_epoch + 1, updated_at = ? WHERE id = ?""", (self._clean_text(title, "Deck title", maximum=160), now, deck_id))
        updated = conn.execute("SELECT * FROM flashcard_decks WHERE id = ?", (deck_id,)).fetchone()
        assert updated is not None
        return self._deck_from_row(updated)

    def rename_deck(self, course_id: str, deck_id: str, *, title: str, expected_revision: int, expected_course_write_epoch: int) -> FlashcardDeck:
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._mutate_deck(conn, course_id, deck_id, expected_revision=expected_revision, expected_course_write_epoch=expected_course_write_epoch, title=title)

    def ready_deck(self, course_id: str, deck_id: str, *, expected_revision: int, expected_course_write_epoch: int) -> FlashcardDeck:
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._mutate_deck(conn, course_id, deck_id, expected_revision=expected_revision, expected_course_write_epoch=expected_course_write_epoch, target_state="ready")

    def archive_deck(self, course_id: str, deck_id: str, *, expected_revision: int, expected_course_write_epoch: int) -> FlashcardDeck:
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._mutate_deck(conn, course_id, deck_id, expected_revision=expected_revision, expected_course_write_epoch=expected_course_write_epoch, target_state="archived")

    def restore_deck(self, course_id: str, deck_id: str, *, expected_revision: int, expected_course_write_epoch: int) -> FlashcardDeck:
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._mutate_deck(conn, course_id, deck_id, expected_revision=expected_revision, expected_course_write_epoch=expected_course_write_epoch, target_state="restore")

    def _editable_deck(self, conn: sqlite3.Connection, course_id: str, deck_id: str, *, expected_deck_revision: int, expected_course_write_epoch: int) -> FlashcardDeck:
        self._course_for_write(conn, course_id, expected_course_write_epoch)
        deck = self._deck_from_row(self._owned_deck_row(conn, course_id, deck_id))
        if deck.state == "archived":
            raise CourseConflictError("Archived Flashcard decks cannot be edited")
        if deck.revision != expected_deck_revision:
            raise CourseConflictError("Flashcard deck revision is stale")
        if deck.mode != "manual":
            raise CourseConflictError("Generated Flashcard cards are reserved for generation operations")
        return deck

    def add_card(
        self, course_id: str, deck_id: str, *, prompt: str, answer: str, objective_ids: Iterable[str] = (),
        expected_deck_revision: int, expected_course_write_epoch: int,
    ) -> Flashcard:
        objectives = self._objective_ids(objective_ids)
        now = time.time()
        card_id = _card_id()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._editable_deck(conn, course_id, deck_id, expected_deck_revision=expected_deck_revision, expected_course_write_epoch=expected_course_write_epoch)
            card_count = int(conn.execute("SELECT COUNT(*) FROM flashcards WHERE deck_id = ?", (deck_id,)).fetchone()[0])
            if card_count >= _MAX_CARDS:
                raise CourseConflictError("Flashcard deck has reached its card limit")
            ordinal = int(conn.execute("SELECT COALESCE(MAX(ordinal), 0) + 1 FROM flashcards WHERE deck_id = ?", (deck_id,)).fetchone()[0])
            conn.execute(
                """INSERT INTO flashcards (id, deck_id, prompt, answer, objective_ids_json, citation_json,
                   ordinal, revision, state, created_at, updated_at, archived_at)
                   VALUES (?, ?, ?, ?, ?, '[]', ?, 1, 'active', ?, ?, NULL)""",
                (card_id, deck_id, self._clean_text(prompt, "Card prompt", maximum=12_000), self._clean_text(answer, "Card answer", maximum=12_000), self._json(objectives, field="objective_ids"), ordinal, now, now),
            )
            conn.execute(
                """INSERT INTO flashcard_review_states
                   (card_id, owner_user_id, course_id, deck_id, review_count, interval_seconds,
                    next_review_at, last_review_id, updated_at)
                   VALUES (?, ?, ?, ?, 0, 0, ?, NULL, ?)""",
                (card_id, self.owner_user_id, course_id, deck_id, now, now),
            )
            conn.execute("UPDATE flashcard_decks SET revision = revision + 1, write_epoch = write_epoch + 1, updated_at = ? WHERE id = ?", (now, deck_id))
            row = conn.execute("SELECT * FROM flashcards WHERE id = ?", (card_id,)).fetchone()
        assert row is not None
        return self._card_from_row(row)

    def update_card(
        self, course_id: str, deck_id: str, card_id: str, *, prompt: str, answer: str,
        objective_ids: Iterable[str] = (), expected_card_revision: int, expected_deck_revision: int,
        expected_course_write_epoch: int,
    ) -> Flashcard:
        objectives = self._objective_ids(objective_ids)
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._editable_deck(conn, course_id, deck_id, expected_deck_revision=expected_deck_revision, expected_course_write_epoch=expected_course_write_epoch)
            card = self._card_from_row(self._owned_card_row(conn, course_id, deck_id, card_id))
            if card.state != "active":
                raise CourseConflictError("Archived Flashcards cannot be edited")
            if card.revision != expected_card_revision:
                raise CourseConflictError("Flashcard revision is stale")
            conn.execute("""UPDATE flashcards SET prompt = ?, answer = ?, objective_ids_json = ?,
                          revision = revision + 1, updated_at = ? WHERE id = ?""", (self._clean_text(prompt, "Card prompt", maximum=12_000), self._clean_text(answer, "Card answer", maximum=12_000), self._json(objectives, field="objective_ids"), now, card_id))
            conn.execute("UPDATE flashcard_decks SET revision = revision + 1, write_epoch = write_epoch + 1, updated_at = ? WHERE id = ?", (now, deck_id))
            row = conn.execute("SELECT * FROM flashcards WHERE id = ?", (card_id,)).fetchone()
        assert row is not None
        return self._card_from_row(row)

    def archive_card(
        self, course_id: str, deck_id: str, card_id: str, *, expected_card_revision: int,
        expected_deck_revision: int, expected_course_write_epoch: int,
    ) -> Flashcard:
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._editable_deck(conn, course_id, deck_id, expected_deck_revision=expected_deck_revision, expected_course_write_epoch=expected_course_write_epoch)
            card = self._card_from_row(self._owned_card_row(conn, course_id, deck_id, card_id))
            if card.state != "active":
                raise CourseConflictError("Flashcard is already archived")
            if card.revision != expected_card_revision:
                raise CourseConflictError("Flashcard revision is stale")
            conn.execute("UPDATE flashcards SET state = 'archived', revision = revision + 1, archived_at = ?, updated_at = ? WHERE id = ?", (now, now, card_id))
            conn.execute("UPDATE flashcard_decks SET revision = revision + 1, write_epoch = write_epoch + 1, updated_at = ? WHERE id = ?", (now, deck_id))
            row = conn.execute("SELECT * FROM flashcards WHERE id = ?", (card_id,)).fetchone()
        assert row is not None
        return self._card_from_row(row)

    def due_cards(self, course_id: str, deck_id: str, *, at: float | None = None) -> FlashcardDeckView:
        at = time.time() if at is None else float(at)
        with self.course_repository._connect() as conn:
            deck = self._deck_from_row(self._owned_deck_row(conn, course_id, deck_id))
            if deck.state == "archived":
                return FlashcardDeckView(
                    deck=deck,
                    cards=[],
                    schedules=[],
                    review_summary=self._summary(conn, deck.id, at=at),
                )
            return self._view(conn, deck, at=at, due_only=True)

    @staticmethod
    def _interval(previous: int, rating: FlashcardRating) -> int:
        if rating == "again":
            return 60
        if rating == "hard":
            return min(_MAX_INTERVAL_SECONDS, max(6 * 60 * 60, int(previous * 1.2)))
        if rating == "good":
            return min(_MAX_INTERVAL_SECONDS, max(24 * 60 * 60, int(previous * 2)))
        return min(_MAX_INTERVAL_SECONDS, max(4 * 24 * 60 * 60, int(previous * 3)))

    def record_review(
        self, course_id: str, deck_id: str, *, card_id: str, rating: FlashcardRating,
        idempotency_key: str, expected_deck_revision: int, expected_card_revision: int,
        expected_course_write_epoch: int, now: float | None = None,
    ) -> tuple[FlashcardReview, FlashcardSchedule, FlashcardReviewSummary]:
        if rating not in {"again", "hard", "good", "easy"}:
            raise ValueError("rating must be again, hard, good, or easy")
        key = self._clean_text(idempotency_key, "Idempotency key", maximum=160)
        now = time.time() if now is None else float(now)
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # The route's Course parent is authority even for an idempotent
            # retry. A same-owner caller cannot replay an event by placing its
            # deck ID under a different Course path, and an archive/revocation
            # fence remains effective for retries.
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            deck = self._deck_from_row(self._owned_deck_row(conn, course_id, deck_id))
            if deck.state != "ready":
                raise CourseConflictError("Flashcard deck is not ready for review")
            if deck.revision != expected_deck_revision:
                raise CourseConflictError("Flashcard deck revision is stale")
            card = self._card_from_row(self._owned_card_row(conn, course_id, deck_id, card_id))
            if card.state != "active":
                raise CourseConflictError("Archived Flashcards cannot be reviewed")
            if card.revision != expected_card_revision:
                raise CourseConflictError("Flashcard revision is stale")
            duplicate = conn.execute(
                "SELECT * FROM flashcard_reviews WHERE deck_id = ? AND idempotency_key = ?",
                (deck_id, key),
            ).fetchone()
            if duplicate is not None:
                review = self._review_from_row(duplicate)
                if (
                    review.course_id != course_id
                    or review.card_id != card_id
                    or review.rating != rating
                    or review.course_write_epoch != expected_course_write_epoch
                    or review.deck_revision != expected_deck_revision
                    or review.card_revision != expected_card_revision
                ):
                    raise CourseConflictError("Idempotency key conflicts with an existing review")
                schedule = FlashcardSchedule(card_id=review.card_id, review_count=review.review_count, interval_seconds=review.interval_seconds, next_review_at=review.next_review_at, last_review_id=review.id)
                return review, schedule, self._summary(conn, deck_id, at=now)
            previous = self._schedule_from_row(self._schedule_row(conn, card_id))
            interval = self._interval(previous.interval_seconds, rating)
            review = FlashcardReview(
                id=_review_id(), owner_user_id=self.owner_user_id, course_id=course_id, deck_id=deck_id,
                card_id=card_id, rating=rating, idempotency_key=key,
                course_write_epoch=expected_course_write_epoch, deck_revision=deck.revision,
                card_revision=card.revision, review_count=previous.review_count + 1,
                interval_seconds=interval, was_due=previous.next_review_at <= now,
                reviewed_at=now, next_review_at=now + interval,
            )
            conn.execute(
                """INSERT INTO flashcard_reviews
                   (id, owner_user_id, course_id, deck_id, card_id, rating, idempotency_key,
                    course_write_epoch, deck_revision, card_revision, review_count, interval_seconds, was_due,
                    reviewed_at, next_review_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (review.id, review.owner_user_id, review.course_id, review.deck_id, review.card_id,
                 review.rating, review.idempotency_key, review.course_write_epoch, review.deck_revision, review.card_revision,
                 review.review_count, review.interval_seconds, int(review.was_due), review.reviewed_at,
                 review.next_review_at),
            )
            conn.execute(
                """UPDATE flashcard_review_states SET review_count = ?, interval_seconds = ?,
                   next_review_at = ?, last_review_id = ?, updated_at = ? WHERE card_id = ?""",
                (review.review_count, review.interval_seconds, review.next_review_at, review.id,
                 review.reviewed_at, card_id),
            )
            schedule = FlashcardSchedule(card_id=card_id, review_count=review.review_count, interval_seconds=review.interval_seconds, next_review_at=review.next_review_at, last_review_id=review.id)
            summary = self._summary(conn, deck_id, at=now)
        return review, schedule, summary
