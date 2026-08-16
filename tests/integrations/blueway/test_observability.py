"""Focused safety and trace-contract tests for BlueWay lifecycle events."""

from __future__ import annotations

import hashlib
from io import StringIO
import json
import logging
from pathlib import Path

import pytest

from deeptutor.__version__ import __version__
from deeptutor.courses.repository import CourseRepository
from deeptutor.integrations.blueway.observability import (
    EVENT_SCHEMA_VERSION,
    build_blueway_event,
    emit_blueway_event,
    pairing_trace_id,
    request_trace_id,
    safe_persisted_pairing_trace_id,
    safe_request_ref,
)
from deeptutor.integrations.blueway.repository import BlueWayRepository
from deeptutor.integrations.blueway.service import BlueWayService, PairingAttempt
from deeptutor.logging.formatters import ContextFilter, JsonlFormatter
from deeptutor.services.auth_diagnostics import validated_request_id

REQUEST_ID = "11111111-1111-4111-8111-111111111111"
TRACE_ID = f"bwp_{REQUEST_ID}"
CORPUS = json.loads(
    (Path(__file__).parent / "fixtures" / "teeechr.blueway.lifecycle.v1.json").read_text()
)


def test_pairing_trace_is_deterministic_and_uuid_is_explicitly_opaque_safe() -> None:
    assert pairing_trace_id(REQUEST_ID) == TRACE_ID
    assert pairing_trace_id(REQUEST_ID.upper()) == TRACE_ID
    assert pairing_trace_id("request-1").startswith("bwp_")
    assert request_trace_id().startswith("bwr_")
    with pytest.raises(ValueError):
        pairing_trace_id("https://attacker.example")


def test_request_reference_is_stable_but_never_preserves_caller_text() -> None:
    raw = "phone-attempt-20260815-001"
    safe = safe_request_ref(raw, auth_secret="blueway-test-diagnostic-secret")

    assert safe is not None
    assert safe.startswith("req_")
    assert safe == safe_request_ref(raw, auth_secret="blueway-test-diagnostic-secret")
    assert safe == validated_request_id(raw, auth_secret="blueway-test-diagnostic-secret")
    assert safe != safe_request_ref(raw, auth_secret="different-secret")
    assert raw not in safe
    assert safe_request_ref("https://attacker.example") is None


def test_persisted_pairing_attempt_keeps_trace_and_legacy_records_get_a_safe_fallback() -> None:
    attempt = PairingAttempt(
        id="attempt-1",
        owner_user_id="owner-a",
        device_code="device-code",
        verifier="verifier",
        user_code="ABCD-EFGH",
        verification_uri="https://teeechr.example/connect",
        expires_at=1_800_000_000.0,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        connection_id="bwc_connection",
    )

    record = BlueWayService._attempt_record(attempt)
    restored = BlueWayService._attempt_from_record("attempt-1", record)
    legacy = BlueWayService._attempt_from_record(
        "attempt-1",
        {key: value for key, value in record.items() if key not in {"trace_id", "connection_id"}},
    )
    malformed = BlueWayService._attempt_from_record("attempt-1", {**record, "trace_id": "owner-a"})

    assert record["trace_id"] == TRACE_ID
    assert record["connection_id"] == "bwc_connection"
    assert restored.trace_id == TRACE_ID
    assert restored.connection_id == "bwc_connection"
    assert legacy.trace_id == TRACE_ID
    assert legacy.connection_id is None
    assert malformed.trace_id == safe_persisted_pairing_trace_id(None, REQUEST_ID)


def test_legacy_connection_without_trace_uses_a_request_scoped_trace(monkeypatch) -> None:
    from deeptutor.integrations.blueway import workspace

    class Connection:
        id = "bwc_legacy"
        external_subject = "provider-subject"
        state = "active"
        credential_status = "healthy"
        observability_trace_id = None
        last_sync_at = None

    class Authorization:
        authorization_id = "bwa_authorization"
        client_id = "teeechr"
        scope = "teeechr.workspace.read.v1"
        connection_id = Connection.id
        status = "revoked"
        external_subject_hash = hashlib.sha256(Connection.external_subject.encode()).hexdigest()
        external_course_id = "course-1"
        external_term_id = None

    class Repository:
        owner_user_id = "owner-a"

        @staticmethod
        def get_connection(_connection_id):
            return Connection()

        @staticmethod
        def get_workspace_authorization(_authorization_id):
            return Authorization()

    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(
        workspace, "resolve_authorization", lambda _claims: (Authorization(), Repository())
    )
    monkeypatch.setattr(workspace, "request_trace_id", lambda: "bwr_legacy-request")
    monkeypatch.setattr(
        workspace, "emit_blueway_event", lambda _event, **fields: emitted.append(fields)
    )

    result = workspace.project_workspace(
        {
            "authorization_id": Authorization.authorization_id,
            "client_id": Authorization.client_id,
            "scope": Authorization.scope,
            "sub": Connection.external_subject,
            "external_course_id": "course-1",
        }
    )

    assert result["status"] == "revoked"
    assert emitted
    assert {item["trace_id"] for item in emitted} == {"bwr_legacy-request"}


