"""Fail closed when a TEEECHR release image lacks its migration/event identity."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from deeptutor.courses.migrations.runner import discover_migrations, ensure_course_schema
from deeptutor.integrations.blueway.observability import emit_blueway_event


def main() -> int:
    expected_version = os.environ.get("EXPECTED_RELEASE_VERSION", "").strip()
    if not expected_version:
        raise RuntimeError("EXPECTED_RELEASE_VERSION is required")
    if os.environ.get("TEEECHR_ENVIRONMENT") != "production":
        raise RuntimeError("Release image environment is not production")
    if os.environ.get("TEEECHR_APP_VERSION") != expected_version:
        raise RuntimeError("Release image version does not match the release tag")

    artifacts = discover_migrations()
    if not artifacts or artifacts[-1].version < 18:
        raise RuntimeError("Release image does not contain Course migration 0018")
    with TemporaryDirectory(prefix="teeechr-release-") as directory:
        applied = ensure_course_schema(Path(directory) / "courses.db")
    if 18 not in applied:
        raise RuntimeError("Release image did not apply Course migration 0018")

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
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
