"""Authenticated zero-write historical learner-data migration API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from deeptutor.courses.repository import CourseNotFoundError
from deeptutor.courses.service import CourseUnavailableError, get_current_course_service
from deeptutor.historical_migration import (
    HistoricalMigrationError,
    HistoricalMigrationScanner,
    HistoricalSourceNotFoundError,
)
from deeptutor.historical_migration.models import (
    DryRunDestinations,
    HistoricalMigrationDryRun,
    HistoricalMigrationDryRunRequest,
    HistoricalSourceSummary,
)
from deeptutor.multi_user.context import get_current_user_or_none

router = APIRouter()


def _scanner() -> HistoricalMigrationScanner:
    return HistoricalMigrationScanner()


@router.get("/sources", response_model=list[HistoricalSourceSummary])
def list_historical_sources() -> list[HistoricalSourceSummary]:
    try:
        return _scanner().list_sources()
    except HistoricalMigrationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _validate_destinations(request: HistoricalMigrationDryRunRequest) -> DryRunDestinations:
    try:
        service = get_current_course_service()
        if request.practice_course_id:
            course = service.get(request.practice_course_id)
            if course.workspace_kind != "academic_course" or course.state != "active":
                raise HTTPException(
                    status_code=409,
                    detail="Historical Practice requires an active academic Course",
                )
        if request.flashcard_workspace_id:
            workspace = service.get(request.flashcard_workspace_id)
            if workspace.state != "active":
                raise HTTPException(
                    status_code=409,
                    detail="Historical Flashcards require an active destination",
                )
    except CourseNotFoundError as exc:
        # The same response for missing and foreign resources preserves the
        # private Course ownership boundary.
        raise HTTPException(status_code=404, detail="Destination not found") from exc
    except CourseUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DryRunDestinations(
        practice_course_id=request.practice_course_id,
        flashcard_workspace_id=request.flashcard_workspace_id,
    )


@router.post("/dry-run", response_model=HistoricalMigrationDryRun)
def create_historical_dry_run(
    request: HistoricalMigrationDryRunRequest,
) -> HistoricalMigrationDryRun:
    user = get_current_user_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Authenticated user context is required")
    destinations = _validate_destinations(request)
    try:
        return _scanner().dry_run(
            source_id=request.source_id,
            legacy_owner_designation=request.legacy_owner_designation,
            target_owner_id=user.id,
            destinations=destinations,
        )
    except HistoricalSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HistoricalMigrationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


__all__ = ["router"]