def test_pinned_conformance_corpus_matches_the_python_contract() -> None:
    assert CORPUS["contract_version"] == EVENT_SCHEMA_VERSION
    assert (
        hashlib.sha256(
            json.dumps(CORPUS, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        == "cc6de03c589866ebe04f7dc935df706266e956f76a7af985620049ece2df26c2"
    )
    accepted = [item for item in CORPUS["cases"] if item["expected"] == "accepted"]
    for item in accepted:
        fields = dict(item["fields"])
        built = build_blueway_event(item["event"], **fields)
        assert built["event"] == item["event"]

    redaction = next(item for item in CORPUS["cases"] if item["name"] == "redaction_attempt")
    safe_fields = {
        key: value
        for key, value in redaction["fields"].items()
        if key
        in {
            "trace_id",
            "attempt_ref",
            "connection_ref",
            "sync_ref",
            "request_ref",
            "state_from",
            "state_to",
            "reason_code",
            "duration_ms",
            "outcome",
            "counts",
        }
    }
    redacted = build_blueway_event(redaction["event"], **safe_fields)
    assert "private_field" not in redacted
    for name in ("invalid_event_name", "invalid_reason_code", "invalid_count_key"):
        item = next(candidate for candidate in CORPUS["cases"] if candidate["name"] == name)
        with pytest.raises(ValueError):
            build_blueway_event(item["event"], **item["fields"])


def test_connection_persists_only_the_diagnostic_trace_reference(tmp_path) -> None:
    repository = BlueWayRepository(CourseRepository(tmp_path / "courses.db", "owner-a"))
    connection = repository.create_active_connection(
        external_subject="provider-subject",
        scope_version="academic.read.v1",
        observability_trace_id=TRACE_ID,
    )

    assert connection.observability_trace_id == TRACE_ID
    assert connection.external_subject == "provider-subject"


def test_success_and_failure_traces_are_reconstructable_without_private_payloads(caplog) -> None:
    caplog.set_level(logging.INFO, logger="deeptutor.integrations.blueway.observability")
    logger = logging.getLogger("deeptutor.integrations.blueway.observability")
    rendered = StringIO()
    handler = logging.StreamHandler(rendered)
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonlFormatter())
    logger.addHandler(handler)
    try:
        success = emit_blueway_event(
            "blueway_pairing_exchanged",
            trace_id=TRACE_ID,
            attempt_ref="bwa_attempt",
            connection_ref="bwc_connection",
            state_from="approved",
            state_to="exchanged",
            outcome="success",
        )
        failed = emit_blueway_event(
            "blueway_sync_failed",
            trace_id=TRACE_ID,
            connection_ref="bwc_connection",
            sync_ref="bwr_sync",
            state_from="validating",
            state_to="failed",
            reason_code="validation_failure",
            outcome="failed",
        )
    finally:
        logger.removeHandler(handler)

    assert success["schema_version"] == EVENT_SCHEMA_VERSION
    assert success["trace_id"] == failed["trace_id"] == TRACE_ID
    assert [record.getMessage() for record in caplog.records[-2:]] == [
        "blueway_pairing_exchanged",
        "blueway_sync_failed",
    ]
    formatted = rendered.getvalue().splitlines()[-1]
    assert '"blueway_event"' in formatted
    assert '"timestamp":' in formatted
    assert '"emitting_service": "teeechr-server"' in formatted
    assert '"environment": "unknown"' in formatted
    assert f'"application_version": "{__version__}"' in formatted
    assert '"password"' not in formatted
    serialized = repr([success, failed])
    for forbidden in (
        "access_token",
        "refresh_token",
        "password",
        "cookie",
        "course title",
        "transcript",
        "owner-a",
    ):
        assert forbidden not in serialized


def test_event_envelope_uses_established_environment_fallback(monkeypatch) -> None:
    monkeypatch.delenv("TEEECHR_ENVIRONMENT", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "prod")

    event = emit_blueway_event(
        "blueway_connection_status_read",
        trace_id=TRACE_ID,
        state_to="active",
        outcome="success",
    )

    assert event["environment"] == "production"


def test_event_builder_rejects_unsafe_state_and_reference() -> None:
    revoked = build_blueway_event(
        "blueway_connection_revoked",
        trace_id=TRACE_ID,
        state_from="revocation_pending",
        state_to="disconnected",
        outcome="success",
    )
    assert revoked["state_from"] == "revocation_pending"
    assert revoked["state_to"] == "disconnected"

    recovery = build_blueway_event(
        "blueway_credential_recovery_required",
        trace_id=TRACE_ID,
        state_from="active",
        state_to="recovery_required",
        reason_code="credential_recovery_required",
        outcome="required",
    )
    assert recovery["outcome"] == "required"

    with pytest.raises(ValueError):
        build_blueway_event(
            "blueway_sync_state_changed",
            trace_id=TRACE_ID,
            state_to="raw-course-title",
        )
    with pytest.raises(ValueError):
        build_blueway_event(
            "blueway_sync_state_changed",
            trace_id=TRACE_ID,
            request_ref="../../private/log",
        )
    with pytest.raises(ValueError):
        build_blueway_event(
            "blueway_sync_failed",
            trace_id=TRACE_ID,
            reason_code="invented_reason",
        )
    with pytest.raises(ValueError):
        build_blueway_event(
            "blueway_sync_requested",
            trace_id=TRACE_ID,
            counts={"private_field": 1},
        )


def test_event_failures_are_best_effort_and_never_escape_to_callers(monkeypatch) -> None:
    import deeptutor.integrations.blueway.observability as observability

    monkeypatch.setattr(
        observability.logger,
        "info",
        lambda _message: (_ for _ in ()).throw(RuntimeError("sink down")),
    )
    assert (
        emit_blueway_event(
            "blueway_course_launch_allowed",
            trace_id=request_trace_id(),
            reason_code="ready",
            outcome="allowed",
        )
        is None
    )
    assert (
        emit_blueway_event(
            "blueway_sync_failed",
            trace_id=request_trace_id(),
            reason_code="invented_reason",  # type: ignore[arg-type]
            outcome="failed",
        )
        is None
    )
