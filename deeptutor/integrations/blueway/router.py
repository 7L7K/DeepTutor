"""Authenticated owner-scoped API for the optional BlueWay integration."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .repository import BlueWayNotFoundError, Connection, SyncRun
from .service import (
    BlueWayCredentialRecoveryRequired,
    BlueWayService,
    BlueWayUnavailableError,
    build_blueway_service,
)
from .transport import BlueWayTransportError
from .assertion import AssertionError as WorkspaceAssertionError, verify_assertion
from .workspace import ConsentRequiredError, project_workspace

router = APIRouter()
workspace_router = APIRouter()
_test_service: BlueWayService | None = None


class DisconnectRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class WorkspaceReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: str = Field(min_length=1, max_length=256)
    term_id: str | None = Field(default=None, min_length=1, max_length=256)


def set_test_service(service: BlueWayService | None) -> None:
    """Focused tests may inject a deterministic no-network service."""
    global _test_service
    _test_service = service


def _service() -> BlueWayService:
    return _test_service or build_blueway_service()


def _connection(connection: Connection | None) -> dict | None:
    if connection is None:
        return None
    return {
        "id": connection.id,
        "state": (
            "credential_recovery_required"
            if connection.credential_status == "recovery_required"
            else connection.state
        ),
        "revision": connection.revision,
        "scope_version": connection.scope_version, "connected_at": connection.connected_at,
        "last_sync_at": connection.last_sync_at,
    }


def _run(run: SyncRun | None) -> dict | None:
    if run is None:
        return None
    return {"id": run.id, "state": run.state, "counts": run.counts, "error_code": run.error_code}


def _call(operation):
    try:
        return operation()
    except BlueWayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Integration resource not found") from exc
    except BlueWayUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BlueWayCredentialRecoveryRequired as exc:
        raise HTTPException(
            status_code=409,
            detail="BlueWay credential recovery is required",
        ) from exc
    except BlueWayTransportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        from deeptutor.courses.repository import CourseConflictError
        if isinstance(exc, CourseConflictError):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise


@router.get("")
def status():
    service = _call(_service)
    if not service.settings.enabled:
        return {"enabled": False, "connection": None, "active_run": None}
    connection, run = _call(service.status)
    return {"enabled": True, "connection": _connection(connection), "active_run": _run(run)}


@router.post("/connect/start")
def connect_start():
    attempt = _call(lambda: _service().start_connection())
    return {
        "attempt_id": attempt.id, "user_code": attempt.user_code,
        "verification_uri": attempt.verification_uri, "expires_at": attempt.expires_at,
    }


@router.post("/recovery/start")
def recovery_start():
    attempt = _call(lambda: _service().start_recovery())
    return {
        "attempt_id": attempt.id,
        "user_code": attempt.user_code,
        "verification_uri": attempt.verification_uri,
        "expires_at": attempt.expires_at,
    }


@router.get("/connect/{attempt_id}/status")
def connect_status(attempt_id: str):
    service = _call(_service)
    attempt = _call(lambda: service.get_attempt(attempt_id))
    connection, run = _call(service.status)
    return {
        "enabled": service.settings.enabled, "attempt_id": attempt.id,
        "state": "pending", "expires_at": attempt.expires_at,
        "connection": _connection(connection), "active_run": _run(run),
    }


@router.post("/connect/{attempt_id}/poll", status_code=202)
def connect_poll(attempt_id: str):
    """Mutating approval poll; main's cookie-Origin middleware protects it."""
    connection, run = _call(lambda: _service().poll_connection(attempt_id=attempt_id))
    return {"enabled": True, "connection": _connection(connection), "active_run": _run(run)}


@router.get("/recovery/{attempt_id}/status")
def recovery_status(attempt_id: str):
    service = _call(_service)
    attempt = _call(lambda: service.get_attempt(attempt_id))
    if attempt.mode != "recovery":
        raise HTTPException(status_code=404, detail="Integration resource not found")
    connection, run = _call(service.status)
    return {
        "enabled": service.settings.enabled,
        "attempt_id": attempt.id,
        "state": "pending",
        "expires_at": attempt.expires_at,
        "connection": _connection(connection),
        "active_run": _run(run),
    }


@router.post("/recovery/{attempt_id}/poll", status_code=202)
def recovery_poll(attempt_id: str):
    connection, run = _call(
        lambda: _service().poll_recovery(attempt_id=attempt_id)
    )
    return {
        "enabled": True,
        "connection": _connection(connection),
        "active_run": _run(run),
    }


@router.post("/sync", status_code=202)
def sync():
    service = _service()
    run = _call(service.queue_sync)
    _call(lambda: service.schedule_sync(run))
    return _run(run)


@router.get("/sync-runs/{run_id}")
def sync_run(run_id: str):
    return _run(_call(lambda: _service().get_run(run_id)))


@router.get("/unlinked")
def unlinked():
    return {"records": _call(lambda: _service().unlinked_records())}


@router.post("/disconnect")
def disconnect(body: DisconnectRequest):
    connection = _call(lambda: _service().disconnect(expected_revision=body.expected_revision))
    return {"connection": _connection(connection)}


@workspace_router.post("/workspace")
def workspace_read(body: WorkspaceReadRequest, authorization: str | None = Header(default=None)):
    """Read the owner-scoped allowlist projection using a BlueWay assertion only."""
    if not authorization or not authorization.startswith("Bearer ") or not authorization[7:].strip():
        raise HTTPException(status_code=401, detail="Workspace assertion required")
    try:
        claims = verify_assertion(authorization[7:].strip())
        if claims["external_course_id"] != body.course_id or claims.get("external_term_id") != body.term_id:
            raise HTTPException(status_code=400, detail="Workspace request identity does not match assertion")
        return project_workspace(claims)
    except WorkspaceAssertionError as exc:
        raise HTTPException(status_code=401, detail="Invalid workspace assertion") from exc
    except ConsentRequiredError as exc:
        return JSONResponse(status_code=403, content={"schema_version": "teeechr.workspace.v1", "status": "consent_required"})
    except LookupError as exc:
        raise HTTPException(status_code=403, detail="Workspace consent is unavailable") from exc
