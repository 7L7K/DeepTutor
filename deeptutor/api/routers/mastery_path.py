"""Guided Learning API Router."""

from __future__ import annotations

import html
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from pydantic import ValidationError as PydanticValidationError

from deeptutor.learning import policy as learning_policy
from deeptutor.learning import prompts as learning_prompts
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
)
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.services.llm.notebook_admission import (
    NotebookLLMAdmissionError,
    QuotaExceeded,
    admitted_notebook_llm_call,
)
from deeptutor.services.notebook import get_notebook_manager
from deeptutor.services.settings.interface_settings import get_ui_language
from deeptutor.utils.json_parser import parse_json_response

router = APIRouter()


def get_learning_service() -> LearningService:
    # Create a fresh store + service per request to avoid object-level race conditions.
    store = LearningStore()
    return LearningService(store)


def _validate_book_id(book_id: str) -> None:
    """Reject empty or path-traversal-bearing book ids (shared by all endpoints)."""
    if (
        not book_id
        or len(book_id) > 100
        or ".." in book_id
        or "/" in book_id
        or "\\" in book_id
        or ":" in book_id
        or any(ord(char) < 0x20 for char in book_id)
    ):
        raise HTTPException(status_code=400, detail="Invalid book_id")
    if book_id.startswith("lp_crs_"):
        raise HTTPException(status_code=404, detail="Learning path not found")


def _parse_modules(body_modules: list[dict]) -> list[LearningModule]:
    """Parse raw module dicts into LearningModule objects (shared by init/replace)."""
    modules: list[LearningModule] = []
    for i, m in enumerate(body_modules):
        kps_data = m.get("knowledge_points", [])
        try:
            kps = [KnowledgePoint(**kp) for kp in kps_data]
        except PydanticValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid knowledge_point data in modules[{i}]: {exc.errors()}",
            ) from exc
        # Remove knowledge_points from m to avoid duplicate argument to LearningModule.
        m_clean = {k: v for k, v in m.items() if k != "knowledge_points"}
        try:
            modules.append(LearningModule(knowledge_points=kps, **m_clean))
        except PydanticValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid module data in modules[{i}]: {exc.errors()}",
            ) from exc
    return modules


def _validate_runnable_modules(modules: list[LearningModule], *, status_code: int = 400) -> None:
    if not modules:
        raise HTTPException(
            status_code=status_code, detail="At least one learning module is required"
        )
    for mod in modules:
        if not mod.knowledge_points:
            raise HTTPException(
                status_code=status_code,
                detail=f"Module {mod.id!r} must contain at least one knowledge point",
            )


async def _cancel_active_learning_turn(session_id: str | None) -> None:
    """Cancel by persisted chat-session identity, never by learning-path identity."""
    if not session_id:
        return
    from deeptutor.services.session import get_turn_runtime_manager

    runtime = get_turn_runtime_manager()
    session = await runtime.store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    active_turn = await runtime.store.get_active_turn(session_id)
    if active_turn:
        await runtime.cancel_turn(active_turn["id"])


# ── Request models ───────────────────────────────────────────────────────────


class InitModulesRequest(BaseModel):
    modules: list[dict] = Field(..., max_length=100)  # list of LearningModule-compatible dicts
    session_id: str | None = Field(default=None, max_length=100)

    @field_validator("modules")
    @classmethod
    def module_payload_is_bounded(cls, value: list[dict]) -> list[dict]:
        # The ASGI middleware caps the raw envelope; this count check keeps a
        # small body full of empty objects from expanding into a large parse.
        for module in value:
            if not isinstance(module, dict):
                raise ValueError("modules must contain objects")
            knowledge_points = module.get("knowledge_points", [])
            if not isinstance(knowledge_points, list) or len(knowledge_points) > 100:
                raise ValueError("each module may contain at most 100 knowledge points")
        return value


class ChapterImport(BaseModel):
    title: str = Field(..., max_length=300)
    knowledge_points: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("knowledge_points")
    @classmethod
    def knowledge_point_names_are_bounded(cls, value: list[str]) -> list[str]:
        if any(len(name) > 500 for name in value):
            raise ValueError("knowledge point names must be at most 500 characters")
        return value


