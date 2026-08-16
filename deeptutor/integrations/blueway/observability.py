"""Safe, allowlisted lifecycle events for the BlueWay integration.

These events are evidence about persisted integration state.  They are not a
second state store and must never contain credentials, account identity, or
Course content.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import logging
import os
import re
from typing import Any, Literal
from uuid import UUID, uuid4

from deeptutor.__version__ import __version__
from deeptutor.logging.context import bind_log_context
from deeptutor.services.auth_diagnostics import validated_request_id

logger = logging.getLogger(__name__)

EVENT_SCHEMA_VERSION = "teeechr.blueway.lifecycle.v1"
EMITTING_SERVICE = "teeechr-server"

EventName = Literal[
    "blueway_pairing_started",
    "blueway_pairing_approval_received",
    "blueway_pairing_approval_rejected",
    "blueway_pairing_expired",
    "blueway_pairing_cancelled",
    "blueway_pairing_replayed",
    "blueway_pairing_wrong_account",
    "blueway_pairing_exchanged",
    "blueway_connection_status_read",
    "blueway_connection_created",
    "blueway_connection_revoked",
    "blueway_connection_revoke_failed",
    "blueway_credential_recovery_required",
    "blueway_sync_requested",
    "blueway_sync_duplicate_suppressed",
    "blueway_sync_state_changed",
    "blueway_sync_completed",
    "blueway_sync_failed",
    "blueway_workspace_read",
    "blueway_course_readiness_evaluated",
    "blueway_course_launch_allowed",
    "blueway_course_launch_denied",
]

EVENT_NAMES = frozenset(
    {
        "blueway_pairing_started",
        "blueway_pairing_approval_received",
        "blueway_pairing_approval_rejected",
        "blueway_pairing_expired",
        "blueway_pairing_cancelled",
        "blueway_pairing_replayed",
        "blueway_pairing_wrong_account",
        "blueway_pairing_exchanged",
        "blueway_connection_status_read",
        "blueway_connection_created",
        "blueway_connection_revoked",
        "blueway_connection_revoke_failed",
        "blueway_credential_recovery_required",
        "blueway_sync_requested",
        "blueway_sync_duplicate_suppressed",
        "blueway_sync_state_changed",
        "blueway_sync_completed",
        "blueway_sync_failed",
        "blueway_workspace_read",
        "blueway_course_readiness_evaluated",
        "blueway_course_launch_allowed",
        "blueway_course_launch_denied",
    }
)
PAIRING_TRACE_EVENTS = frozenset(
    {
        "blueway_pairing_started",
        "blueway_pairing_approval_received",
        "blueway_pairing_approval_rejected",
        "blueway_pairing_expired",
        "blueway_pairing_cancelled",
        "blueway_pairing_replayed",
        "blueway_pairing_wrong_account",
        "blueway_pairing_exchanged",
        "blueway_connection_created",
    }
)

_SAFE_REF = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_TRACE = re.compile(r"^(?:bwp|bwr)_(?:[0-9a-f-]{36}|[0-9a-f]{64})$")
_SAFE_STATES = frozenset(
    {
        "pending",
        "approved",
        "exchanged",
        "expired",
        "cancelled",
        "active",
        "paused",
        "revocation_pending",
        "revoked",
        "disconnected",
        "recovery_required",
        "queued",
        "fetching",
        "validating",
        "staging",
        "indexing",
        "completed",
        "failed",
        "not_connected",
        "consent_required",
        "syncing",
        "not_ready",
        "temporarily_unavailable",
        "stale",
        "ready",
        "course_not_ready",
        "connection_revoked",
        "course_not_found",
        "term_mismatch",
    }
)
_REASON_CODES = _SAFE_STATES | frozenset(
    {
        "active_run_exists",
        "approval_not_authorized",
        "approval_not_available",
        "authorization_pending",
        "credential_recovery_required",
        "indexing_failure",
        "provider_authority_lost",
        "provider_failure",
        "provider_rejected",
        "request_cancelled",
        "request_expired",
        "recovery_failed",
        "state_conflict",
        "validation_failure",
        "wrong_account",
    }
)
_OUTCOMES = frozenset(
    {
        "accepted",
        "allowed",
        "blocked",
        "completed",
        "denied",
        "failed",
        "in_progress",
        "pending",
        "ready",
        "rejected",
        "required",
        "success",
        "suppressed",
        "terminal",
    }
)
_COUNT_KEYS = frozenset(
    {"accepted", "archived", "created", "failed", "processing", "ready", "unlinked", "updated"}
)
_ENVIRONMENTS = frozenset({"development", "test", "staging", "beta", "production", "unknown"})
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")


def pairing_trace_id(request_id: str) -> str:
    """Return the cross-system trace for one server-issued pairing request.

    A provider-issued UUID is an opaque, high-entropy, non-secret request
    reference approved for diagnostics; it is not an account identifier or
    credential. Bounded non-UUID adapter references are domain-separated and
    hashed before they can enter a trace.
    """

    raw = str(request_id).strip()
    if not _SAFE_REF.fullmatch(raw):
        raise ValueError("Invalid BlueWay pairing request reference")
    try:
        normalized = str(UUID(raw))
    except (ValueError, TypeError, AttributeError):
        # Provider adapters and hermetic tests may use a bounded opaque
        # reference instead of a UUID. Preserve the same trace rule without
        # putting that reference into logs or exposing it cross-system.
        normalized = hashlib.sha256(b"teeechr.blueway.trace.v1\0" + raw.encode("utf-8")).hexdigest()
    return f"bwp_{normalized}"


def request_trace_id() -> str:
    """Create a request-scoped trace for work with no historical pairing trace."""

    return f"bwr_{uuid4()}"


def _event_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    raw_environment = (
        os.getenv("TEEECHR_ENVIRONMENT", "").strip() or os.getenv("ENVIRONMENT", "unknown").strip()
    ).lower()
    if raw_environment == "prod":
        raw_environment = "production"
    environment = raw_environment if raw_environment in _ENVIRONMENTS else "unknown"
    raw_version = os.getenv("TEEECHR_APP_VERSION", "").strip() or __version__
    application_version = raw_version if _SAFE_VERSION.fullmatch(raw_version) else "unknown"
    return {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "emitting_service": EMITTING_SERVICE,
        "environment": environment,
        "application_version": application_version,
        **payload,
    }


def safe_pairing_trace_id(request_id: str) -> str:
    """Use a pairing trace when possible, otherwise a truthful request trace."""

    try:
        return pairing_trace_id(request_id)
    except Exception:
        return request_trace_id()


def safe_persisted_pairing_trace_id(trace_id: Any, request_id: str) -> str:
    """Restore a persisted pairing trace without trusting stored text blindly."""

    if isinstance(trace_id, str) and _TRACE.fullmatch(trace_id):
        return trace_id
    return safe_pairing_trace_id(request_id)


def safe_request_ref(
    request_id: str | None,
    *,
    auth_secret: str | bytes | None = None,
) -> str | None:
    """HMAC a caller request reference before it can enter lifecycle logs.

    The digest is stable for correlation, but the caller-controlled value is
    never written to the server logs or copied into an event payload. When a
    deployment secret is not supplied, the shared diagnostic helper uses its
    server-held process key; callers with a durable deployment key may inject
    it for cross-process correlation.
    """

    return validated_request_id(request_id, auth_secret=auth_secret)


def build_blueway_event(
    event: EventName,
    *,
    trace_id: str | None = None,
    attempt_ref: str | None = None,
    connection_ref: str | None = None,
    sync_ref: str | None = None,
    request_ref: str | None = None,
    state_from: str | None = None,
    state_to: str | None = None,
    reason_code: str | None = None,
    duration_ms: int | None = None,
    outcome: str | None = None,
    counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Validate and build one strictly bounded event without emitting it."""

    if event not in EVENT_NAMES:
        raise ValueError("Unknown BlueWay lifecycle event")
    if event in PAIRING_TRACE_EVENTS and trace_id is None:
        raise ValueError("Pairing lifecycle events require a trace id")
    if trace_id is not None and not _TRACE.fullmatch(trace_id):
        raise ValueError("Invalid BlueWay trace id")
    for value in (attempt_ref, connection_ref, sync_ref, request_ref):
        if value is not None and not _SAFE_REF.fullmatch(value):
            raise ValueError("Invalid BlueWay diagnostic reference")
    for value in (state_from, state_to):
        if value is not None and value not in _SAFE_STATES:
            raise ValueError("Invalid BlueWay diagnostic state")
    if reason_code is not None and reason_code not in _REASON_CODES:
        raise ValueError("Invalid BlueWay diagnostic reason")
    if duration_ms is not None and (
        isinstance(duration_ms, bool) or duration_ms < 0 or duration_ms > 86_400_000
    ):
        raise ValueError("Invalid BlueWay diagnostic duration")
    if outcome is not None and outcome not in _OUTCOMES:
        raise ValueError("Invalid BlueWay diagnostic outcome")
    safe_counts: dict[str, int] | None = None
    if counts is not None:
        safe_counts = {}
        for key, value in counts.items():
            if str(key) not in _COUNT_KEYS:
                raise ValueError("Invalid BlueWay diagnostic count")
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value > 1_000_000
            ):
                raise ValueError("Invalid BlueWay diagnostic count")
            safe_counts[str(key)] = value

    payload: dict[str, Any] = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event": event,
    }
    for key, value in (
        ("trace_id", trace_id),
        ("attempt_ref", attempt_ref),
        ("connection_ref", connection_ref),
        ("sync_ref", sync_ref),
        ("request_ref", request_ref),
        ("state_from", state_from),
        ("state_to", state_to),
        ("reason_code", reason_code),
        ("duration_ms", duration_ms),
        ("outcome", outcome),
        ("counts", safe_counts),
    ):
        if value is not None:
            payload[key] = value

    return payload


