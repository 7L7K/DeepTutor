"""
Notebook API Router
Provides notebook creation, querying, updating, deletion, and record management functions
"""

import json
from typing import AsyncGenerator, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from deeptutor.agents.notebook import NotebookSummarizeAgent
from deeptutor.services.llm import clean_thinking_tags
from deeptutor.services.llm.notebook_admission import (
    NotebookLLMAdmissionError,
    QuotaExceeded,
    admitted_notebook_llm_call,
)
from deeptutor.services.notebook import notebook_manager

router = APIRouter()


# === Request/Response Models ===


class CreateNotebookRequest(BaseModel):
    """Create notebook request"""

    name: str = Field(..., max_length=200)
    description: str = Field(default="", max_length=4_000)
    color: str = Field(default="#3B82F6", max_length=32)
    icon: str = Field(default="book", max_length=64)


class UpdateNotebookRequest(BaseModel):
    """Update notebook request"""

    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    color: str | None = Field(default=None, max_length=32)
    icon: str | None = Field(default=None, max_length=64)


class AddRecordRequest(BaseModel):
    """Add record request"""

    notebook_ids: list[str] = Field(max_length=20)
    record_type: Literal["solve", "question", "research", "chat", "co_writer", "tutorbot"]
    title: str = Field(max_length=500)
    summary: str = Field(default="", max_length=4_000)
    user_query: str = Field(max_length=12_000)
    output: str = Field(max_length=24_000)
    metadata: dict = Field(default_factory=dict)
    kb_name: str | None = Field(default=None, max_length=500)

    @field_validator("metadata")
    @classmethod
    def metadata_is_bounded(cls, value: dict) -> dict:
        if len(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) > 8_000:
            raise ValueError("metadata is too large")
        return value


class RemoveRecordRequest(BaseModel):
    """Remove record request"""

    record_id: str = Field(..., max_length=100)


class UpdateRecordRequest(BaseModel):
    """Update an existing notebook record."""

    title: str | None = Field(default=None, max_length=500)
    summary: str | None = Field(default=None, max_length=4_000)
    user_query: str | None = Field(default=None, max_length=12_000)
    output: str | None = Field(default=None, max_length=24_000)
    metadata: dict | None = None
    kb_name: str | None = Field(default=None, max_length=500)

    @field_validator("metadata")
    @classmethod
    def metadata_is_bounded(cls, value: dict | None) -> dict | None:
        if (
            value is not None
            and len(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) > 8_000
        ):
            raise ValueError("metadata is too large")
        return value


# === API Endpoints ===


async def _build_record_summary(request: AddRecordRequest) -> str:
    if request.summary.strip():
        return clean_thinking_tags(request.summary).strip()
    async with admitted_notebook_llm_call():
        agent = NotebookSummarizeAgent(language=str(request.metadata.get("ui_language", "en")))
        return clean_thinking_tags(
            await agent.summarize(
                title=request.title,
                record_type=request.record_type,
                user_query=request.user_query,
                output=request.output,
                metadata=request.metadata,
            )
        ).strip()


