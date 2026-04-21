from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from deeptutor.services.flashcards import get_flashcard_service

router = APIRouter()


class FlashcardGenerateRequest(BaseModel):
    source_type: Literal["topic", "knowledge"] = "topic"
    topic: str = ""
    knowledge_base_names: list[str] = Field(default_factory=list)
    card_count: int = Field(default=20, ge=5, le=40)
    style: Literal["mixed", "definition", "concept"] = "mixed"
    reuse_existing: bool = True

    @field_validator("knowledge_base_names", mode="before")
    @classmethod
    def _coerce_kbs(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []


class FlashcardReviewRequest(BaseModel):
    card_id: str
    rating: Literal["got_it", "missed", "skipped"]


class FlashcardCompleteRequest(BaseModel):
    review_mode: Literal["full_deck", "missed_only"] = "full_deck"
    card_ids: list[str] = Field(default_factory=list)

    @field_validator("card_ids", mode="before")
    @classmethod
    def _coerce_card_ids(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []


class FlashcardTopicSuggestionsRequest(BaseModel):
    knowledge_base_names: list[str] = Field(default_factory=list)
    hint: str = ""

    @field_validator("knowledge_base_names", mode="before")
    @classmethod
    def _coerce_kbs(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []


@router.post("/generate")
async def generate_flashcard_deck(payload: FlashcardGenerateRequest):
    service = get_flashcard_service()
    try:
        deck, reused_existing = await service.generate_deck(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"deck": deck, "reused_existing": reused_existing}


@router.get("/decks")
async def list_flashcard_decks(
    limit: int = Query(default=12, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
):
    service = get_flashcard_service()
    decks = await service.list_decks(limit=limit, offset=offset)
    return {"decks": decks}


@router.get("/decks/{deck_id}")
async def get_flashcard_deck(deck_id: str):
    service = get_flashcard_service()
    deck = await service.get_deck(deck_id)
    if deck is None:
        raise HTTPException(status_code=404, detail="Flashcard deck not found")
    return {"deck": deck}


@router.post("/decks/{deck_id}/reviews")
async def review_flashcard(deck_id: str, payload: FlashcardReviewRequest):
    service = get_flashcard_service()
    try:
        deck = await service.record_review(deck_id=deck_id, **payload.model_dump())
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status, detail=detail)
    return {"deck": deck}


@router.post("/decks/{deck_id}/restart")
async def restart_flashcard_deck(deck_id: str):
    service = get_flashcard_service()
    try:
        deck = await service.restart_deck(deck_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deck": deck}


@router.post("/decks/{deck_id}/complete")
async def complete_flashcard_pass(deck_id: str, payload: FlashcardCompleteRequest):
    service = get_flashcard_service()
    try:
        deck, session_review = await service.complete_session(deck_id=deck_id, **payload.model_dump())
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status, detail=detail)
    return {"deck": deck, "session_review": session_review}


@router.post("/topic-suggestions")
async def get_flashcard_topic_suggestions(payload: FlashcardTopicSuggestionsRequest):
    service = get_flashcard_service()
    try:
        suggestions = await service.get_topic_suggestions(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"suggestions": suggestions}
