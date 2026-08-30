"""
Question Notebook API — persists quiz questions, bookmarks, and categories.
"""

from __future__ import annotations

import logging
import uuid as _uuid

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from deeptutor.services.session import get_sqlite_session_store
from deeptutor.services.storage import get_attachment_store
from deeptutor.services.storage.attachment_validation import (
    AttachmentValidationError,
    validate_attachment_id,
    validate_notebook_answer_images,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Models ────────────────────────────────────────────────────────


class AnswerImageItem(BaseModel):
    """Persisted reference to one image attached to a learner's answer.

    The bytes live in the AttachmentStore at ``url``; we never round-trip
    base64 back to the client so notebook lookups stay cheap.
    """

    id: str = ""
    url: str = ""
    filename: str = ""
    mime_type: str = ""


class NotebookEntryItem(BaseModel):
    id: int
    session_id: str
    session_title: str = ""
    turn_id: str = ""
    question_id: str = ""
    question: str
    question_type: str = ""
    options: dict[str, str] = {}
    correct_answer: str = ""
    explanation: str = ""
    difficulty: str = ""
    user_answer: str = ""
    user_answer_images: list[AnswerImageItem] = []
    is_correct: bool = False
    bookmarked: bool = False
    followup_session_id: str = ""
    ai_judgment: str = ""
    created_at: float
    updated_at: float
    categories: list[CategoryItem] | None = None


class NotebookEntryListResponse(BaseModel):
    items: list[NotebookEntryItem]
    total: int


class EntryUpdateRequest(BaseModel):
    bookmarked: bool | None = None
    followup_session_id: str | None = None
    ai_judgment: str | None = None


class CategoryItem(BaseModel):
    id: int
    name: str
    created_at: float = 0
    entry_count: int = 0


class CategoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class CategoryRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class CategoryAddRequest(BaseModel):
    category_id: int


class AnswerImageUpload(BaseModel):
    """One image attached to the learner's answer.

    Either ``base64`` (new upload) or ``url`` (re-submit of an already
    persisted image) must be set. ``id`` is preserved when the client
    sends one so the same logical image keeps a stable AttachmentStore
    record across resubmissions.
    """

    id: str = ""
    base64: str = ""
    url: str = ""
    filename: str = "answer.png"
    mime_type: str = "image/png"


class UpsertEntryRequest(BaseModel):
    session_id: str
    turn_id: str = ""
    question_id: str
    question: str
    question_type: str = ""
    options: dict[str, str] | None = None
    correct_answer: str = ""
    explanation: str = ""
    difficulty: str = ""
    user_answer: str = ""
    # Optional: list of images attached as part of the learner's answer.
    # ``None`` means "don't touch any previously-stored images on update";
    # an empty list explicitly clears them.
    user_answer_images: list[AnswerImageUpload] | None = Field(default=None, max_length=5)
    is_correct: bool = False


# ── Entry endpoints ──────────────────────────────────────────────


async def _persist_answer_images(
    session_id: str,
    images: list[AnswerImageUpload] | None,
    *,
    existing_images: list[dict],
) -> tuple[list[dict[str, str]] | None, list[str]]:
    """Materialise base64 image uploads into the AttachmentStore.

    Returns a list of ``{id, url, filename, mime_type}`` records suitable
    for ``notebook_entries.user_answer_images_json``. ``None`` is returned
    when ``images`` is ``None`` (no change to existing stored images).
    All images are validated before the first write. Existing URLs are only
    reusable when they already belong to this notebook entry, preventing a
    caller from attaching another message's file by guessing its URL.
    """
    if images is None:
        return None, []

    attachment_store = get_attachment_store()
    records: list[dict[str, str]] = []
    created_ids: list[str] = []
    reusable = {
        str(record.get("id") or ""): record
        for record in existing_images
        if str(record.get("id") or "")
    }
    new_images: list[dict] = []
    for image in images:
        url = (image.url or "").strip()
        if not url:
            new_images.append(image.model_dump())
            continue
        if image.base64:
            raise AttachmentValidationError("answer images cannot include both URL and base64 data")
        record_id = validate_attachment_id(image.id, label="answer image")
        existing = reusable.get(record_id)
        if not existing or str(existing.get("url") or "") != url:
            raise AttachmentValidationError("answer image URL is not owned by this notebook entry")
        records.append(
            {
                "id": record_id,
                "url": url,
                "filename": str(existing.get("filename") or ""),
                "mime_type": str(existing.get("mime_type") or ""),
            }
        )

    for image in validate_notebook_answer_images(new_images):
        # New uploads always receive a server-generated identifier so callers
        # cannot overwrite a sibling attachment through a chosen id.
        record_id = _uuid.uuid4().hex[:12]
        filename = (str(image.get("filename") or "answer.png")).strip() or "answer.png"
        mime_type = (str(image.get("mime_type") or "image/png")).strip() or "image/png"
        try:
            url = await attachment_store.put(
                session_id=session_id,
                attachment_id=record_id,
                filename=filename,
                data=image["_raw_bytes"],
                mime_type=mime_type,
            )
            created_ids.append(record_id)
        except Exception as exc:
            for attachment_id in [*created_ids, record_id]:
                try:
                    await attachment_store.delete_attachment(session_id, attachment_id)
                except Exception:
                    logger.exception("failed to clean up answer image %s", attachment_id)
            raise RuntimeError(f"failed to persist answer image {filename!r}") from exc
        records.append({"id": record_id, "url": url, "filename": filename, "mime_type": mime_type})
    return records, created_ids


@router.post("/entries/upsert")
async def upsert_single_entry(payload: UpsertEntryRequest):
    store = get_sqlite_session_store()
    session = await store.get_session(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    existing = await store.find_notebook_entry(
        payload.session_id, payload.question_id, turn_id=payload.turn_id
    )
    try:
        images_records, created_ids = await _persist_answer_images(
            payload.session_id,
            payload.user_answer_images,
            existing_images=list((existing or {}).get("user_answer_images") or []),
        )
    except AttachmentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail="Could not save answer images") from exc
    item = payload.model_dump()
    # The store expects ``user_answer_images`` as a plain list of dicts
    # (or absent to mean "leave the stored images alone"). Strip the
    # upload payload version and replace with the persisted records.
    item.pop("user_answer_images", None)
    if images_records is not None:
        item["user_answer_images"] = images_records
    try:
        await store.upsert_notebook_entries(payload.session_id, [item])
    except ValueError as e:
        await _cleanup_answer_images(payload.session_id, created_ids)
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as exc:
        await _cleanup_answer_images(payload.session_id, created_ids)
        logger.exception("question notebook upsert failed")
        raise HTTPException(status_code=500, detail="Could not save notebook entry") from exc
    entry = await store.find_notebook_entry(
        payload.session_id, payload.question_id, turn_id=payload.turn_id
    )
    if entry is None:
        await _cleanup_answer_images(payload.session_id, created_ids)
        raise HTTPException(status_code=500, detail="Upsert failed")
    if images_records is not None:
        retained_ids = {str(record.get("id") or "") for record in images_records}
        stale_ids = [
            str(record.get("id") or "")
            for record in (existing or {}).get("user_answer_images") or []
            if str(record.get("id") or "") not in retained_ids
        ]
        await _cleanup_answer_images(payload.session_id, stale_ids)
    return entry


async def _cleanup_answer_images(session_id: str, attachment_ids: list[str]) -> None:
    attachment_store = get_attachment_store()
    for attachment_id in attachment_ids:
        try:
            await attachment_store.delete_attachment(session_id, attachment_id)
        except Exception:
            logger.exception("failed to clean up answer image %s", attachment_id)


@router.get("/entries", response_model=NotebookEntryListResponse)
async def list_entries(
    category_id: int | None = Query(default=None),
    bookmarked: bool | None = Query(default=None),
    is_correct: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> NotebookEntryListResponse:
    store = get_sqlite_session_store()
    result = await store.list_notebook_entries(
        category_id=category_id,
        bookmarked=bookmarked,
        is_correct=is_correct,
        limit=limit,
        offset=offset,
    )
    return NotebookEntryListResponse(
        items=[NotebookEntryItem(**item) for item in result["items"]],
        total=result["total"],
    )


@router.get("/entries/lookup/by-question")
async def lookup_entry(
    session_id: str = Query(...),
    question_id: str = Query(...),
    turn_id: str | None = Query(default=None),
    missing_ok: bool = Query(
        default=False,
        description="Return 204 No Content instead of 404 when the entry is "
        "absent — used by the quiz viewer to probe not-yet-saved questions "
        "without logging noisy 404s.",
    ),
):
    store = get_sqlite_session_store()
    entry = await store.find_notebook_entry(session_id, question_id, turn_id=turn_id)
    if entry is None:
        if missing_ok:
            return Response(status_code=204)
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.get("/entries/{entry_id}", response_model=NotebookEntryItem)
async def get_entry(entry_id: int) -> NotebookEntryItem:
    store = get_sqlite_session_store()
    entry = await store.get_notebook_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return NotebookEntryItem(**entry)


@router.patch("/entries/{entry_id}")
async def update_entry(entry_id: int, payload: EntryUpdateRequest):
    store = get_sqlite_session_store()
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = await store.update_notebook_entry(entry_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"updated": True, "id": entry_id}


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: int):
    store = get_sqlite_session_store()
    entry = await store.get_notebook_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    deleted = await store.delete_notebook_entry(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found")
    await _cleanup_answer_images(
        str(entry.get("session_id") or ""),
        [
            str(record.get("id") or "")
            for record in entry.get("user_answer_images") or []
            if str(record.get("id") or "")
        ],
    )
    return {"deleted": True, "id": entry_id}


# ── Entry ↔ Category linking ────────────────────────────────────


@router.post("/entries/{entry_id}/categories")
async def add_entry_to_category(entry_id: int, payload: CategoryAddRequest):
    store = get_sqlite_session_store()
    entry = await store.get_notebook_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    ok = await store.add_entry_to_category(entry_id, payload.category_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to add to category")
    return {"added": True, "entry_id": entry_id, "category_id": payload.category_id}


@router.delete("/entries/{entry_id}/categories/{category_id}")
async def remove_entry_from_category(entry_id: int, category_id: int):
    store = get_sqlite_session_store()
    removed = await store.remove_entry_from_category(entry_id, category_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"removed": True, "entry_id": entry_id, "category_id": category_id}


# ── Category CRUD ────────────────────────────────────────────────


@router.get("/categories", response_model=list[CategoryItem])
async def list_categories():
    store = get_sqlite_session_store()
    return await store.list_categories()


@router.post("/categories", response_model=CategoryItem, status_code=201)
async def create_category(payload: CategoryCreateRequest):
    store = get_sqlite_session_store()
    try:
        return await store.create_category(payload.name)
    except Exception:
        raise HTTPException(status_code=409, detail="Category name already exists")


@router.patch("/categories/{category_id}")
async def rename_category(category_id: int, payload: CategoryRenameRequest):
    store = get_sqlite_session_store()
    updated = await store.rename_category(category_id, payload.name)
    if not updated:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"updated": True, "id": category_id, "name": payload.name}


@router.delete("/categories/{category_id}")
async def delete_category(category_id: int):
    store = get_sqlite_session_store()
    deleted = await store.delete_category(category_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"deleted": True, "id": category_id}