class ImportFromBookRequest(BaseModel):
    chapters: list[ChapterImport] = Field(..., max_length=100)
    session_id: str | None = Field(default=None, max_length=100)


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/progress")
async def list_all_progress():
    service = get_learning_service()
    result = service.list_progress()
    result["summaries"] = [
        item
        for item in result.get("summaries", [])
        if not str(item.get("book_id") or "").startswith("lp_crs_")
    ]
    return result


@router.get("/progress/{book_id}")
async def get_progress(book_id: str):
    _validate_book_id(book_id)
    service = get_learning_service()
    progress = service.get_or_create(book_id)
    return progress.model_dump()


@router.get("/progress/{book_id}/map")
async def get_progress_map(book_id: str):
    """The dashboard view of a path: the gate-decided next step plus a map of
    every objective's status (new / learning / mastered). The per-type gate
    lives in ``learning.policy`` so the dashboard and the tutor agree."""
    _validate_book_id(book_id)
    service = get_learning_service()
    progress = service.get_or_create(book_id)
    return {
        "book_id": book_id,
        "next": learning_policy.next_objective(progress).to_dict(),
        "map": learning_policy.map_summary(progress),
    }


@router.post("/progress/{book_id}/init-modules")
async def init_modules(book_id: str, body: InitModulesRequest):
    _validate_book_id(book_id)
    modules = _parse_modules(body.modules)
    _validate_runnable_modules(modules)
    await _cancel_active_learning_turn(body.session_id)
    service = get_learning_service()
    progress = service.get_or_create(book_id)
    service.init_modules(progress, modules)
    progress.current_module_id = modules[0].id
    progress.current_kp_index = 0
    service.save(progress)
    return {"status": "ok", "module_count": len(modules)}


@router.post("/progress/{book_id}/import-from-book")
async def import_from_book(book_id: str, body: ImportFromBookRequest):
    _validate_book_id(book_id)
    modules = []
    for i, ch in enumerate(body.chapters):
        kps = [
            KnowledgePoint(
                id=f"{book_id}_ch{i}_kp{j}",
                name=kp_name,
                type=KnowledgeType("concept"),
                module_id=f"{book_id}_ch{i}",
            )
            for j, kp_name in enumerate(ch.knowledge_points)
        ]
        modules.append(
            LearningModule(
                id=f"{book_id}_ch{i}",
                name=ch.title or f"Chapter {i + 1}",
                order=i,
                pass_threshold=0.7,
                knowledge_points=kps,
            )
        )
    _validate_runnable_modules(modules)
    await _cancel_active_learning_turn(body.session_id)
    service = get_learning_service()
    progress = service.get_or_create(book_id)
    service.init_modules(progress, modules)
    progress.current_module_id = modules[0].id
    progress.current_kp_index = 0
    service.save(progress)
    return {"status": "ok", "module_count": len(modules)}


@router.delete("/progress/{book_id}")
async def delete_progress(book_id: str):
    _validate_book_id(book_id)
    store = LearningStore()
    if not store.exists(book_id):
        raise HTTPException(status_code=404, detail="Progress not found")
    store.delete(book_id)
    return {"status": "ok"}


