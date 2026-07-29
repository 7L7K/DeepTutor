"""Authenticated service seam for Course-owned Flashcards."""

from __future__ import annotations

from typing import Any

from .flashcard_models import (
    Flashcard,
    FlashcardDeck,
    FlashcardDeckView,
    FlashcardReview,
    FlashcardReviewSummary,
    FlashcardSchedule,
)
from .flashcard_repository import CourseFlashcardRepository


class CourseFlashcardService:
    def __init__(self, repository: CourseFlashcardRepository) -> None:
        self.repository = repository

    def create_deck(self, course_id: str, **kwargs: Any) -> FlashcardDeck:
        return self.repository.create_deck(course_id, **kwargs)

    def list_decks(self, course_id: str, **kwargs: Any) -> list[FlashcardDeck]:
        return self.repository.list_decks(course_id, **kwargs)

    def get_deck(self, course_id: str, deck_id: str, **kwargs: Any) -> FlashcardDeckView:
        return self.repository.get_deck(course_id, deck_id, **kwargs)

    def rename_deck(self, course_id: str, deck_id: str, **kwargs: Any) -> FlashcardDeck:
        return self.repository.rename_deck(course_id, deck_id, **kwargs)

    def archive_deck(self, course_id: str, deck_id: str, **kwargs: Any) -> FlashcardDeck:
        return self.repository.archive_deck(course_id, deck_id, **kwargs)

    def restore_deck(self, course_id: str, deck_id: str, **kwargs: Any) -> FlashcardDeck:
        return self.repository.restore_deck(course_id, deck_id, **kwargs)

    def ready_deck(self, course_id: str, deck_id: str, **kwargs: Any) -> FlashcardDeck:
        return self.repository.ready_deck(course_id, deck_id, **kwargs)

    def add_card(self, course_id: str, deck_id: str, **kwargs: Any) -> Flashcard:
        return self.repository.add_card(course_id, deck_id, **kwargs)

    def update_card(self, course_id: str, deck_id: str, card_id: str, **kwargs: Any) -> Flashcard:
        return self.repository.update_card(course_id, deck_id, card_id, **kwargs)

    def archive_card(self, course_id: str, deck_id: str, card_id: str, **kwargs: Any) -> Flashcard:
        return self.repository.archive_card(course_id, deck_id, card_id, **kwargs)

    def due_cards(self, course_id: str, deck_id: str, **kwargs: Any) -> FlashcardDeckView:
        return self.repository.due_cards(course_id, deck_id, **kwargs)

    def record_review(self, course_id: str, deck_id: str, **kwargs: Any) -> tuple[FlashcardReview, FlashcardSchedule, FlashcardReviewSummary]:
        return self.repository.record_review(course_id, deck_id, **kwargs)
