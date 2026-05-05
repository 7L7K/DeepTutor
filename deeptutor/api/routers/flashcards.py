from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from deeptutor.api.routers.access import get_current_tester
from deeptutor.services.flashcards import get_flashcard_service

router = APIRouter()


class FlashcardGenerateRequest(BaseModel):
    source_type: Literal["topic", "knowledge"] = "topic"
    topic: str = ""
    knowledge_base_names: list[str] = Field(default_factory=list)
    card_count: int = Field(default=10, ge=5, le=40)
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
async def generate_flashcard_deck(
    payload: FlashcardGenerateRequest,
    background_tasks: BackgroundTasks,
    tester: dict = Depends(get_current_tester),
):
    service = get_flashcard_service()
    try:
        deck, reused_existing, should_continue = await service.generate_progressive_deck(
            **payload.model_dump(),
            tester_id=tester["id"],
        )
        if should_continue:
            background_tasks.add_task(
                service.complete_progressive_deck,
                deck_id=deck["id"],
                source_type=payload.source_type,
                topic=payload.topic,
                knowledge_base_names=payload.knowledge_base_names,
                card_count=payload.card_count,
                style=payload.style,
                tester_id=tester["id"],
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"deck": deck, "reused_existing": reused_existing}


@router.get("/decks")
async def list_flashcard_decks(
    limit: int = Query(default=12, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    tester: dict = Depends(get_current_tester),
):
    service = get_flashcard_service()
    decks = await service.list_decks(limit=limit, offset=offset, tester_id=tester["id"])
    return {"decks": decks}


@router.get("/decks/{deck_id}")
async def get_flashcard_deck(deck_id: str, tester: dict = Depends(get_current_tester)):
    service = get_flashcard_service()
    deck = await service.get_deck(deck_id, tester_id=tester["id"])
    if deck is None:
        raise HTTPException(status_code=404, detail="Flashcard deck not found")
    return {"deck": deck}


@router.post("/decks/{deck_id}/reviews")
async def review_flashcard(
    deck_id: str,
    payload: FlashcardReviewRequest,
    tester: dict = Depends(get_current_tester),
):
    service = get_flashcard_service()
    try:
        deck = await service.record_review(deck_id=deck_id, **payload.model_dump(), tester_id=tester["id"])
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status, detail=detail)
    return {"deck": deck}


@router.post("/decks/{deck_id}/restart")
async def restart_flashcard_deck(deck_id: str, tester: dict = Depends(get_current_tester)):
    service = get_flashcard_service()
    try:
        deck = await service.restart_deck(deck_id, tester_id=tester["id"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deck": deck}


@router.post("/decks/{deck_id}/complete")
async def complete_flashcard_pass(
    deck_id: str,
    payload: FlashcardCompleteRequest,
    tester: dict = Depends(get_current_tester),
):
    service = get_flashcard_service()
    try:
        deck, session_review = await service.complete_session(
            deck_id=deck_id,
            **payload.model_dump(),
            tester_id=tester["id"],
        )
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status, detail=detail)
    return {"deck": deck, "session_review": session_review}


@router.post("/topic-suggestions")
async def get_flashcard_topic_suggestions(
    payload: FlashcardTopicSuggestionsRequest,
    tester: dict = Depends(get_current_tester),
):
    service = get_flashcard_service()
    try:
        suggestions = await service.get_topic_suggestions(**payload.model_dump(), tester_id=tester["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"suggestions": suggestions}
