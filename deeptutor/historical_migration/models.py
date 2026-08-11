"""Public, privacy-safe models for historical migration dry runs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Classification = Literal["importable", "ambiguous", "orphaned", "duplicate", "rejected"]


class LegacyOwnerSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    designation: str
    session_count: int = 0
    practice_attempt_count: int = 0
    flashcard_deck_count: int = 0


class HistoricalSourceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    size_bytes: int
    modified_at: float
    database_sha256: str
    schema_fingerprint: str
    compatible: bool
    issue_code: str | None = None
    owners: list[LegacyOwnerSummary] = Field(default_factory=list)


class ClassificationCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    importable: int = 0
    ambiguous: int = 0
    orphaned: int = 0
    duplicate: int = 0
    rejected: int = 0


class TableClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str
    total: int
    counts: ClassificationCount
    reason_codes: dict[str, int] = Field(default_factory=dict)


class DryRunDestinations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessions: Literal["course_less_archive"] = "course_less_archive"
    practice_course_id: str | None = None
    flashcard_workspace_id: str | None = None
    mastery: Literal["archive_only"] = "archive_only"


class HistoricalMigrationDryRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: str
    source_id: str
    source_database_sha256: str
    source_schema_fingerprint: str
    target_owner_designation: str
    legacy_owner_designation: str
    destinations: DryRunDestinations
    classifications: list[TableClassification]
    totals: ClassificationCount
    required_decisions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    zero_write: Literal[True] = True
    manifest_sha256: str


class HistoricalMigrationDryRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=5, max_length=80)
    legacy_owner_designation: str = Field(min_length=8, max_length=80)
    practice_course_id: str | None = Field(default=None, min_length=5, max_length=80)
    flashcard_workspace_id: str | None = Field(default=None, min_length=5, max_length=80)


__all__ = [
    "Classification",
    "ClassificationCount",
    "DryRunDestinations",
    "HistoricalMigrationDryRun",
    "HistoricalMigrationDryRunRequest",
    "HistoricalSourceSummary",
    "LegacyOwnerSummary",
    "TableClassification",
]
