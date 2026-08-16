"""Authenticated owner-scoped API for the optional BlueWay integration."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from deeptutor.courses.service import CourseUnavailableError, get_current_course_service
from deeptutor.services import auth as auth_service

from .assertion import REVOCATION_SCOPE, verify_assertion
from .assertion import AssertionError as WorkspaceAssertionError
from .launch import resolve_course_launch
from .observability import emit_blueway_event, request_trace_id, safe_request_ref
from .repository import (
    BlueWayNotFoundError,
    BlueWayRepository,
    Connection,
    SyncRun,
    WorkspaceAssertionReplayError,
)
from .service import (
    BlueWayCredentialRecoveryRequired,
    BlueWayService,
    BlueWayUnavailableError,
    build_blueway_service,
)
from .transport import BlueWayTransportError
from .workspace import ConsentRequiredError, project_workspace, revoke_workspace_authorization

router = APIRouter()
workspace_router = APIRouter()
_test_service: BlueWayService | None = None


class DisconnectRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class WorkspaceReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: str = Field(min_length=1, max_length=256)
    term_id: str | None = Field(default=None, min_length=1, max_length=256)


class WorkspaceRevokeRequest(WorkspaceReadRequest):
    pass


@router.get("/launch")
def launch(
    external_course_id: str = Query(min_length=1, max_length=256),
    external_term_id: str | None = Query(default=None, max_length=256),
    x_request_id: str | None = Header(default=None),
):
    """Resolve a BlueWay launch hint inside the authenticated Course scope."""
    try:
        course_service = get_current_course_service()
    except CourseUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="Course launch is temporarily unavailable",
        ) from exc
    resolution = resolve_course_launch(
        BlueWayRepository(course_service.repository),
        external_course_id=external_course_id,
        external_term_id=external_term_id,
    )
    event_name = (
        "blueway_course_launch_allowed"
        if resolution.status in {"ready", "stale"}
        else "blueway_course_launch_denied"
    )
    emit_blueway_event(
        event_name,
        trace_id=resolution.trace_id or request_trace_id(),
        connection_ref=resolution.connection_ref,
        request_ref=safe_request_ref(
            x_request_id, auth_secret=auth_service.AUTH_SECRET or None,
        ),
        reason_code=resolution.status,
        outcome="allowed" if event_name.endswith("allowed") else "denied",
    )
    payload = resolution.as_dict()
    return JSONResponse(
        content=payload,
        headers={"Cache-Control": "private, no-store"},
    )


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
    return {
        "id": run.id,
        "state": run.state,
        "counts": run.counts,
        "error_code": run.error_code,
        "created_at": run.created_at,
    }


def _attempt(attempt) -> dict:
    """Return pairing metadata only; encrypted provider material stays server-side."""
    return {
        "attempt_id": attempt.id,
        "request_id": attempt.request_id,
        "user_code": attempt.user_code,
        "verification_uri": attempt.verification_uri,
        "expires_at": attempt.expires_at,
        "mode": attempt.mode,
        "state": attempt.state,
    }


def _attempt_for_mode(
    service: BlueWayService,
    attempt_id: str,
    mode: str,
    *,
    purge_expired: bool = True,
):
    attempt = service.get_attempt(attempt_id, purge_expired=purge_expired)
    if attempt.mode != mode:
        raise BlueWayNotFoundError("Integration resource not found")
    return attempt


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
    observed_state = "not_connected"
    if connection is not None:
        if connection.credential_status == "recovery_required":
            observed_state = "recovery_required"
        else:
            observed_state = {
                "active": "active",
                "disconnected": "not_connected",
                "revocation_pending": "revocation_pending",
                "error": "temporarily_unavailable",
            }.get(connection.state, "temporarily_unavailable")
    emit_blueway_event(
        "blueway_connection_status_read",
        trace_id=connection.observability_trace_id if connection and connection.observability_trace_id else request_trace_id(),
        connection_ref=connection.id if connection else None,
        sync_ref=run.id if run else None,
        state_to=observed_state,
        outcome="success",
    )
    return {"enabled": True, "connection": _connection(connection), "active_run": _run(run)}


@router.post("/connect/start")
def connect_start():
    attempt = _call(lambda: _service().start_connection())
    return _attempt(attempt)


@router.get("/connect/current")
def connect_current():
    attempt = _call(lambda: _service().current_attempt())
    return {"attempt": _attempt(attempt) if attempt is not None else None}


@router.post("/recovery/start")
def recovery_start():
    attempt = _call(lambda: _service().start_recovery())
    return _attempt(attempt)


@router.get("/connect/{attempt_id}/status")
def connect_status(attempt_id: str):
    service = _call(_service)
    attempt = _call(lambda: _attempt_for_mode(service, attempt_id, "connect"))
    connection, run = _call(service.status)
    return {
        "enabled": service.settings.enabled, "attempt_id": attempt.id,
        "request_id": attempt.request_id, "user_code": attempt.user_code,
        "verification_uri": attempt.verification_uri, "mode": attempt.mode,
        "state": attempt.state, "expires_at": attempt.expires_at,
        "pairing": _attempt(attempt),
        "connection": _connection(connection), "active_run": _run(run),
    }


@router.post("/connect/{attempt_id}/poll", status_code=202)
def connect_poll(attempt_id: str):
    """Mutating approval poll; main's cookie-Origin middleware protects it."""
    service = _call(_service)
    connection, run = _call(lambda: service.poll_connection(attempt_id=attempt_id))
    attempt = _call(lambda: _attempt_for_mode(service, attempt_id, "connect"))
    return {
        "enabled": True, "attempt_id": attempt.id, "state": attempt.state,
        "expires_at": attempt.expires_at, "pairing": _attempt(attempt),
        "connection": _connection(connection),
        "active_run": _run(run),
    }


