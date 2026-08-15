"""Owner-scoped, allowlisted ``teeechr.workspace.v1`` projection for BlueWay.

The route accepts only a verified assertion and external course/term identity.
It locates the metadata-only authorization, derives its owner, opens that
owner's private CourseRepository, and never serializes local IDs or source
payloads.  A missing map is ``not_ready``; active processing is ``syncing``;
failed provider work is ``temporarily_unavailable``; and freshness is measured
from the last successful synchronization timestamp. Archived or incomplete
Course/map state is ``not_ready``, not ``stale``.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import logging
from pathlib import Path
import time
from typing import Any

from deeptutor.courses.migrations.runner import open_course_connection
from deeptutor.courses.repository import CourseRepository
from deeptutor.multi_user import paths

from .repository import (
    BlueWayNotFoundError,
    BlueWayRepository,
    WorkspaceAuthorization,
)
from .observability import emit_blueway_event, request_trace_id

SCHEMA_VERSION = "teeechr.workspace.v1"
WORKSPACE_FRESHNESS_SECONDS = 24 * 60 * 60
# Direct launch is intentionally bounded to the same lifetime as a BlueWay
# assertion. BlueWay revocation is therefore enforced within at most this
# interval even if the local TEEECHR row has not received a revocation notice.
WORKSPACE_LEASE_SECONDS = 60
logger = logging.getLogger(__name__)


def _iso_timestamp(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), UTC).isoformat().replace("+00:00", "Z")


class ConsentRequiredError(LookupError):
    """The signed assertion is valid but no local consent record is available."""


def _candidate_databases() -> list[Path]:
    data = paths.PROJECT_ROOT / "data"
    candidates = [data / "user" / "courses.db"]
    users = data / "users"
    if users.is_dir() and not users.is_symlink():
        candidates.extend(
            child / "user" / "courses.db"
            for child in users.iterdir()
            if child.is_dir() and not child.is_symlink()
        )
    return [candidate for candidate in candidates if candidate.is_file() and not candidate.is_symlink()]


def resolve_authorization(
    claims: dict[str, Any], *, consume_replay: bool = False,
) -> tuple[WorkspaceAuthorization, BlueWayRepository]:
    """Resolve or provision exact authorization from fresh signed authority."""
    authorization_id = str(claims["authorization_id"])
    subject_hash = str(claims["subject_hash"])
    candidates = _candidate_databases()
    scanned_candidates = 0
    for database in candidates:
        scanned_candidates += 1
        try:
            # Existing rows are only a database locator. The assertion is still
            # revalidated against the active connection and exact Course map.
            with open_course_connection(database) as conn:
                row = conn.execute("""SELECT owner_user_id FROM blueway_workspace_authorizations
                    WHERE authorization_id = ? AND external_subject_hash = ?""", (authorization_id, subject_hash)).fetchone()
                if row is None:
                    connection_row = conn.execute(
                        """SELECT owner_user_id, id FROM blueway_connections
                           WHERE external_subject = ?""",
                        (claims["sub"],),
                    ).fetchone()
                else:
                    connection_row = conn.execute(
                        """SELECT owner_user_id, id FROM blueway_connections
                           WHERE owner_user_id = ? AND external_subject = ?""",
                        (row["owner_user_id"], claims["sub"]),
                    ).fetchone()
            if connection_row is None:
                continue
            owner = str(connection_row["owner_user_id"])
            course_repo = CourseRepository(database, owner)
            blueway = BlueWayRepository(course_repo)
            authorization = blueway.ensure_workspace_authorization(
                authorization_id=authorization_id,
                client_id=str(claims["client_id"]),
                external_subject=str(claims["sub"]),
                external_subject_hash=subject_hash,
                scope=str(claims["scope"]),
                external_course_id=str(claims["external_course_id"]),
                external_term_id=claims.get("external_term_id"),
                connection_id=str(connection_row["id"]),
                lease_seconds=WORKSPACE_LEASE_SECONDS,
                assertion_jti=(str(claims["jti"]) if consume_replay else None),
                assertion_expires_at=(float(claims["exp"]) if consume_replay else None),
            )
            logger.info(
                "blueway_workspace_authorization_resolved",
                extra={
                    "candidate_database_count": len(candidates),
                    "candidate_databases_scanned": scanned_candidates,
                },
            )
            return authorization, blueway
        except (BlueWayNotFoundError, OSError, RuntimeError, ValueError):
            logger.warning(
                "blueway_workspace_candidate_unreadable",
                extra={"candidate_databases_scanned": scanned_candidates},
            )
            continue
    logger.info(
        "blueway_workspace_authorization_not_found",
        extra={
            "candidate_database_count": len(candidates),
            "candidate_databases_scanned": scanned_candidates,
        },
    )
    raise ConsentRequiredError("Workspace authorization not found")


def revoke_workspace_authorization(
    claims: dict[str, Any], *, now: float | None = None,
) -> WorkspaceAuthorization:
    """Consume a signed revocation and fence the exact local authorization."""
    del now  # Kept symmetric with projection helpers; assertion time is verified upstream.
    authorization_id = str(claims["authorization_id"])
    subject_hash = str(claims["subject_hash"])
    candidates = _candidate_databases()
    for database in candidates:
        try:
            with open_course_connection(database) as conn:
                row = conn.execute(
                    """SELECT owner_user_id FROM blueway_workspace_authorizations
                       WHERE authorization_id = ? AND external_subject_hash = ?""",
                    (authorization_id, subject_hash),
                ).fetchone()
            if row is None:
                continue
            blueway = BlueWayRepository(
                CourseRepository(database, str(row["owner_user_id"])),
            )
            return blueway.revoke_workspace_authorization_from_assertion(
                authorization_id=authorization_id,
                client_id=str(claims["client_id"]),
                external_subject=str(claims["sub"]),
                external_subject_hash=subject_hash,
                external_course_id=str(claims["external_course_id"]),
                external_term_id=claims.get("external_term_id"),
                assertion_jti=str(claims["jti"]),
                assertion_expires_at=float(claims["exp"]),
            )
        except (BlueWayNotFoundError, OSError, RuntimeError, ValueError):
            continue
    raise ConsentRequiredError("Workspace authorization not found")


def project_workspace(
    claims: dict[str, Any], *, now: float | None = None,
    consume_replay: bool = False, request_ref: str | None = None,
) -> dict[str, Any]:
    if consume_replay:
        authorization, blueway = resolve_authorization(claims, consume_replay=True)
    else:
        authorization, blueway = resolve_authorization(claims)
    if (
        claims.get("client_id") != authorization.client_id
        or claims.get("authorization_id") != authorization.authorization_id
        or claims.get("scope") != authorization.scope
        or hashlib.sha256(claims["sub"].encode()).hexdigest() != authorization.external_subject_hash
        or authorization.external_course_id != claims.get("external_course_id")
        or authorization.external_term_id != claims.get("external_term_id")
    ):
        raise LookupError("Workspace subject does not match authorization")
    connection = blueway.get_connection(authorization.connection_id)
    if connection.external_subject != claims["sub"]:
        raise LookupError("Workspace subject does not match connection")
    operation_trace_id = connection.observability_trace_id or request_trace_id()

    def finish(payload: dict[str, Any]) -> dict[str, Any]:
        status = str(payload.get("status", "temporarily_unavailable"))
        emit_blueway_event(
            "blueway_course_readiness_evaluated",
            trace_id=operation_trace_id,
            connection_ref=connection.id,
            request_ref=request_ref,
            state_to=status,
            reason_code=status,
            outcome="ready" if status in {"ready", "stale"} else "blocked",
        )
        emit_blueway_event(
            "blueway_workspace_read",
            trace_id=operation_trace_id,
            connection_ref=connection.id,
            request_ref=request_ref,
            state_to=status,
            outcome="success",
        )
        return payload

    if authorization.status == "revoked":
        return finish({"schema_version": SCHEMA_VERSION, "status": "revoked"})
    if authorization.status != "active" or authorization.scope != "teeechr.workspace.read.v1":
        return finish({"schema_version": SCHEMA_VERSION, "status": "consent_required"})
    if connection.state in {"disconnected", "error"}:
        return finish({"schema_version": SCHEMA_VERSION, "status": "not_connected"})
    if connection.state != "active" or connection.credential_status != "healthy":
        return finish({"schema_version": SCHEMA_VERSION, "status": "temporarily_unavailable"})
    external_course_id = str(claims["external_course_id"])
    external_term_id = claims.get("external_term_id")
    with blueway.courses._connect() as conn:  # noqa: SLF001
        mapping = conn.execute("""SELECT m.course_id, m.external_course_id, m.external_term_id,
                m.remote_title, m.remote_state, c.state AS course_state
            FROM blueway_course_maps m JOIN courses c ON c.id = m.course_id
            WHERE m.connection_id = ? AND m.external_course_id = ?
              AND m.external_term_id IS ? AND c.owner_user_id = ?""",
            (connection.id, external_course_id, external_term_id, blueway.owner_user_id)).fetchone()
        run = conn.execute("""SELECT state, error_code FROM blueway_sync_runs
            WHERE connection_id = ? ORDER BY updated_at DESC LIMIT 1""", (connection.id,)).fetchone()
        if mapping is None:
            if run and run["state"] in {"queued", "fetching", "validating", "staging", "indexing"}:
                status = "syncing"
            elif run and run["state"] == "failed":
                status = "temporarily_unavailable"
            else:
                status = "not_ready"
            return finish({"schema_version": SCHEMA_VERSION, "status": status})
        connected_sources_count = conn.execute(
            """SELECT COUNT(*) FROM course_sources
               WHERE course_id = ? AND state = 'ready'""",
            (mapping["course_id"],),
        ).fetchone()[0]
        meetings_count = conn.execute(
            """SELECT COUNT(*) FROM blueway_records
               WHERE connection_id = ? AND course_id = ?
                 AND external_course_id = ? AND external_term_id IS ?
                 AND record_kind = 'class_meetings' AND state = 'current'""",
            (connection.id, mapping["course_id"], external_course_id, external_term_id),
        ).fetchone()[0]
        counts = {
            "connected_sources_count": int(connected_sources_count),
            "meetings_count": int(meetings_count),
        }
        source_states = [str(row[0]) for row in conn.execute("SELECT state FROM course_sources WHERE course_id = ?", (mapping["course_id"],)).fetchall()]
    if mapping["course_state"] != "active" or mapping["remote_state"] != "active":
        status = "not_ready"
    elif (run and run["state"] in {"queued", "fetching", "validating", "staging", "indexing"}) or "processing" in source_states:
        status = "syncing"
    elif run and run["state"] == "failed":
        status = "temporarily_unavailable"
    elif connection.last_sync_at is None:
        status = "not_ready"
    elif (now if now is not None else time.time()) - float(connection.last_sync_at) > WORKSPACE_FRESHNESS_SECONDS:
        status = "stale"
    elif "ready" in source_states:
        status = "ready"
    else:
        status = "not_ready"
    return finish({
        "schema_version": SCHEMA_VERSION, "status": status,
        "course": {"external_course_id": mapping["external_course_id"], **({"external_term_id": mapping["external_term_id"]} if mapping["external_term_id"] is not None else {}), "title": mapping["remote_title"]},
        "sync": {"last_synced_at": _iso_timestamp(connection.last_sync_at), "is_stale": status == "stale"},
        "summary": counts,
        "resume": None,
        "recommended_next_action": None,
    })
