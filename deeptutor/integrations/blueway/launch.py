"""Owner-scoped BlueWay -> TEEECHR Course launch resolution.

The launch query contains only untrusted external identity hints. The current
authenticated request owns the repository and therefore the connection/map
lookup. A local Course id is returned only after one exact owner + connection
+ external Course + external term mapping has been proven.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Literal

from .repository import BlueWayRepository
from .workspace import WORKSPACE_FRESHNESS_SECONDS

LaunchStatus = Literal[
    "ready",
    "stale",
    "course_not_ready",
    "connection_revoked",
    "course_not_found",
    "term_mismatch",
    "temporarily_unavailable",
]

LAUNCH_SCHEMA_VERSION = "teeechr.blueway.launch.v1"
_ACTIVE_RUN_STATES = {"queued", "fetching", "validating", "staging", "indexing"}


@dataclass(frozen=True)
class CourseLaunchResolution:
    status: LaunchStatus
    course_id: str | None = None
    trace_id: str | None = None
    connection_ref: str | None = None

    def as_dict(self) -> dict[str, str]:
        payload: dict[str, str] = {
            "schema_version": LAUNCH_SCHEMA_VERSION,
            "status": self.status,
        }
        if self.course_id is not None:
            payload["course_id"] = self.course_id
        return payload


def resolve_course_launch(
    blueway: BlueWayRepository,
    *,
    external_course_id: str,
    external_term_id: str | None,
    now: float | None = None,
) -> CourseLaunchResolution:
    """Resolve one exact launch target without accepting request ownership.

    Missing and ambiguous matches fail closed. A foreign owner's mapping is
    invisible because the query is restricted to ``blueway.owner_user_id``.
    """

    course_hint = external_course_id.strip()
    term_hint = external_term_id.strip() if external_term_id is not None else None

    def result(status: LaunchStatus, row: object | None = None, *, course_id: str | None = None) -> CourseLaunchResolution:
        trace_id = str(row["observability_trace_id"]) if row is not None and row["observability_trace_id"] else None  # type: ignore[index]
        connection_ref = str(row["connection_id"]) if row is not None and row["connection_id"] else None  # type: ignore[index]
        return CourseLaunchResolution(status, course_id, trace_id, connection_ref)

    if not course_hint or len(course_hint) > 256:
        return result("course_not_found")
    if external_term_id is not None and not term_hint:
        return result("term_mismatch")

    with blueway.courses._connect() as conn:  # noqa: SLF001 - owner-scoped read
        rows = conn.execute(
            """SELECT m.connection_id, m.external_course_id, m.external_term_id,
                      m.course_id, m.remote_state, c.state AS course_state,
                      b.state AS connection_state, b.credential_status,
                      b.last_sync_at, b.observability_trace_id
                 FROM blueway_course_maps AS m
                 JOIN courses AS c ON c.id = m.course_id
                 JOIN blueway_connections AS b ON b.id = m.connection_id
                WHERE b.owner_user_id = ? AND c.owner_user_id = ?
                  AND m.external_course_id = ?
                ORDER BY m.updated_at DESC, m.course_id""",
            (blueway.owner_user_id, blueway.owner_user_id, course_hint),
        ).fetchall()

        if not rows:
            return result("course_not_found")
        if external_term_id is None:
            # A termless launch is a narrowly scoped legacy compatibility path:
            # it may select one exact NULL-term mapping, but it must never
            # guess between term-qualified mappings or multiple legacy rows.
            exact_rows = [row for row in rows if row["external_term_id"] is None]
            if len(exact_rows) > 1:
                return result("course_not_found")
        else:
            exact_rows = [row for row in rows if row["external_term_id"] == term_hint]
        if not exact_rows:
            return result("term_mismatch")
        if len(exact_rows) > 1:
            return result("course_not_found")

        live_rows = [
            row for row in exact_rows if row["connection_state"] == "active"
        ]

        if not live_rows:
            if any(
                row["connection_state"]
                in {"revocation_pending", "disconnected", "error"}
                for row in exact_rows
            ):
                return result("connection_revoked", exact_rows[0])
            return result("course_not_found", exact_rows[0])

        row = live_rows[0]
        if row["credential_status"] != "healthy":
            return result("temporarily_unavailable", row)

        latest_run = conn.execute(
            """SELECT state FROM blueway_sync_runs
                WHERE connection_id = ?
                ORDER BY updated_at DESC, id DESC LIMIT 1""",
            (row["connection_id"],),
        ).fetchone()
        if latest_run and latest_run["state"] == "failed":
            return result("temporarily_unavailable", row)
        if latest_run and latest_run["state"] in _ACTIVE_RUN_STATES:
            return result("course_not_ready", row)

        if row["course_state"] != "active" or row["remote_state"] != "active":
            return result("course_not_ready", row)

        source_states = {
            str(source[0])
            for source in conn.execute(
                "SELECT state FROM course_sources WHERE course_id = ?",
                (row["course_id"],),
            ).fetchall()
        }
        if not source_states or "processing" in source_states or "ready" not in source_states:
            return result("course_not_ready", row)

        if row["last_sync_at"] is None:
            return result("course_not_ready", row)

        # A stale but previously proven mapping remains openable. Preserve the
        # state so BlueWay and the browser receipt can distinguish stale-open
        # from a freshly synchronized launch.
        is_stale = (
            (now if now is not None else time.time()) - float(row["last_sync_at"])
            > WORKSPACE_FRESHNESS_SECONDS
        )
        return result("stale" if is_stale else "ready", row, course_id=str(row["course_id"]))