@router.post("/progress/{book_id}/redo")
async def redo_progress(book_id: str, session_id: str | None = None):
    _validate_book_id(book_id)
    await _cancel_active_learning_turn(session_id)
    store = LearningStore()
    progress = store.load(book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    LearningService(store).reset_progress(progress)
    return {"status": "ok"}


class NotebookRecordInput(BaseModel):
    id: str = Field(max_length=100)
    type: str = Field(default="note", max_length=50)
    title: str = Field(default="", max_length=300)
    output: str = Field(default="", max_length=6_000)


class GenerateFromNotebookRequest(BaseModel):
    notebook_id: str = Field(min_length=1, max_length=100)
    records: list[NotebookRecordInput] = Field(max_length=12)
    session_id: str | None = Field(default=None, max_length=100)


@router.post("/progress/{book_id}/generate-from-notebook")
async def generate_from_notebook(book_id: str, body: GenerateFromNotebookRequest):
    _validate_book_id(book_id)
    if not body.records:
        raise HTTPException(status_code=400, detail="No records provided")

    try:
        from deeptutor.services.llm import complete

        async with admitted_notebook_llm_call():
            # The request identifies saved notebook records; it must not
            # supply the material that is sent to the model. Resolve those
            # records from the current user's notebook workspace, which also
            # fails closed for missing or cross-workspace records.
            record_ids = [record.id for record in body.records]
            if len(set(record_ids)) != len(record_ids):
                raise HTTPException(status_code=400, detail="Duplicate record ids are not allowed")
            manager = get_notebook_manager()
            if manager.get_notebook(body.notebook_id) is None:
                raise HTTPException(status_code=404, detail="Notebook not found")
            stored_records = manager.get_records(body.notebook_id, record_ids)
            stored_by_id = {str(record.get("id") or ""): record for record in stored_records}
            if any(record_id not in stored_by_id for record_id in record_ids):
                raise HTTPException(status_code=404, detail="Notebook record not found")

            records_data = [
                {
                    "type": html.escape(
                        str(stored_by_id[record_id].get("type") or "note")[:50], quote=False
                    ),
                    "title": html.escape(
                        str(stored_by_id[record_id].get("title") or "")[:200], quote=False
                    ),
                    "output": html.escape(
                        str(stored_by_id[record_id].get("output") or "")[:500], quote=False
                    ),
                }
                for record_id in record_ids
            ]
            records_json = json.dumps(records_data, ensure_ascii=False)
            language = get_ui_language()
            system_prompt, prompt = learning_prompts.notebook_generation_prompts(
                language, records_json
            )
            response = await complete(prompt=prompt, system_prompt=system_prompt)
    except NotebookLLMAdmissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail="Notebook LLM request limit reached.") from exc
    # LLMs commonly fence/slightly-malform JSON; use the shared fence-stripping
    # repair parser instead of bare json.loads so the common case isn't a 502.
    data = parse_json_response(response, fallback=None)
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON")

    modules_raw = data.get("modules", [])
    if not isinstance(modules_raw, list):
        raise HTTPException(
            status_code=502, detail="LLM returned invalid structure: modules is not a list"
        )
    _ALLOWED_KP_TYPES = {"memory", "concept", "procedure", "design"}
    modules = []
    for i, m in enumerate(modules_raw[:12]):
        if not isinstance(m, dict) or "name" not in m:
            continue
        fallback_name = learning_prompts.default_module_name(language, i + 1)
        module_name = str(m.get("name") or fallback_name).strip()[:200] or fallback_name
        kps = []
        raw_knowledge_points = m.get("knowledge_points", [])
        if not isinstance(raw_knowledge_points, list):
            continue
        for j, kp in enumerate(raw_knowledge_points[:12]):
            if not isinstance(kp, dict) or "name" not in kp:
                continue
            kp_name = str(kp["name"]).strip()[:200]
            if len(kp_name) < 2:
                continue
            kp_type = str(kp.get("type", "concept")).strip()
            if kp_type not in _ALLOWED_KP_TYPES:
                kp_type = "concept"
            kps.append(
                KnowledgePoint(
                    id=f"{book_id}_nb{i}_kp{j}",
                    name=kp_name,
                    type=KnowledgeType(kp_type),
                    module_id=f"{book_id}_nb{i}",
                )
            )
        modules.append(
            LearningModule(
                id=f"{book_id}_nb{i}",
                name=module_name,
                order=i,
                pass_threshold=0.7,
                knowledge_points=kps,
            )
        )
    _validate_runnable_modules(modules, status_code=502)
    await _cancel_active_learning_turn(body.session_id)
    service = get_learning_service()
    progress = service.get_or_create(book_id)
    service.init_modules(progress, modules)
    progress.current_module_id = modules[0].id
    progress.current_kp_index = 0
    service.save(progress)
    return {
        "status": "ok",
        "module_count": len(modules),
        "modules": [m.model_dump() for m in modules],
    }