async def _stream_add_record_with_summary(
    request: AddRecordRequest,
) -> AsyncGenerator[str, None]:
    try:
        summary_parts: list[str] = []
        if request.summary.strip():
            summary = clean_thinking_tags(request.summary).strip()
            summary_parts.append(summary)
            if summary:
                yield f"data: {json.dumps({'type': 'summary_chunk', 'content': summary}, ensure_ascii=False)}\n\n"
        else:
            async with admitted_notebook_llm_call():
                agent = NotebookSummarizeAgent(
                    language=str(request.metadata.get("ui_language", "en"))
                )
                async for chunk in agent.stream_summary(
                    title=request.title,
                    record_type=request.record_type,
                    user_query=request.user_query,
                    output=request.output,
                    metadata=request.metadata,
                ):
                    if not chunk:
                        continue
                    summary_parts.append(chunk)

            summary = clean_thinking_tags("".join(summary_parts)).strip()
            if summary:
                yield f"data: {json.dumps({'type': 'summary_chunk', 'content': summary}, ensure_ascii=False)}\n\n"

        summary = clean_thinking_tags("".join(summary_parts)).strip()
        result = notebook_manager.add_record(
            notebook_ids=request.notebook_ids,
            record_type=request.record_type,
            title=request.title,
            summary=summary,
            user_query=request.user_query,
            output=request.output,
            metadata=request.metadata,
            kb_name=request.kb_name,
        )
        payload = {
            "type": "result",
            "success": True,
            "summary": summary,
            "record": result["record"],
            "added_to_notebooks": result["added_to_notebooks"],
        }
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    except Exception as exc:
        payload = {"type": "error", "detail": str(exc)}
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/list")
async def list_notebooks():
    """
    Get all notebook list

    Returns:
        Notebook list (includes summary information)
    """
    try:
        notebooks = notebook_manager.list_notebooks()
        return {"notebooks": notebooks, "total": len(notebooks)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics")
async def get_statistics():
    """
    Get notebook statistics

    Returns:
        Statistics information
    """
    try:
        stats = notebook_manager.get_statistics()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create")
async def create_notebook(request: CreateNotebookRequest):
    """
    Create new notebook

    Args:
        request: Create request

    Returns:
        Created notebook information
    """
    try:
        notebook = notebook_manager.create_notebook(
            name=request.name,
            description=request.description,
            color=request.color,
            icon=request.icon,
        )
        return {"success": True, "notebook": notebook}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notebook_id}")
async def get_notebook(notebook_id: str):
    """
    Get notebook details

    Args:
        notebook_id: Notebook ID

    Returns:
        Notebook details (includes all records)
    """
    try:
        notebook = notebook_manager.get_notebook(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return notebook
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{notebook_id}")
async def update_notebook(notebook_id: str, request: UpdateNotebookRequest):
    """
    Update notebook information

    Args:
        notebook_id: Notebook ID
        request: Update request

    Returns:
        Updated notebook information
    """
    try:
        notebook = notebook_manager.update_notebook(
            notebook_id=notebook_id,
            name=request.name,
            description=request.description,
            color=request.color,
            icon=request.icon,
        )
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return {"success": True, "notebook": notebook}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{notebook_id}")
async def delete_notebook(notebook_id: str):
    """
    Delete notebook

    Args:
        notebook_id: Notebook ID

    Returns:
        Deletion result
    """
    try:
        success = notebook_manager.delete_notebook(notebook_id)
        if not success:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return {"success": True, "message": "Notebook deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/add_record")
async def add_record(request: AddRecordRequest):
    """
    Add record to notebook

    Args:
        request: Add record request

    Returns:
        Addition result
    """
    try:
        summary = await _build_record_summary(request)
        result = notebook_manager.add_record(
            notebook_ids=request.notebook_ids,
            record_type=request.record_type,
            title=request.title,
            summary=summary,
            user_query=request.user_query,
            output=request.output,
            metadata=request.metadata,
            kb_name=request.kb_name,
        )
        return {
            "success": True,
            "summary": summary,
            "record": result["record"],
            "added_to_notebooks": result["added_to_notebooks"],
        }
    except NotebookLLMAdmissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail="Notebook LLM request limit reached.") from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/add_record_with_summary")
async def add_record_with_summary(request: AddRecordRequest):
    """Add record to notebook and stream generated summary."""
    return StreamingResponse(
        _stream_add_record_with_summary(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/{notebook_id}/records/{record_id}")
async def remove_record(notebook_id: str, record_id: str):
    """
    Remove record from notebook

    Args:
        notebook_id: Notebook ID
        record_id: Record ID

    Returns:
        Deletion result
    """
    try:
        success = notebook_manager.remove_record(notebook_id, record_id)
        if not success:
            raise HTTPException(status_code=404, detail="Record not found")
        return {"success": True, "message": "Record removed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{notebook_id}/records/{record_id}")
async def update_record(notebook_id: str, record_id: str, request: UpdateRecordRequest):
    """Update an existing notebook record in place."""
    try:
        updated = notebook_manager.update_record(
            notebook_id=notebook_id,
            record_id=record_id,
            title=request.title,
            summary=request.summary,
            user_query=request.user_query,
            output=request.output,
            metadata=request.metadata,
            kb_name=request.kb_name,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Record not found")
        return {"success": True, "record": updated}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check"""
    return {"status": "healthy", "service": "notebook"}
