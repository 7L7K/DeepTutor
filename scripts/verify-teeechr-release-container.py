"""Fail closed when a TEEECHR release image lacks its migration/event identity."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from deeptutor.courses.migrations.runner import discover_migrations, ensure_course_schema
from deeptutor.integrations.blueway.observability import emit_blueway_event

REQUIRED_LATEST_COURSE_MIGRATION = 19
_GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")


def main() -> int:
    expected_version = os.environ.get("EXPECTED_RELEASE_VERSION", "").strip()
    if not expected_version:
        raise RuntimeError("EXPECTED_RELEASE_VERSION is required")
    expected_revision = os.environ.get("EXPECTED_RELEASE_REVISION", "").strip()
    # The local exact-VPS controller predates the explicit revision variable
    # and passes the target full SHA as EXPECTED_RELEASE_VERSION. Keep that
    # path exact rather than weakening the check to a mutable tag: the fallback
    # is accepted only when the version itself is a full Git revision.
    if not expected_revision and _GIT_REVISION.fullmatch(expected_version):
        expected_revision = expected_version
    if not _GIT_REVISION.fullmatch(expected_revision):
        raise RuntimeError("EXPECTED_RELEASE_REVISION must be a full Git SHA")
    if os.environ.get("TEEECHR_ENVIRONMENT") != "production":
        raise RuntimeError("Release image environment is not production")
    if os.environ.get("TEEECHR_APP_VERSION") != expected_version:
        raise RuntimeError("Release image version does not match the release tag")
    if os.environ.get("TEEECHR_SOURCE_REVISION") != expected_revision:
        raise RuntimeError("Release image revision does not match the release source")

    artifacts = discover_migrations()
    if not artifacts or artifacts[-1].version != REQUIRED_LATEST_COURSE_MIGRATION:
        raise RuntimeError(
            "Release image does not contain the required latest Course migration 0019"
        )
    with TemporaryDirectory(prefix="teeechr-release-") as directory:
        applied = ensure_course_schema(Path(directory) / "courses.db")
    if REQUIRED_LATEST_COURSE_MIGRATION not in applied:
        raise RuntimeError("Release image did not apply Course migration 0019")

    event = emit_blueway_event(
        "blueway_connection_revoke_failed",
        trace_id="bwr_11111111-1111-4111-8111-111111111111",
        connection_ref="bwc_release_probe",
        state_from="revocation_pending",
        state_to="revocation_pending",
        reason_code="provider_failure",
        outcome="failed",
    )
    if event is None:
        raise RuntimeError("Release image rejected the lifecycle event contract")
    if event["environment"] != "production":
        raise RuntimeError("Lifecycle event environment is not production")
    if event["application_version"] != expected_version:
        raise RuntimeError("Lifecycle event version does not match the release tag")

    print(
        json.dumps(
            {
                "status": "PASS",
                "application_version": event["application_version"],
                "environment": event["environment"],
                "latest_migration": artifacts[-1].version,
                "source_revision": expected_revision,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
