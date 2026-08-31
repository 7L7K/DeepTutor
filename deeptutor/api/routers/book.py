"""
Book Engine API Router
======================

REST + WebSocket endpoints for the ``BookEngine``. Phase 1 surface:
create / confirm / compile / read / delete + a per-book event stream.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_admin
from deeptutor.book import (
    BlockType,
    BookProposal,
    Spine,
    get_book_engine,
)
from deeptutor.book.models import ContentType
from deeptutor.book.streaming import SOURCE as BOOK_SOURCE
from deeptutor.core.stream import StreamEventType
from deeptutor.core.stream_bus import StreamBus
from deeptutor.services.sandbox.quota import QuotaExceeded, UserExecQuota

router = APIRouter(dependencies=[Depends(require_admin)])
logger = logging.getLogger(__name__)


# Book commands never carry binary data. Keep their independent, much smaller
# protocol limit instead of inheriting the chat attachment transport budget.
_BOOK_WS_MAX_FRAME_BYTES = 512 * 1024
_BOOK_WS_MAX_STRING_CHARS = 32 * 1024
_BOOK_WS_MAX_INTENT_CHARS = 200 * 1024
_BOOK_WS_MAX_ID_CHARS = 512
_BOOK_WS_MAX_LIST_ITEMS = 100
_BOOK_WS_MAX_DYNAMIC_BYTES = 128 * 1024
_BOOK_WS_MAX_DEPTH = 12
_BOOK_WS_FIRST_FRAME_TIMEOUT_S = 30.0
_BOOK_WS_IDLE_FRAME_TIMEOUT_S = 120.0
_BOOK_WS_MAX_INVALID_MESSAGES = 1
_BOOK_WS_RECEIVE_USER_QUOTA = UserExecQuota(max_concurrent=1, max_per_minute=60)
_BOOK_WS_RECEIVE_GLOBAL_QUOTA = UserExecQuota(max_concurrent=4, max_per_minute=240)
_BOOK_WS_ACTION_USER_QUOTA = UserExecQuota(max_concurrent=1, max_per_minute=12)
_BOOK_WS_ACTION_GLOBAL_QUOTA = UserExecQuota(max_concurrent=2, max_per_minute=24)
_BOOK_WS_RECEIVE_GLOBAL_KEY = "book-ws-receive-global"
_BOOK_WS_ACTION_GLOBAL_KEY = "book-ws-action-global"


# ─────────────────────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────────────────────


class CreateBookRequest(BaseModel):
    user_intent: str = Field(default="")
    chat_session_id: str = Field(default="")
    chat_selections: list[dict[str, Any]] = Field(default_factory=list)
    notebook_refs: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_bases: list[str] = Field(default_factory=list)
    question_categories: list[int] = Field(default_factory=list)
    question_entries: list[int] = Field(default_factory=list)
    language: str = Field(default="en")


class ConfirmProposalRequest(BaseModel):
    book_id: str
    proposal: dict[str, Any] | None = None  # full edited BookProposal payload


class ConfirmSpineRequest(BaseModel):
    book_id: str
    spine: dict[str, Any] | None = None
    auto_compile: bool = True


class CompilePageRequest(BaseModel):
    book_id: str
    page_id: str
    force: bool = False


class RegenerateBlockRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str
    params_override: dict[str, Any] | None = None


class InsertBlockRequest(BaseModel):
    book_id: str
    page_id: str
    block_type: str
    params: dict[str, Any] | None = None
    position: int | None = None
    compile_now: bool = True


class DeleteBlockRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str


class MoveBlockRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str
    new_position: int


class ChangeBlockTypeRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str
    new_type: str
    params_override: dict[str, Any] | None = None


class DeepDiveRequest(BaseModel):
    book_id: str
    parent_page_id: str
    topic: str
    block_id: str | None = None
    content_type: str = "concept"


class QuizAttemptRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str
    question_id: str = ""
    user_answer: str = ""
    is_correct: bool = False
    request_remediation: bool = False


class SupplementRequest(BaseModel):
    book_id: str
    page_id: str
    topic: str


class PageChatSessionRequest(BaseModel):
    book_id: str
    page_id: str
    session_id: str


class RebuildBookRequest(BaseModel):
    book_id: str
    auto_compile: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# REST endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "book"}


@router.get("/books")
async def list_books() -> dict[str, Any]:
    engine = get_book_engine()
    return {"books": [b.model_dump(mode="json") for b in engine.list_books()]}


@router.get("/books/{book_id}")
async def get_book(book_id: str) -> dict[str, Any]:
    engine = get_book_engine()
    book = engine.load_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    spine = engine.load_spine(book_id)
    pages = engine.list_pages(book_id)
    progress = engine.load_progress(book_id)
    return {
        "book": book.model_dump(mode="json"),
        "spine": spine.model_dump(mode="json") if spine else None,
        "pages": [p.model_dump(mode="json") for p in pages],
        "progress": progress.model_dump(mode="json"),
    }


@router.get("/books/{book_id}/spine")
async def get_spine(book_id: str) -> dict[str, Any]:
    engine = get_book_engine()
    spine = engine.load_spine(book_id)
    if spine is None:
        raise HTTPException(status_code=404, detail="Spine not found")
    return {"spine": spine.model_dump(mode="json")}


@router.get("/books/{book_id}/pages/{page_id}")
async def get_page(book_id: str, page_id: str) -> dict[str, Any]:
    engine = get_book_engine()
    page = engine.load_page(book_id, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"page": page.model_dump(mode="json")}


@router.delete("/books/{book_id}")
async def delete_book(book_id: str) -> dict[str, Any]:
    engine = get_book_engine()
    ok = engine.delete_book(book_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Book not found")
    return {"deleted": True, "book_id": book_id}


@router.post("/books")
async def create_book(req: CreateBookRequest) -> dict[str, Any]:
    """Stage 1: capture inputs + run IdeationAgent."""
    if not req.user_intent.strip():
        raise HTTPException(status_code=400, detail="user_intent is required")
    engine = get_book_engine()
    try:
        book, proposal = await engine.create_book(
            user_intent=req.user_intent,
            chat_session_id=req.chat_session_id,
            chat_selections=req.chat_selections,
            notebook_refs=req.notebook_refs,
            knowledge_bases=req.knowledge_bases,
            question_categories=req.question_categories,
            question_entries=req.question_entries,
            language=req.language,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"create_book failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "book": book.model_dump(mode="json"),
        "proposal": proposal.model_dump(mode="json"),
    }


@router.post("/books/confirm-proposal")
async def confirm_proposal(req: ConfirmProposalRequest) -> dict[str, Any]:
    """Stage 2: user confirms (and possibly edits) the proposal → SpineAgent."""
    engine = get_book_engine()
    edited: BookProposal | None = None
    if req.proposal:
        try:
            edited = BookProposal.model_validate(req.proposal)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid proposal: {exc}")
    try:
        book, spine = await engine.confirm_proposal(book_id=req.book_id, edited_proposal=edited)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"confirm_proposal failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "book": book.model_dump(mode="json"),
        "spine": spine.model_dump(mode="json"),
    }


@router.post("/books/confirm-spine")
async def confirm_spine(req: ConfirmSpineRequest) -> dict[str, Any]:
    """Stage 3: user confirms the spine → create pending page shells."""
    engine = get_book_engine()
    edited: Spine | None = None
    if req.spine:
        try:
            edited = Spine.model_validate(req.spine)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid spine: {exc}")
    try:
        pages = await engine.confirm_spine(
            book_id=req.book_id,
            edited_spine=edited,
            auto_compile=req.auto_compile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"confirm_spine failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"pages": [p.model_dump(mode="json") for p in pages]}


@router.post("/books/compile-page")
async def compile_page(req: CompilePageRequest) -> dict[str, Any]:
    """Drive the compiler for the page the user just opened (current-page priority)."""
    engine = get_book_engine()
    try:
        page = await engine.compile_page(book_id=req.book_id, page_id=req.page_id, force=req.force)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"compile_page failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"page": page.model_dump(mode="json")}


@router.post("/books/regenerate-block")
async def regenerate_block(req: RegenerateBlockRequest) -> dict[str, Any]:
    engine = get_book_engine()
    try:
        block = await engine.regenerate_block(
            book_id=req.book_id,
            page_id=req.page_id,
            block_id=req.block_id,
            params_override=req.params_override,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"regenerate_block failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if block is None:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"block": block.model_dump(mode="json")}


def _coerce_block_type(name: str) -> BlockType:
    try:
        return BlockType(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown block type: {name}") from exc


def _coerce_content_type(name: str) -> ContentType:
    try:
        return ContentType(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown content type: {name}") from exc


@router.post("/books/insert-block")
async def insert_block(req: InsertBlockRequest) -> dict[str, Any]:
    engine = get_book_engine()
    block_type = _coerce_block_type(req.block_type)
    try:
        block = await engine.insert_block(
            book_id=req.book_id,
            page_id=req.page_id,
            block_type=block_type,
            params=req.params,
            position=req.position,
            compile_now=req.compile_now,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"insert_block failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if block is None:
        raise HTTPException(status_code=404, detail="Page or chapter not found")
    return {"block": block.model_dump(mode="json")}


@router.post("/books/delete-block")
async def delete_block(req: DeleteBlockRequest) -> dict[str, Any]:
    engine = get_book_engine()
    ok = await engine.delete_block(book_id=req.book_id, page_id=req.page_id, block_id=req.block_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"ok": True}


@router.post("/books/move-block")
async def move_block(req: MoveBlockRequest) -> dict[str, Any]:
    engine = get_book_engine()
    ok = await engine.move_block(
        book_id=req.book_id,
        page_id=req.page_id,
        block_id=req.block_id,
        new_position=req.new_position,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"ok": True}


@router.post("/books/change-block-type")
async def change_block_type(req: ChangeBlockTypeRequest) -> dict[str, Any]:
    engine = get_book_engine()
    new_type = _coerce_block_type(req.new_type)
    try:
        block = await engine.change_block_type(
            book_id=req.book_id,
            page_id=req.page_id,
            block_id=req.block_id,
            new_type=new_type,
            params_override=req.params_override,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"change_block_type failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if block is None:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"block": block.model_dump(mode="json")}


@router.post("/books/deep-dive")
async def deep_dive(req: DeepDiveRequest) -> dict[str, Any]:
    engine = get_book_engine()
    content_type = _coerce_content_type(req.content_type)
    try:
        page = await engine.create_deep_dive_subpage(
            book_id=req.book_id,
            parent_page_id=req.parent_page_id,
            topic=req.topic,
            block_id=req.block_id,
            content_type=content_type,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"deep_dive failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if page is None:
        raise HTTPException(status_code=404, detail="Parent page not found")
    return {"page": page.model_dump(mode="json")}


@router.post("/books/quiz-attempt")
async def quiz_attempt(req: QuizAttemptRequest) -> dict[str, Any]:
    engine = get_book_engine()
    progress = await engine.record_quiz_attempt(
        book_id=req.book_id,
        page_id=req.page_id,
        block_id=req.block_id,
        question_id=req.question_id,
        user_answer=req.user_answer,
        is_correct=req.is_correct,
    )
    return {"progress": progress.model_dump(mode="json")}


@router.get("/books/{book_id}/health")
async def book_health(book_id: str) -> dict[str, Any]:
    engine = get_book_engine()
    drift = engine.kb_drift_report(book_id)
    log = engine.log_health(book_id)
    return {"kb_drift": drift, "log_health": log}


@router.post("/books/{book_id}/refresh-fingerprints")
async def refresh_fingerprints(book_id: str) -> dict[str, Any]:
    engine = get_book_engine()
    result = engine.refresh_kb_fingerprints(book_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return result


@router.post("/books/supplement")
async def supplement(req: SupplementRequest) -> dict[str, Any]:
    engine = get_book_engine()
    try:
        block = await engine.supplement_for_weakness(
            book_id=req.book_id,
            page_id=req.page_id,
            topic=req.topic,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"supplement failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if block is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"block": block.model_dump(mode="json")}


@router.post("/books/page-chat-session")
async def set_page_chat_session(req: PageChatSessionRequest) -> dict[str, Any]:
    engine = get_book_engine()
    book = engine.set_page_chat_session(
        book_id=req.book_id,
        page_id=req.page_id,
        session_id=req.session_id,
    )
    if book is None:
        raise HTTPException(status_code=404, detail="Book or page not found")
    return {"book": book.model_dump(mode="json")}


@router.post("/books/rebuild")
async def rebuild_book(req: RebuildBookRequest) -> dict[str, Any]:
    engine = get_book_engine()
    try:
        pages = await engine.rebuild_book(book_id=req.book_id, auto_compile=req.auto_compile)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"rebuild_book failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"pages": [p.model_dump(mode="json") for p in pages]}


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket – streamed Book events
# ─────────────────────────────────────────────────────────────────────────────


def _utf8_byte_length(value: str) -> int:
    total = 0
    for char in value:
        codepoint = ord(char)
        total += (
            1 if codepoint <= 0x7F else 2 if codepoint <= 0x7FF else 3 if codepoint <= 0xFFFF else 4
        )
    return total


def _reject_duplicate_json_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _strict_mapping(value: object, *, allowed: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value).difference(allowed):
        raise ValueError(f"{label} is invalid")
    return value


def _bounded_string(value: object, *, maximum: int = _BOOK_WS_MAX_STRING_CHARS) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("string is invalid")
    return value


def _bounded_id(value: object) -> str:
    return _bounded_string(value, maximum=_BOOK_WS_MAX_ID_CHARS)


def _bounded_string_list(value: object, *, maximum: int = _BOOK_WS_MAX_LIST_ITEMS) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("list is invalid")
    return [_bounded_string(item) for item in value]


def _bounded_int_list(value: object, *, maximum: int = _BOOK_WS_MAX_LIST_ITEMS) -> list[int]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("list is invalid")
    result: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError("integer list is invalid")
        result.append(item)
    return result


def _validate_dynamic_json(
    value: object,
    *,
    depth: int = 0,
    count: list[int] | None = None,
) -> None:
    """Bound intentionally extensible block parameters before engine use."""
    if depth > _BOOK_WS_MAX_DEPTH:
        raise ValueError("nested value is too deep")
    counter = count if count is not None else [0]
    counter[0] += 1
    if counter[0] > 1_000:
        raise ValueError("nested value has too many items")
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        _bounded_string(value)
        return
    if isinstance(value, list):
        if len(value) > _BOOK_WS_MAX_LIST_ITEMS:
            raise ValueError("nested list is too large")
        for item in value:
            _validate_dynamic_json(item, depth=depth + 1, count=counter)
        return
    if isinstance(value, dict):
        if len(value) > _BOOK_WS_MAX_LIST_ITEMS:
            raise ValueError("nested object is too large")
        for key, item in value.items():
            _bounded_string(key, maximum=_BOOK_WS_MAX_ID_CHARS)
            _validate_dynamic_json(item, depth=depth + 1, count=counter)
        return
    raise ValueError("nested value is invalid")


def _validate_book_proposal(value: object) -> BookProposal:
    data = _strict_mapping(
        value,
        allowed={
            "title",
            "description",
            "scope",
            "target_level",
            "estimated_chapters",
            "rationale",
        },
        label="proposal",
    )
    for name in {"title", "description", "scope", "target_level", "rationale"}.intersection(data):
        _bounded_string(data[name])
    if "estimated_chapters" in data:
        chapters = data["estimated_chapters"]
        if isinstance(chapters, bool) or not isinstance(chapters, int) or not 0 <= chapters <= 100:
            raise ValueError("proposal is invalid")
    return BookProposal.model_validate(data)


def _validate_source_anchor(value: object) -> None:
    data = _strict_mapping(value, allowed={"kind", "ref", "snippet"}, label="source anchor")
    for item in data.values():
        _bounded_string(item)


def _validate_chapter(value: object) -> None:
    data = _strict_mapping(
        value,
        allowed={
            "id",
            "title",
            "learning_objectives",
            "content_type",
            "source_anchors",
            "prerequisites",
            "page_ids",
            "summary",
            "order",
        },
        label="chapter",
    )
    for name in {"id", "title", "content_type", "summary"}.intersection(data):
        _bounded_string(data[name])
    for name in {"learning_objectives", "prerequisites", "page_ids"}.intersection(data):
        _bounded_string_list(data[name])
    if "source_anchors" in data:
        anchors = data["source_anchors"]
        if not isinstance(anchors, list) or len(anchors) > _BOOK_WS_MAX_LIST_ITEMS:
            raise ValueError("source anchors are invalid")
        for anchor in anchors:
            _validate_source_anchor(anchor)
    if "order" in data and (isinstance(data["order"], bool) or not isinstance(data["order"], int)):
        raise ValueError("chapter is invalid")


def _validate_concept_graph(value: object) -> None:
    data = _strict_mapping(value, allowed={"nodes", "edges"}, label="concept graph")
    for name, allowed in (
        ("nodes", {"id", "label", "chapter_id", "description", "weight"}),
        ("edges", {"src", "dst", "relation", "rationale"}),
    ):
        if name not in data:
            continue
        values = data[name]
        if not isinstance(values, list) or len(values) > _BOOK_WS_MAX_LIST_ITEMS:
            raise ValueError("concept graph is invalid")
        for item in values:
            nested = _strict_mapping(item, allowed=allowed, label="concept graph item")
            for field, field_value in nested.items():
                if field == "weight":
                    if isinstance(field_value, bool) or not isinstance(field_value, (int, float)):
                        raise ValueError("concept graph is invalid")
                else:
                    _bounded_string(field_value)


def _validate_spine(value: object) -> Spine:
    data = _strict_mapping(
        value,
        allowed={
            "book_id",
            "chapters",
            "version",
            "updated_at",
            "concept_graph",
            "exploration_summary",
        },
        label="spine",
    )
    if "book_id" not in data:
        raise ValueError("spine is invalid")
    _bounded_id(data["book_id"])
    if "chapters" in data:
        chapters = data["chapters"]
        if not isinstance(chapters, list) or len(chapters) > _BOOK_WS_MAX_LIST_ITEMS:
            raise ValueError("spine is invalid")
        for chapter in chapters:
            _validate_chapter(chapter)
    for name in {"exploration_summary"}.intersection(data):
        _bounded_string(data[name])
    if "concept_graph" in data:
        _validate_concept_graph(data["concept_graph"])
    if "version" in data and (
        isinstance(data["version"], bool) or not isinstance(data["version"], int)
    ):
        raise ValueError("spine is invalid")
    if "updated_at" in data and (
        isinstance(data["updated_at"], bool) or not isinstance(data["updated_at"], (int, float))
    ):
        raise ValueError("spine is invalid")
    return Spine.model_validate(data)


_BOOK_WS_ALLOWED_FIELDS: dict[str, set[str]] = {
    "create": {
        "type",
        "user_intent",
        "chat_session_id",
        "chat_selections",
        "notebook_refs",
        "knowledge_bases",
        "question_categories",
        "question_entries",
        "language",
    },
    "confirm_proposal": {"type", "book_id", "proposal"},
    "confirm_spine": {"type", "book_id", "spine", "auto_compile"},
    "compile_page": {"type", "book_id", "page_id", "force"},
    "regenerate_block": {"type", "book_id", "page_id", "block_id", "params_override"},
}


def _validate_book_ws_message(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("message is invalid")
    msg_type = value.get("type")
    if not isinstance(msg_type, str) or msg_type not in _BOOK_WS_ALLOWED_FIELDS:
        raise ValueError("message type is invalid")
    if set(value).difference(_BOOK_WS_ALLOWED_FIELDS[msg_type]):
        raise ValueError("message contains unsupported fields")
    result = dict(value)
    if msg_type == "create":
        result["user_intent"] = _bounded_string(
            value.get("user_intent", ""), maximum=_BOOK_WS_MAX_INTENT_CHARS
        )
        if not result["user_intent"].strip():
            raise ValueError("user intent is required")
        result["chat_session_id"] = _bounded_id(value.get("chat_session_id", ""))
        for name, allowed in (
            ("chat_selections", {"session_id", "message_ids"}),
            ("notebook_refs", {"notebook_id", "record_ids"}),
        ):
            values = value.get(name, [])
            if not isinstance(values, list) or len(values) > _BOOK_WS_MAX_LIST_ITEMS:
                raise ValueError(f"{name} is invalid")
            for item in values:
                nested = _strict_mapping(item, allowed=allowed, label=name)
                for field, nested_value in nested.items():
                    if field in {"session_id", "notebook_id"}:
                        _bounded_id(nested_value)
                    else:
                        _bounded_int_list(nested_value)
            result[name] = values
        result["knowledge_bases"] = _bounded_string_list(value.get("knowledge_bases", []))
        result["question_categories"] = _bounded_int_list(value.get("question_categories", []))
        result["question_entries"] = _bounded_int_list(value.get("question_entries", []))
        result["language"] = _bounded_string(value.get("language", "en"), maximum=32)
    elif msg_type == "confirm_proposal":
        result["book_id"] = _bounded_id(value.get("book_id", ""))
        if value.get("proposal") is not None:
            result["proposal"] = _validate_book_proposal(value["proposal"])
    elif msg_type == "confirm_spine":
        result["book_id"] = _bounded_id(value.get("book_id", ""))
        if value.get("spine") is not None:
            result["spine"] = _validate_spine(value["spine"])
        if "auto_compile" in value and not isinstance(value["auto_compile"], bool):
            raise ValueError("auto_compile is invalid")
    else:
        result["book_id"] = _bounded_id(value.get("book_id", ""))
        result["page_id"] = _bounded_id(value.get("page_id", ""))
        if msg_type == "compile_page" and "force" in value and not isinstance(value["force"], bool):
            raise ValueError("force is invalid")
        if msg_type == "regenerate_block":
            result["block_id"] = _bounded_id(value.get("block_id", ""))
            if value.get("params_override") is not None:
                if not isinstance(value["params_override"], dict):
                    raise ValueError("params_override is invalid")
                _validate_dynamic_json(value["params_override"])
                serialized = json.dumps(
                    value["params_override"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                if _utf8_byte_length(serialized) > _BOOK_WS_MAX_DYNAMIC_BYTES:
                    raise ValueError("params_override is too large")
    return result


async def _receive_bounded_book_ws_message(ws: WebSocket, *, timeout_s: float) -> dict[str, Any]:
    from deeptutor.multi_user.context import get_current_user

    leases = AsyncExitStack()
    try:
        user = get_current_user()
        await leases.enter_async_context(await _BOOK_WS_RECEIVE_USER_QUOTA.acquire(user.id))
        await leases.enter_async_context(
            await _BOOK_WS_RECEIVE_GLOBAL_QUOTA.acquire(_BOOK_WS_RECEIVE_GLOBAL_KEY)
        )
        frame = await asyncio.wait_for(ws.receive(), timeout=timeout_s)
        if frame.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(frame.get("code", 1000))
        raw = frame.get("text")
        if not isinstance(raw, str) or _utf8_byte_length(raw) > _BOOK_WS_MAX_FRAME_BYTES:
            raise ValueError("message is too large")
        try:
            decoded = json.loads(raw, object_pairs_hook=_reject_duplicate_json_fields)
        except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as exc:
            raise ValueError("message is invalid") from exc
        return _validate_book_ws_message(decoded)
    finally:
        await leases.aclose()


def _serialize_event(event) -> dict[str, Any]:
    return {
        "type": event.type.value if hasattr(event.type, "value") else str(event.type),
        "source": event.source,
        "stage": event.stage,
        "content": event.content,
        "metadata": event.metadata or {},
    }


@router.websocket("/ws")
async def book_websocket(ws: WebSocket) -> None:
    """Streaming endpoint.

    Client message protocol::

        {"type": "create",          ...CreateBookRequest fields}
        {"type": "confirm_proposal", "book_id": "...", "proposal": {...}}
        {"type": "confirm_spine",    "book_id": "...", "spine": {...}, "auto_compile": true}
        {"type": "compile_page",     "book_id": "...", "page_id": "..."}
        {"type": "regenerate_block", "book_id": "...", "page_id": "...", "block_id": "...", "params_override": {}}
    """
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth, ws_revalidate_auth
    from deeptutor.multi_user.context import get_current_user, reset_current_user

    user_token = await ws_require_auth(ws)
    if user_token is ws_auth_failed:
        return

    # Router dependencies protect HTTP endpoints but do not run for a
    # WebSocket upgrade. Verify the role explicitly at the upgrade and again
    # before each command below so a demotion/revocation takes effect on an
    # already-open socket.
    if not get_current_user().is_admin:
        await ws.close(code=4003)
        reset_current_user(user_token)
        return

    await ws.accept()
    closed = False

    async def send(data: dict[str, Any]) -> None:
        nonlocal closed
        if closed:
            return
        try:
            await ws.send_json(data)
        except Exception:
            closed = True

    async def stream_into_socket(bus: StreamBus) -> asyncio.Task:
        async def _forward() -> None:
            async for event in bus.subscribe():
                if event.source != BOOK_SOURCE:
                    continue
                await send(_serialize_event(event))
                if event.type == StreamEventType.STAGE_END and event.stage in {
                    "ideation",
                    "spine",
                    "compilation",
                }:
                    pass  # keep streaming – multiple stages per task

        return asyncio.create_task(_forward())

    try:
        engine = get_book_engine()
        invalid_messages = 0
        first_frame = True
        while not closed:
            try:
                data = await _receive_bounded_book_ws_message(
                    ws,
                    timeout_s=(
                        _BOOK_WS_FIRST_FRAME_TIMEOUT_S
                        if first_frame
                        else _BOOK_WS_IDLE_FRAME_TIMEOUT_S
                    ),
                )
            except WebSocketDisconnect:
                break
            except asyncio.TimeoutError:
                await send({"type": "error", "content": "Session timed out"})
                await ws.close(code=1008, reason="idle timeout")
                break
            except (QuotaExceeded, ValueError):
                invalid_messages += 1
                await send({"type": "error", "content": "Invalid message"})
                if invalid_messages >= _BOOK_WS_MAX_INVALID_MESSAGES:
                    await ws.close(code=1008, reason="invalid message")
                    break
                continue

            first_frame = False
            if not await ws_revalidate_auth(ws) or not get_current_user().is_admin:
                if not closed:
                    await ws.close(code=4003)
                break
            try:
                user_lease = await _BOOK_WS_ACTION_USER_QUOTA.acquire(get_current_user().id)
                try:
                    global_lease = await _BOOK_WS_ACTION_GLOBAL_QUOTA.acquire(
                        _BOOK_WS_ACTION_GLOBAL_KEY
                    )
                except QuotaExceeded:
                    await user_lease.__aexit__(None, None, None)
                    raise
            except QuotaExceeded:
                await send({"type": "error", "content": "Rate limit exceeded"})
                continue

            msg_type = data["type"]

            bus = StreamBus()
            forward_task = await stream_into_socket(bus)

            try:
                async with user_lease, global_lease:
                    if msg_type == "create":
                        book, proposal = await engine.create_book(
                            user_intent=data["user_intent"],
                            chat_session_id=data["chat_session_id"],
                            chat_selections=data["chat_selections"],
                            notebook_refs=data["notebook_refs"],
                            knowledge_bases=data["knowledge_bases"],
                            question_categories=data["question_categories"],
                            question_entries=data["question_entries"],
                            language=data["language"],
                            stream=bus,
                        )
                        await send(
                            {
                                "type": "create_result",
                                "book": book.model_dump(mode="json"),
                                "proposal": proposal.model_dump(mode="json"),
                            }
                        )

                    elif msg_type == "confirm_proposal":
                        edited = data.get("proposal")
                        book, spine = await engine.confirm_proposal(
                            book_id=data["book_id"],
                            edited_proposal=edited,
                            stream=bus,
                        )
                        await send(
                            {
                                "type": "confirm_proposal_result",
                                "book": book.model_dump(mode="json"),
                                "spine": spine.model_dump(mode="json"),
                            }
                        )

                    elif msg_type == "confirm_spine":
                        edited_spine = data.get("spine")
                        pages = await engine.confirm_spine(
                            book_id=data["book_id"],
                            edited_spine=edited_spine,
                            auto_compile=data.get("auto_compile", True),
                            stream=bus,
                        )
                        await send(
                            {
                                "type": "confirm_spine_result",
                                "pages": [p.model_dump(mode="json") for p in pages],
                            }
                        )

                    elif msg_type == "compile_page":
                        page = await engine.compile_page(
                            book_id=data["book_id"],
                            page_id=data["page_id"],
                            stream=bus,
                            force=data.get("force", False),
                        )
                        await send(
                            {
                                "type": "compile_page_result",
                                "page": page.model_dump(mode="json"),
                            }
                        )

                    else:  # regenerate_block — closed schema validated above.
                        block = await engine.regenerate_block(
                            book_id=data["book_id"],
                            page_id=data["page_id"],
                            block_id=data["block_id"],
                            params_override=data.get("params_override"),
                            stream=bus,
                        )
                        await send(
                            {
                                "type": "regenerate_block_result",
                                "block": block.model_dump(mode="json") if block else None,
                            }
                        )

            except Exception as exc:
                logger.error(f"book ws action {msg_type} failed: {exc}", exc_info=True)
                await send({"type": "error", "content": str(exc)})
            finally:
                await bus.close()
                forward_task.cancel()
                try:
                    await forward_task
                except (asyncio.CancelledError, Exception):
                    pass

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"Book WS connection error: {exc}", exc_info=True)
    finally:
        closed = True
        try:
            await ws.close()
        except Exception:
            pass
        if user_token is not None:
            try:
                reset_current_user(user_token)
            except Exception:
                pass