@router.post("/connect/{attempt_id}/cancel")
def connect_cancel(attempt_id: str):
    service = _call(_service)
    _call(lambda: _attempt_for_mode(service, attempt_id, "connect", purge_expired=False))
    attempt = _call(lambda: service.cancel_attempt(attempt_id=attempt_id))
    return {"attempt": _attempt(attempt)}


@router.post("/recovery/{attempt_id}/cancel")
def recovery_cancel(attempt_id: str):
    service = _call(_service)
    _call(lambda: _attempt_for_mode(service, attempt_id, "recovery", purge_expired=False))
    attempt = _call(lambda: service.cancel_attempt(attempt_id=attempt_id))
    return {"attempt": _attempt(attempt)}


@router.get("/recovery/{attempt_id}/status")
def recovery_status(attempt_id: str):
    service = _call(_service)
    attempt = _call(lambda: _attempt_for_mode(service, attempt_id, "recovery"))
    connection, run = _call(service.status)
    return {
        "enabled": service.settings.enabled,
        "attempt_id": attempt.id,
        "request_id": attempt.request_id, "user_code": attempt.user_code,
        "verification_uri": attempt.verification_uri, "mode": attempt.mode,
        "state": attempt.state,
        "expires_at": attempt.expires_at,
        "pairing": _attempt(attempt),
        "connection": _connection(connection),
        "active_run": _run(run),
    }


@router.post("/recovery/{attempt_id}/poll", status_code=202)
def recovery_poll(attempt_id: str):
    service = _call(_service)
    connection, run = _call(lambda: service.poll_recovery(attempt_id=attempt_id))
    return {
        "enabled": True,
        "connection": _connection(connection),
        "active_run": _run(run),
        "attempt": _attempt(_call(lambda: _attempt_for_mode(service, attempt_id, "recovery"))),
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
    emit_blueway_event(
        "blueway_connection_revoked",
        trace_id=connection.observability_trace_id,
        connection_ref=connection.id,
        state_from="revocation_pending",
        state_to="disconnected",
        outcome="success",
    )
    return {"connection": _connection(connection)}


@workspace_router.post("/workspace")
def workspace_read(
    body: WorkspaceReadRequest,
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
):
    """Read the owner-scoped allowlist projection using a BlueWay assertion only."""
    request_id = safe_request_ref(
        x_request_id, auth_secret=auth_service.AUTH_SECRET or None,
    )
    if not authorization or not authorization.startswith("Bearer ") or not authorization[7:].strip():
        raise HTTPException(status_code=401, detail="Workspace assertion required")
    try:
        claims = verify_assertion(authorization[7:].strip())
        if claims["external_course_id"] != body.course_id or claims.get("external_term_id") != body.term_id:
            raise HTTPException(status_code=400, detail="Workspace request identity does not match assertion")
        return project_workspace(claims, consume_replay=True, request_ref=request_id)
    except WorkspaceAssertionError as exc:
        raise HTTPException(status_code=401, detail="Invalid workspace assertion") from exc
    except WorkspaceAssertionReplayError as exc:
        raise HTTPException(status_code=401, detail="Workspace assertion has already been used") from exc
    except ConsentRequiredError as exc:
        return JSONResponse(status_code=403, content={"schema_version": "teeechr.workspace.v1", "status": "consent_required"})
    except LookupError as exc:
        raise HTTPException(status_code=403, detail="Workspace consent is unavailable") from exc


@workspace_router.post("/workspace/revoke", status_code=204)
def workspace_revoke(
    body: WorkspaceRevokeRequest,
    authorization: str | None = Header(default=None),
):
    """Immediately fence one exact local authorization from BlueWay."""
    if not authorization or not authorization.startswith("Bearer ") or not authorization[7:].strip():
        raise HTTPException(status_code=401, detail="Workspace assertion required")
    try:
        claims = verify_assertion(authorization[7:].strip(), expected_scope=REVOCATION_SCOPE)
        if claims["external_course_id"] != body.course_id or claims.get("external_term_id") != body.term_id:
            raise HTTPException(status_code=400, detail="Workspace request identity does not match assertion")
        revoke_workspace_authorization(claims)
    except WorkspaceAssertionError as exc:
        raise HTTPException(status_code=401, detail="Invalid workspace revocation assertion") from exc
    except WorkspaceAssertionReplayError as exc:
        raise HTTPException(status_code=401, detail="Workspace revocation assertion has already been used") from exc
    except ConsentRequiredError as exc:
        raise HTTPException(status_code=404, detail="Workspace authorization is unavailable") from exc
    return None