def emit_blueway_event(
    event: EventName,
    *,
    trace_id: str | None = None,
    attempt_ref: str | None = None,
    connection_ref: str | None = None,
    sync_ref: str | None = None,
    request_ref: str | None = None,
    state_from: str | None = None,
    state_to: str | None = None,
    reason_code: str | None = None,
    duration_ms: int | None = None,
    outcome: str | None = None,
    counts: Mapping[str, int] | None = None,
) -> dict[str, Any] | None:
    """Best-effort event emission that cannot change the product result.

    Validation, serialization, logging-context, and handler failures are
    intentionally swallowed here.  ``build_blueway_event`` remains available
    for strict contract tests and offline validation.
    """

    try:
        payload = _event_envelope(
            build_blueway_event(
                event,
                trace_id=trace_id,
                attempt_ref=attempt_ref,
                connection_ref=connection_ref,
                sync_ref=sync_ref,
                request_ref=request_ref,
                state_from=state_from,
                state_to=state_to,
                reason_code=reason_code,
                duration_ms=duration_ms,
                outcome=outcome,
                counts=counts,
            )
        )
        # The formatter serializes only this allowlisted context field.  No
        # raw exception, request body, user identity, Course payload, or
        # credential is passed to the logger.
        with bind_log_context(blueway_event=payload):
            logger.info(event)
        return payload
    except Exception:
        # Observability is evidence, never an authority or response
        # dependency.  Do not log the rejected payload or exception here.
        return None


def safe_transport_reason(exc: BaseException) -> str:
    """Map a transport exception to a stable reason without logging its text."""

    name = type(exc).__name__
    if name == "BlueWayAuthorizationPending":
        return "authorization_pending"
    if name == "BlueWayAuthorityError":
        return "provider_authority_lost"
    if name == "BlueWayCredentialRecoveryRequired":
        return "credential_recovery_required"
    if name == "SnapshotValidationError":
        return "validation_failure"
    if name == "BundleMaterializationError":
        return "indexing_failure"
    if name == "CourseConflictError":
        return "state_conflict"
    return "provider_failure"
