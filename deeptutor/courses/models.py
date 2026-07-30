"""Stable Phase 2 course and source records."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CourseState = Literal["active", "archived"]
CourseWorkspaceKind = Literal["academic_course", "general_study"]
SourceState = Literal["processing", "ready", "failed", "archived"]


class Course(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    owner_user_id: str
    title: str
    workspace_kind: CourseWorkspaceKind = "academic_course"
    state: CourseState = "active"
    revision: int = 1
    write_epoch: int = 1
    managed_kb_ref: str | None = None
    created_at: float
    updated_at: float
    archived_at: float | None = None

    @property
    def learning_path_id(self) -> str:
        return f"lp_{self.id}"


class CourseSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    course_id: str
    kind: str
    display_name: str
    state: SourceState = "processing"
    manifest: list[dict[str, Any]] = Field(default_factory=list)
    content_sha256: str
    revision: int = 1
    operation_id: str | None = None
    idempotency_key: str | None = None
    supersedes_source_id: str | None = None
    created_at: float
    updated_at: float
