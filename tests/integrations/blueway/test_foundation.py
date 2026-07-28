from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import copy
import os
from pathlib import Path
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from deeptutor.courses.repository import CourseConflictError, CourseRepository
from deeptutor.integrations.blueway import config as blueway_config
from deeptutor.integrations.blueway.config import BlueWaySettings, IntegrationConfigurationError
from deeptutor.integrations.blueway.credentials import CredentialError, CredentialStore
from deeptutor.integrations.blueway.refresh import (
    RefreshReceiptCoordinator,
    RefreshResult,
    RefreshReuseError,
)
from deeptutor.integrations.blueway.repository import BlueWayRepository
from deeptutor.integrations.blueway.service import BlueWayService, BlueWayUnavailableError
from deeptutor.integrations.blueway.snapshot import (
    MAX_PAGE_BYTES,
    SnapshotValidationError,
    canonical_snapshot_hash,
    validate_snapshot,
    validate_snapshot_fixture,
)
from deeptutor.integrations.blueway.transport import (
    BlueWayAuthorityError,
    BlueWayAuthorizationPending,
    BlueWayTransportError,
    DeviceAuthorization,
    HttpBlueWayTransport,
    TokenExchange,
)
from deeptutor.multi_user import identity as user_identity
from deeptutor.services.path_service import PathService


class FakeTransport:
    def __init__(self) -> None:
        self.fail_revoke = False
        self.revocations: list[str] = []

    def begin_device_authorization(self, *, client_id: str, audience: str, device_code: str, user_code: str, pkce_challenge: str) -> DeviceAuthorization:
        assert client_id == "client-test"
        assert audience == "client-test"
        assert len(pkce_challenge) >= 43
        return DeviceAuthorization(device_code, user_code, "https://blueway.example/verify", 4_102_444_800.0, "11111111-1111-4111-8111-111111111111")

    def revoke(self, *, refresh_token: str) -> None:
        self.revocations.append(refresh_token)
        if self.fail_revoke:
            raise RuntimeError("offline")
        assert refresh_token in {"refresh-secret", "next-refresh"}

    def refresh(self, *, refresh_token: str, rotation_request_id: str) -> TokenExchange:
        assert refresh_token in {"refresh-secret", "next-refresh"}
        assert rotation_request_id.count("-") == 4
        return TokenExchange("grant-a", "subject-a", "access-token", "2026-07-23T00:00:00Z", "next-refresh")

    def fetch_snapshot(self, *, access_token: str, cursor: str | None) -> dict:
        assert access_token == "access-token" and cursor is None
        return _snapshot()


def _snapshot() -> dict:
    payload = {
        "schema_version": 1, "snapshot_id": "bws_" + "c" * 64, "snapshot_revision": 1,
        "generated_at": "2026-07-22T00:00:00Z", "complete": True, "next_cursor": None,
        "datasets": {
            "courses": [{"id": "course-same-title-a", "course_id": "course-same-title-a", "title": "History"}, {"id": "course-same-title-b", "course_id": "course-same-title-b", "title": "History"}],
            "class_meetings": [], "schedule_events": [], "assignments": [], "class_notes": [],
            "class_links": [], "course_profiles": [], "syllabus_facts": [], "source_texts": [],
            "capture_metadata": [], "capture_notes": [],
            "transcripts": [
                {
                    "id": "tx-1",
                    "course_id": "course-same-title-a",
                    "layer": "raw",
                    "segments": [
                        {"start_ms": 0, "end_ms": 1, "text": "Course transcript."}
                    ],
                },
                {
                    "id": "tx-2",
                    "course_id": "course-same-title-b",
                    "layer": "raw",
                    "segments": [
                        {"start_ms": 0, "end_ms": 1, "text": "Course transcript."}
                    ],
                },
            ],
        }, "unavailable": [],
    }
    for records in payload["datasets"].values():
        for record in records:
            record.update({"state": "current", "revision": "a" * 64, "content_sha256": "a" * 64})
    payload["payload_sha256"] = canonical_snapshot_hash(payload)
    return payload


def _service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[BlueWayService, CourseRepository]:
    courses = CourseRepository(tmp_path / "courses.db", "owner-a")
    paths = PathService(tmp_path / "workspace")
    service = BlueWayService(BlueWaySettings(enabled=True, base_url="https://blueway.example", client_id="client-test", master_key=b"k" * 32), FakeTransport())
    monkeypatch.setattr("deeptutor.integrations.blueway.service.get_current_user_or_none", lambda: SimpleNamespace(id="owner-a"))
    monkeypatch.setattr("deeptutor.integrations.blueway.service._current_personal_user", lambda _owner: SimpleNamespace(id="owner-a"))
    monkeypatch.setattr("deeptutor.integrations.blueway.service.get_current_course_service", lambda: SimpleNamespace(repository=courses))
    monkeypatch.setattr("deeptutor.integrations.blueway.service.get_personal_path_service", lambda _owner: paths)
    return service, courses


def test_credential_store_binds_owner_connection_scope_and_permissions(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "credentials", b"k" * 32)
    store.write(owner_user_id="owner-a", connection_id="bwc_a", scope_version="academic.read.v1", refresh_token="secret")
    path = tmp_path / "credentials" / "bwc_a.enc"
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert store.read(owner_user_id="owner-a", connection_id="bwc_a", scope_version="academic.read.v1") == "secret"
    with pytest.raises(CredentialError):
        store.read(owner_user_id="owner-b", connection_id="bwc_a", scope_version="academic.read.v1")
    path.write_bytes(b"tampered")
    with pytest.raises(CredentialError):
        store.read(owner_user_id="owner-a", connection_id="bwc_a", scope_version="academic.read.v1")


def test_credential_store_rejects_symlink_and_hardlink_targets(tmp_path: Path) -> None:
    root = tmp_path / "credentials"
    store = CredentialStore(root, b"k" * 32)
    store.write(owner_user_id="owner-a", connection_id="bwc_a", scope_version="academic.read.v1", refresh_token="secret")
    target = root / "bwc_a.enc"
    target.unlink()
    target.symlink_to(tmp_path / "outside.enc")
    with pytest.raises(CredentialError):
        store.read(owner_user_id="owner-a", connection_id="bwc_a", scope_version="academic.read.v1")
    target.unlink()
    source = tmp_path / "source.enc"
    source.write_bytes(b"not-a-private-credential")
    os.link(source, target)
    with pytest.raises(CredentialError):
        store.read(owner_user_id="owner-a", connection_id="bwc_a", scope_version="academic.read.v1")


def test_credential_store_rejects_symlinked_root(tmp_path: Path) -> None:
    backing = tmp_path / "backing"
    backing.mkdir()
    root = tmp_path / "credentials"
    root.symlink_to(backing, target_is_directory=True)
    with pytest.raises(CredentialError):
        CredentialStore(root, b"k" * 32).write(
            owner_user_id="owner-a", connection_id="bwc_a", scope_version="academic.read.v1", refresh_token="secret"
        )


def test_credential_deletions_fsync_only_after_an_actual_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = CredentialStore(tmp_path / "credentials", b"k" * 32)
    store.write(
        owner_user_id="owner-a", connection_id="bwc_a",
        scope_version="academic.read.v1", refresh_token="secret",
    )
    store.write_rotation_envelope(
        owner_user_id="owner-a", connection_id="bwc_a",
        scope_version="academic.read.v1", refresh_token="secret",
        rotation_request_id="rotation-a",
    )
    fsyncs: list[bool] = []
    monkeypatch.setattr(store, "_fsync_root", lambda: fsyncs.append(True))
    store.remove("bwc_a")
    assert fsyncs == [True]
    store.remove("bwc_a")
    assert fsyncs == [True]

    store.write_rotation_envelope(
        owner_user_id="owner-a", connection_id="bwc_a",
        scope_version="academic.read.v1", refresh_token="secret",
        rotation_request_id="rotation-b",
    )
    fsyncs.clear()
    store.clear_rotation_envelope("bwc_a")
    assert fsyncs == [True]
    store.clear_rotation_envelope("bwc_a")
    assert fsyncs == [True]


def test_mapping_is_exact_id_not_title_and_course_creation_is_atomic(tmp_path: Path) -> None:
    repository = BlueWayRepository(CourseRepository(tmp_path / "courses.db", "owner-a"))
    connection = repository.create_active_connection(external_subject="subject-a", scope_version="academic.read.v1")
    first = repository.create_course_map(connection_id=connection.id, external_course_id="course-a", remote_title="History", remote_state="active", remote_hash="a" * 64, snapshot_id="bws-1", expected_generation=connection.grant_generation)
    second = repository.create_course_map(connection_id=connection.id, external_course_id="course-b", remote_title="History", remote_state="active", remote_hash="b" * 64, snapshot_id="bws-1", expected_generation=connection.grant_generation)
    replay = repository.create_course_map(connection_id=connection.id, external_course_id="course-a", remote_title="Renamed remotely", remote_state="active", remote_hash="a" * 64, snapshot_id="bws-1", expected_generation=connection.grant_generation)
    assert first.id != second.id
    assert replay.id == first.id and replay.title == "History"


def test_pairing_refuses_a_second_provider_grant_until_the_local_connection_is_terminal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, _courses = _service(tmp_path, monkeypatch)
    starts = [0]
    original = service.transport.begin_device_authorization

    def begin(**kwargs):
        starts[0] += 1
        return original(**kwargs)

    service.transport.begin_device_authorization = begin
    first = service.start_connection()
    with pytest.raises(CourseConflictError, match="pending"):
        service.start_connection()
    assert starts == [1]
    service.complete_connection_for_transport(
        attempt_id=first.id,
        exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"),
    )
    with pytest.raises(CourseConflictError, match="Disconnect"):
        service.start_connection()
    assert starts == [1]
    repository = BlueWayRepository(_courses)
    live = repository.visible_connection()
    assert live is not None
    repository.begin_disconnect(live.id, expected_revision=live.revision)
    with pytest.raises(CourseConflictError, match="Disconnect"):
        service.start_connection()
    assert starts == [1]


def test_approval_url_is_an_explicit_pinned_deployment_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(blueway_config.auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(blueway_config, "is_pocketbase_enabled", lambda: False)
    monkeypatch.setenv("TEEECHR_BLUEWAY_INTEGRATION_ENABLED", "true")
    monkeypatch.setenv("TEEECHR_BLUEWAY_BASE_URL", "https://api.blueway.example")
    monkeypatch.setenv("TEEECHR_BLUEWAY_CLIENT_ID", "client-test")
    monkeypatch.setenv("TEEECHR_BLUEWAY_API_SECRET", "s" * 32)
    monkeypatch.setenv("TEEECHR_BLUEWAY_APPROVAL_URL", "https://consent.blueway.example/approve")
    monkeypatch.setenv("TEEECHR_INTEGRATION_MASTER_KEY", base64.b64encode(b"k" * 32).decode())
    settings = BlueWaySettings.from_environment()
    assert settings.approval_url == "https://consent.blueway.example/approve"
    monkeypatch.setenv("TEEECHR_BLUEWAY_APPROVAL_URL", "https://user:pass@consent.blueway.example/approve")
    with pytest.raises(IntegrationConfigurationError, match="approval URL"):
        BlueWaySettings.from_environment()
    monkeypatch.setenv("TEEECHR_BLUEWAY_APPROVAL_URL", "https://consent.blueway.example")
    with pytest.raises(IntegrationConfigurationError, match="approval URL"):
        BlueWaySettings.from_environment()


def test_http_pairing_rejects_chunked_oversize_and_preserves_authorization_pending() -> None:
    settings = BlueWaySettings(
        enabled=True, base_url="https://api.blueway.example", client_id="client-test",
        api_secret="s" * 32, approval_url="https://consent.blueway.example/approve", master_key=b"k" * 32,
    )

    class Oversize(httpx.SyncByteStream):
        def __iter__(self):
            yield b"{"
            yield b"x" * MAX_PAGE_BYTES

        def close(self) -> None:
            pass

    seen_headers: list[httpx.Headers] = []

    def oversized_response(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers)
        return httpx.Response(200, stream=Oversize())

    oversized = HttpBlueWayTransport(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(oversized_response)),
    )
    with pytest.raises(BlueWayTransportError, match="byte limit"):
        oversized.begin_device_authorization(
            client_id="client-test", audience="client-test", device_code="device", user_code="user", pkce_challenge="challenge",
        )
    assert seen_headers[0]["x-teeechr-integration-secret"] == "s" * 32
    assert "apikey" not in seen_headers[0]

    pending = HttpBlueWayTransport(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(202, json={"error": "authorization_pending"}))),
    )
    with pytest.raises(BlueWayAuthorizationPending):
        pending.exchange(request_id="request", device_code="device", code_verifier="verifier")


def test_slow_pairing_provider_does_not_hold_identity_lock_or_allow_duplicate_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, _courses = _service(tmp_path, monkeypatch)
    entered, release = threading.Event(), threading.Event()

    class BlockingStart(FakeTransport):
        def begin_device_authorization(self, **kwargs) -> DeviceAuthorization:
            entered.set()
            assert release.wait(5)
            return super().begin_device_authorization(**kwargs)

    service.transport = BlockingStart()
    result: dict[str, object] = {}

    def start() -> None:
        result["attempt"] = service.start_connection()

    thread = threading.Thread(target=start)
    thread.start()
    assert entered.wait(5)
    lock = user_identity.identity_write_lock()
    assert lock.acquire(blocking=False)
    lock.release()
    with pytest.raises(CourseConflictError, match="already pending"):
        service.start_connection()
    release.set()
    thread.join(5)
    assert not thread.is_alive() and isinstance(result["attempt"], object)


def test_owner_disable_during_exchange_revokes_uncommitted_remote_grant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, courses = _service(tmp_path, monkeypatch)
    attempt = service.start_connection()
    entered, release = threading.Event(), threading.Event()
    active = [True]

    class BlockingExchange(FakeTransport):
        def exchange(self, **_kwargs) -> TokenExchange:
            entered.set()
            assert release.wait(5)
            return TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret")

    transport = BlockingExchange()
    service.transport = transport

    def owner_check(_owner: str) -> None:
        if not active[0]:
            raise BlueWayUnavailableError("disabled")

    monkeypatch.setattr(service, "_assert_owner_current", owner_check)
    result: dict[str, object] = {}

    def exchange() -> None:
        try:
            service.exchange_connection_for_transport(attempt_id=attempt.id)
        except Exception as exc:  # noqa: BLE001 - capture the exact cross-thread result.
            result["error"] = exc

    thread = threading.Thread(target=exchange)
    thread.start()
    assert entered.wait(5)
    lock = user_identity.identity_write_lock()
    assert lock.acquire(blocking=False)
    active[0] = False
    lock.release()
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert isinstance(result.get("error"), BlueWayUnavailableError)
    assert transport.revocations == ["refresh-secret"]
    assert BlueWayRepository(courses).visible_connection() is None


def test_pending_pairing_poll_does_not_queue_until_the_provider_approves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class PendingThenApproved(FakeTransport):
        approved = False

        def exchange(self, *, request_id: str, device_code: str, code_verifier: str) -> TokenExchange:
            if not self.approved:
                raise BlueWayAuthorizationPending("waiting")
            return TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret")

    service, _courses = _service(tmp_path, monkeypatch)
    service.transport = PendingThenApproved()
    attempt = service.start_connection()
    assert service.poll_connection(attempt_id=attempt.id) == (None, None)
    service.transport.approved = True
    scheduled: list[str] = []
    monkeypatch.setattr(service, "schedule_sync", lambda run: scheduled.append(run.id))
    connection, run = service.poll_connection(attempt_id=attempt.id)
    assert connection is not None and run is not None and scheduled == [run.id]


def test_disconnect_wins_the_generation_fence_before_late_course_map(tmp_path: Path) -> None:
    repository = BlueWayRepository(CourseRepository(tmp_path / "courses.db", "owner-a"))
    connection = repository.create_active_connection(external_subject="subject-a", scope_version="academic.read.v1")
    repository.begin_disconnect(connection.id, expected_revision=connection.revision)
    with pytest.raises(CourseConflictError, match="no longer writable"):
        repository.create_course_map(
            connection_id=connection.id, external_course_id="course-a", remote_title="History",
            remote_state="active", remote_hash="a" * 64, snapshot_id="bws-1",
            expected_generation=connection.grant_generation,
        )


def test_disconnect_fences_before_remote_revoke_and_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, courses = _service(tmp_path, monkeypatch)
    paths = PathService(tmp_path / "workspace")
    fake = service.transport
    attempt = service.start_connection()
    connection = service.complete_connection_for_transport(attempt_id=attempt.id, exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"))
    queued = service.queue_sync()
    fake.fail_revoke = True
    with pytest.raises(RuntimeError, match="offline"):
        service.disconnect(expected_revision=connection.revision)
    repository = BlueWayRepository(courses)
    pending = repository.visible_connection()
    assert pending is not None and pending.state == "revocation_pending" and pending.grant_generation == 2
    assert repository.get_run(queued.id).state == "cancelled"
    assert (paths.get_integration_credentials_dir() / f"{connection.id}.enc").exists()
    fake.fail_revoke = False
    finished = service.disconnect(expected_revision=pending.revision)
    assert finished.state == "disconnected"
    assert not (paths.get_integration_credentials_dir() / f"{connection.id}.enc").exists()


def test_durable_sync_mirrors_exact_courses_and_unlinked_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, courses = _service(tmp_path, monkeypatch)
    attempt = service.start_connection()
    service.complete_connection_for_transport(attempt_id=attempt.id, exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"))
    completed = service.run_queued_sync(run_id=service.queue_sync().id)
    repository = BlueWayRepository(courses)
    assert completed.state == "completed" and completed.counts["courses"] == 2
    assert len(courses.list_courses()) == 2
    generated = [[source for source in courses.list_sources(course.id) if source.kind == "blueway snapshot"] for course in courses.list_courses()]
    assert all(len(sources) == 1 and sources[0].state == "ready" for sources in generated)
    assert len({sources[0].operation_id for sources in generated}) == 2
    assert all(len(str(sources[0].idempotency_key)) <= 160 for sources in generated)


def test_snapshot_is_offline_bounded_and_rejects_raw_audio() -> None:
    snapshot = _snapshot()
    assert validate_snapshot(snapshot)["datasets"]["courses"][1]["id"] == "course-same-title-b"
    snapshot["datasets"]["transcripts"][0]["audio_url"] = "https://example.test/raw.m4a"
    snapshot["payload_sha256"] = canonical_snapshot_hash(snapshot)
    with pytest.raises(ValueError, match="undeclared"):
        validate_snapshot(snapshot)
    snapshot = _snapshot()
    snapshot["snapshot_id"] = "bad"
    snapshot["payload_sha256"] = canonical_snapshot_hash(snapshot)
    with pytest.raises(ValueError, match="identity"):
        validate_snapshot(snapshot)
    snapshot = _snapshot()
    snapshot["datasets"]["courses"][0]["content_sha256"] = "not-a-hash"
    snapshot["payload_sha256"] = canonical_snapshot_hash(snapshot)
    with pytest.raises(ValueError, match="identity or hash"):
        validate_snapshot(snapshot)
    snapshot = _snapshot()
    snapshot["snapshot_id"] = "bws_" + "C" * 64
    snapshot["payload_sha256"] = canonical_snapshot_hash(snapshot)
    with pytest.raises(ValueError, match="identity"):
        validate_snapshot(snapshot)
    snapshot = _snapshot()
    snapshot["datasets"]["courses"][0]["revision"] = "B" * 64
    snapshot["payload_sha256"] = canonical_snapshot_hash(snapshot)
    with pytest.raises(ValueError, match="identity or hash"):
        validate_snapshot(snapshot)
    snapshot = _snapshot()
    snapshot["datasets"]["courses"][0]["state"] = "archived"
    snapshot["payload_sha256"] = canonical_snapshot_hash(snapshot)
    with pytest.raises(ValueError, match="course identity/title"):
        validate_snapshot(snapshot)
    snapshot = _snapshot()
    transcript = snapshot["datasets"]["transcripts"][0]
    transcript.update({"duration_ms": 100, "language": "en", "segments": [{"start_ms": 90, "end_ms": 80, "text": "bad"}]})
    snapshot["payload_sha256"] = canonical_snapshot_hash(snapshot)
    with pytest.raises(ValueError, match="segment"):
        validate_snapshot(snapshot)
    snapshot = _snapshot()
    snapshot["datasets"]["assignments"] = [{"id": "a", "state": "current", "revision": "a" * 64, "content_sha256": "a" * 64, "title": {"unsafe": True}}]
    snapshot["payload_sha256"] = canonical_snapshot_hash(snapshot)
    with pytest.raises(ValueError, match="optional field"):
        validate_snapshot(snapshot)


@pytest.mark.parametrize("mutate", [
    lambda payload: payload["datasets"]["courses"][0].__setitem__("title", 123),
    lambda payload: payload["datasets"]["courses"][0].__setitem__("revision", 7),
    lambda payload: payload["datasets"]["courses"][0].__setitem__("content_sha256", 7),
    lambda payload: payload["datasets"]["courses"][0].__setitem__("state", {}),
])
def test_snapshot_rejects_wrong_scalar_provenance_types(mutate) -> None:
    payload = _snapshot()
    mutate(payload)
    payload["payload_sha256"] = canonical_snapshot_hash(payload)
    with pytest.raises(ValueError):
        validate_snapshot(payload)


def test_snapshot_rejects_transcript_time_ordering() -> None:
    payload = _snapshot()
    transcript = payload["datasets"]["transcripts"][0]
    transcript.update({"duration_ms": 100, "recorded_at": "2026-01-02T00:00:00Z", "stopped_at": "2026-01-01T00:00:00Z", "segments": [{"start_ms": 50, "end_ms": 60, "text": "a"}, {"start_ms": 40, "end_ms": 70, "text": "b"}]})
    payload["payload_sha256"] = canonical_snapshot_hash(payload)
    with pytest.raises(ValueError):
        validate_snapshot(payload)


@pytest.mark.parametrize("mutate", [
    lambda payload: payload.__setitem__("snapshot_revision", True),
    lambda payload: payload.__setitem__("unavailable", [{"dataset": [], "reason": "temporary"}]),
    lambda payload: payload["datasets"]["transcripts"][0].__setitem__("duration_ms", 14_400_001),
    lambda payload: payload["datasets"]["transcripts"][0].update({
        "recorded_at": "2026-01-01T00:00:00", "stopped_at": "2026-01-01T00:01:00Z",
    }),
])
def test_snapshot_type_errors_always_fail_with_the_typed_validator(mutate) -> None:
    payload = _snapshot()
    mutate(payload)
    payload["payload_sha256"] = canonical_snapshot_hash(payload)
    with pytest.raises(SnapshotValidationError):
        validate_snapshot(payload)


def test_malformed_snapshot_leaves_the_durable_run_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MalformedSnapshot(FakeTransport):
        def fetch_snapshot(self, *, access_token: str, cursor: str | None) -> dict:
            payload = _snapshot()
            payload["datasets"]["courses"][0]["state"] = {}
            payload["payload_sha256"] = canonical_snapshot_hash(payload)
            return payload

    service, courses = _service(tmp_path, monkeypatch)
    service.transport = MalformedSnapshot()
    attempt = service.start_connection()
    service.complete_connection_for_transport(
        attempt_id=attempt.id,
        exchange=TokenExchange(
            "grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret",
        ),
    )
    run = service.queue_sync()
    with pytest.raises(SnapshotValidationError):
        service.run_queued_sync(run_id=run.id)
    failed = BlueWayRepository(courses).get_run(run.id)
    assert failed.state == "failed" and failed.error_code == "SnapshotValidationError"


def test_complete_missing_course_archives_but_unavailable_or_partial_does_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, courses = _service(tmp_path, monkeypatch)
    attempt = service.start_connection()
    service.complete_connection_for_transport(attempt_id=attempt.id, exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"))
    assert service.run_queued_sync(run_id=service.queue_sync().id).state == "completed"
    class Missing(FakeTransport):
        def fetch_snapshot(self, *, access_token: str, cursor: str | None) -> dict:
            payload = copy.deepcopy(_snapshot())
            payload["snapshot_id"] = "bws_" + "e" * 64
            payload["snapshot_revision"] = 2
            payload["datasets"]["courses"] = []
            payload["datasets"]["transcripts"] = []
            payload["payload_sha256"] = canonical_snapshot_hash(payload)
            return payload
    service.transport = Missing()
    assert service.run_queued_sync(run_id=service.queue_sync().id).state == "completed"
    repository = BlueWayRepository(courses)
    with courses._connect() as conn:  # noqa: SLF001
        states = [row["remote_state"] for row in conn.execute("SELECT remote_state FROM blueway_course_maps")]
    assert states == ["archived", "archived"]
    assert len(courses.list_courses()) == 2
    assert all(not [source for source in courses.list_sources(course.id) if source.state == "ready"] for course in courses.list_courses())

    # Start a clean connection so the non-authoritative snapshots have active
    # remote rows and ready local bundles to protect.
    service, courses = _service(tmp_path / "preserve", monkeypatch)

    class AssignmentInitial(FakeTransport):
        def fetch_snapshot(self, *, access_token: str, cursor: str | None) -> dict:
            payload = _snapshot()
            payload["datasets"]["assignments"] = [{
                "id": "assignment-1", "course_id": "course-same-title-a", "title": "Essay",
                "due_at": None, "details": "", "submission_method": "", "grading_note": "", "status": "open",
                "state": "current", "revision": "a" * 64, "content_sha256": "a" * 64,
            }]
            payload["payload_sha256"] = canonical_snapshot_hash(payload)
            return payload

    service.transport = AssignmentInitial()
    attempt = service.start_connection()
    service.complete_connection_for_transport(attempt_id=attempt.id, exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"))
    assert service.run_queued_sync(run_id=service.queue_sync().id).state == "completed"

    class CoursesUnavailable(FakeTransport):
        def fetch_snapshot(self, *, access_token: str, cursor: str | None) -> dict:
            payload = copy.deepcopy(_snapshot())
            payload["snapshot_id"] = "bws_" + "f" * 64
            payload["snapshot_revision"] = 2
            payload["datasets"]["courses"] = []
            payload["datasets"]["assignments"] = []
            payload["unavailable"] = [{"dataset": "courses", "reason": "temporary provider gap"}]
            payload["payload_sha256"] = canonical_snapshot_hash(payload)
            return payload

    service.transport = CoursesUnavailable()
    assert service.run_queued_sync(run_id=service.queue_sync().id).state == "completed"
    repository = BlueWayRepository(courses)
    with courses._connect() as conn:  # noqa: SLF001
        assert [row["remote_state"] for row in conn.execute("SELECT remote_state FROM blueway_course_maps")] == ["active", "active"]
        transcript_rows = list(
            conn.execute(
                "SELECT state, course_id FROM blueway_records WHERE connection_id = ? AND record_kind = 'transcripts'",
                (repository.active_connection().id,),
            )
        )
        assert len(transcript_rows) == 2
        assert all(
            row["state"] == "current" and row["course_id"] is not None for row in transcript_rows
        )
        assignment = conn.execute(
            "SELECT state, current_source_id FROM blueway_records WHERE record_kind = 'assignments' AND external_record_id = 'assignment-1'"
        ).fetchone()
        assert assignment is not None and assignment["state"] == "archived"
        archived_source = conn.execute("SELECT state FROM course_sources WHERE id = ?", (assignment["current_source_id"],)).fetchone()
        assert archived_source is not None and archived_source["state"] == "archived"
    assert all(len([source for source in courses.list_sources(course.id) if source.state == "ready"]) == 1 for course in courses.list_courses())

    class Partial(FakeTransport):
        def fetch_snapshot(self, *, access_token: str, cursor: str | None) -> dict:
            payload = copy.deepcopy(_snapshot())
            payload["snapshot_id"] = "bws_" + "1" * 64
            payload["snapshot_revision"] = 3
            payload["complete"] = False
            payload["next_cursor"] = "next-page"
            payload["payload_sha256"] = canonical_snapshot_hash(payload)
            return payload

    service.transport = Partial()
    partial = service.queue_sync()
    with pytest.raises(ValueError, match="complete stable snapshot"):
        service.run_queued_sync(run_id=partial.id)
    assert repository.get_run(partial.id).state == "failed"
    with courses._connect() as conn:  # noqa: SLF001
        assert [row["remote_state"] for row in conn.execute("SELECT remote_state FROM blueway_course_maps")] == ["active", "active"]
    assert all(len([source for source in courses.list_sources(course.id) if source.state == "ready"]) == 1 for course in courses.list_courses())


def test_fifty_owner_repositories_are_isolated_under_concurrent_local_operations(tmp_path: Path) -> None:
    def create(index: int) -> tuple[str, str]:
        owner = f"owner-{index:02d}"
        repo = BlueWayRepository(CourseRepository(tmp_path / owner / "courses.db", owner))
        connection = repo.create_active_connection(external_subject=f"subject-{index}", scope_version="academic.read.v1")
        visible = repo.visible_connection()
        assert visible is not None and visible.id == connection.id
        return owner, repo.get_connection(connection.id).owner_user_id
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(create, range(50)))
    assert results == [(f"owner-{index:02d}", f"owner-{index:02d}") for index in range(50)]
    assert len({tmp_path / owner / "courses.db" for owner, _ in results}) == 50


def test_reconnect_rebinds_same_subject_but_never_cross_subject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, courses = _service(tmp_path, monkeypatch)
    first_attempt = service.start_connection()
    first_connection = service.complete_connection_for_transport(
        attempt_id=first_attempt.id,
        exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"),
    )
    assert service.run_queued_sync(run_id=service.queue_sync().id).state == "completed"
    original_course_ids = {course.id for course in courses.list_courses()}
    assert service.disconnect(expected_revision=first_connection.revision).state == "disconnected"

    second_attempt = service.start_connection()
    service.complete_connection_for_transport(
        attempt_id=second_attempt.id,
        exchange=TokenExchange("grant-b", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"),
    )
    assert service.run_queued_sync(run_id=service.queue_sync().id).state == "completed"
    assert {course.id for course in courses.list_courses()} == original_course_ids

    second_connection = BlueWayRepository(courses).active_connection()
    assert second_connection is not None
    with courses._connect() as conn:  # noqa: SLF001
        rebound_ids = {
            row["course_id"]
            for row in conn.execute(
                "SELECT course_id FROM blueway_course_maps WHERE connection_id = ?",
                (second_connection.id,),
            )
        }
    assert rebound_ids == original_course_ids
    assert all(
        len([source for source in courses.list_sources(course.id) if source.state == "ready"]) == 1
        for course in courses.list_courses()
    )
    with courses._connect() as conn:  # noqa: SLF001
        rebound_source_ids = {
            row["current_source_id"]
            for row in conn.execute(
                "SELECT current_source_id FROM blueway_records WHERE connection_id = ? AND record_kind = 'transcripts'",
                (second_connection.id,),
            )
        }
    assert all(rebound_source_ids & {source.id for source in courses.list_sources(course.id)} for course in courses.list_courses())

    assert service.disconnect(expected_revision=second_connection.revision).state == "disconnected"
    third_attempt = service.start_connection()
    service.complete_connection_for_transport(
        attempt_id=third_attempt.id,
        exchange=TokenExchange("grant-c", "subject-b", "access", "2026-07-23T00:00:00Z", "refresh-secret"),
    )
    assert service.run_queued_sync(run_id=service.queue_sync().id).state == "completed"
    cross_subject_ids = {course.id for course in courses.list_courses()} - original_course_ids
    assert len(cross_subject_ids) == 2


def test_same_snapshot_id_with_different_verified_hash_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, courses = _service(tmp_path, monkeypatch)
    attempt = service.start_connection()
    service.complete_connection_for_transport(
        attempt_id=attempt.id,
        exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"),
    )
    assert service.run_queued_sync(run_id=service.queue_sync().id).state == "completed"

    class DifferentProvenance(FakeTransport):
        def fetch_snapshot(self, *, access_token: str, cursor: str | None) -> dict:
            payload = _snapshot()
            payload["datasets"]["courses"][0]["title"] = "History rewritten"
            payload["payload_sha256"] = canonical_snapshot_hash(payload)
            return payload

    service.transport = DifferentProvenance()
    rejected = service.queue_sync()
    with pytest.raises(CourseConflictError, match="different provenance"):
        service.run_queued_sync(run_id=rejected.id)
    assert BlueWayRepository(courses).get_run(rejected.id).state == "failed"


def test_owner_disabled_before_final_bundle_commit_fails_without_ready_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, courses = _service(tmp_path, monkeypatch)
    attempt = service.start_connection()
    service.complete_connection_for_transport(
        attempt_id=attempt.id,
        exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"),
    )
    checks = [0]

    def owner_check(_owner: str) -> None:
        checks[0] += 1
        if checks[0] == 4:
            raise BlueWayUnavailableError("disabled before final commit")

    monkeypatch.setattr(service, "_assert_owner_current", owner_check)
    run = service.queue_sync()
    with pytest.raises(RuntimeError, match="bundle"):
        service.run_queued_sync(run_id=run.id)
    assert BlueWayRepository(courses).get_run(run.id).state == "failed"
    assert all(not [source for source in courses.list_sources(course.id) if source.state == "ready"] for course in courses.list_courses())


def test_owner_disabled_queued_run_is_terminalized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, courses = _service(tmp_path, monkeypatch)
    attempt = service.start_connection()
    service.complete_connection_for_transport(
        attempt_id=attempt.id,
        exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"),
    )
    monkeypatch.setattr(service, "_assert_owner_current", lambda _owner: (_ for _ in ()).throw(BlueWayUnavailableError("disabled")))
    run = service.queue_sync()
    with pytest.raises(BlueWayUnavailableError, match="disabled"):
        service.run_queued_sync(run_id=run.id)
    assert BlueWayRepository(courses).get_run(run.id).state == "failed"


def test_identity_lock_linearizes_final_bundle_commit_and_account_disable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The final ready transition and identity disable have one deterministic order."""
    users_file = tmp_path / "identity" / "users.json"
    monkeypatch.setattr(user_identity, "USERS_FILE", users_file)
    user_identity._write_users({  # noqa: SLF001 - exercises the real identity mutation lock.
        "owner": {"id": "owner-a", "hash": "hash", "role": "user", "created_at": "", "disabled": False, "avatar": ""},
    })
    service, courses = _service(tmp_path / "race", monkeypatch)
    from deeptutor.courses import ingestion

    monkeypatch.setattr("deeptutor.integrations.blueway.service._current_personal_user", ingestion._current_personal_user)
    attempt = service.start_connection()
    service.complete_connection_for_transport(
        attempt_id=attempt.id,
        exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"),
    )
    entered, release, delete_started, delete_done = (threading.Event() for _ in range(4))
    original_commit = BlueWayRepository.commit_bundle_sources

    def pause_inside_final_commit(self, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(BlueWayRepository, "commit_bundle_sources", pause_inside_final_commit)
    result: dict[str, object] = {}

    def sync() -> None:
        result["run"] = service.run_queued_sync(run_id=service.queue_sync().id)

    def disable() -> None:
        delete_started.set()
        result["disabled"] = user_identity.delete_user("owner")
        delete_done.set()

    sync_thread = threading.Thread(target=sync)
    sync_thread.start()
    assert entered.wait(5)
    assert not user_identity.identity_write_lock().acquire(blocking=False)
    disable_thread = threading.Thread(target=disable)
    disable_thread.start()
    assert delete_started.wait(5)
    assert not delete_done.is_set()
    release.set()
    sync_thread.join(5)
    disable_thread.join(5)
    assert not sync_thread.is_alive() and not disable_thread.is_alive()
    assert result["run"].state == "completed"  # type: ignore[union-attr]
    assert result["disabled"] is True
    assert user_identity.get_user("owner")["disabled"] is True
    assert all(len([source for source in courses.list_sources(course.id) if source.state == "ready"]) == 1 for course in courses.list_courses())


def test_blueway_schema_is_idempotent_private_and_has_required_partial_indexes(tmp_path: Path) -> None:
    database = tmp_path / "private" / "courses.db"
    first = BlueWayRepository(CourseRepository(database, "owner-a"))
    with first.courses._connect() as conn:  # noqa: SLF001
        before = list(conn.execute("SELECT type, name, sql FROM sqlite_master WHERE name LIKE 'blueway_%' ORDER BY type, name"))
    second = BlueWayRepository(CourseRepository(database, "owner-a"))
    with second.courses._connect() as conn:  # noqa: SLF001
        after = list(conn.execute("SELECT type, name, sql FROM sqlite_master WHERE name LIKE 'blueway_%' ORDER BY type, name"))
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert list(conn.execute("PRAGMA foreign_key_check")) == []
        connection_indexes = {row[1]: row[4] for row in conn.execute("PRAGMA index_list('blueway_connections')")}
        run_indexes = {row[1]: row[4] for row in conn.execute("PRAGMA index_list('blueway_sync_runs')")}
        assert connection_indexes["blueway_one_live_connection"] == 1
        assert run_indexes["blueway_snapshot_replay"] == 1
        index_sql = {
            row["name"]: row["sql"]
            for row in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND name IN (?, ?)",
                ("blueway_one_live_connection", "blueway_snapshot_replay"),
            )
        }
    assert before == after
    assert "state IN ('active', 'revocation_pending')" in index_sql["blueway_one_live_connection"]
    assert "snapshot_id IS NOT NULL AND state = 'completed'" in index_sql["blueway_snapshot_replay"]
    assert database.stat().st_mode & 0o777 == 0o600


def test_generated_blueway_fixture_validates_with_explicit_unavailable_datasets() -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "blueway" / "academic_snapshot.v1.json"
    snapshot = validate_snapshot_fixture(fixture)
    assert snapshot["payload_sha256"] == "57bdc8c4a79ce2e92afad097e5b55bf82340bf4653415383f8931dbab10f9e74"
    assert snapshot["datasets"]["capture_metadata"][0]["schedule_event_id"] == "schedule-event-chem-a"
    assert {item["dataset"] for item in snapshot["unavailable"]} == {"source_texts", "capture_notes", "transcripts"}


def test_permanent_refresh_authority_loss_removes_credential_and_fences_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, courses = _service(tmp_path, monkeypatch)
    attempt = service.start_connection()
    connection = service.complete_connection_for_transport(attempt_id=attempt.id, exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"))
    class Rejected(FakeTransport):
        def refresh(self, *, refresh_token: str, rotation_request_id: str):
            raise BlueWayAuthorityError("revoked")
    service.transport = Rejected()
    with pytest.raises(BlueWayAuthorityError):
        service.run_queued_sync(run_id=service.queue_sync().id)
    repository = BlueWayRepository(courses)
    assert repository.get_connection(connection.id).state == "error"
    assert not (PathService(tmp_path / "workspace").get_integration_credentials_dir() / f"{connection.id}.enc").exists()


def test_refresh_reuses_one_request_id_then_revokes_late_old_token() -> None:
    class Transport:
        def __init__(self) -> None:
            self.ids: list[str] = []
            self.revoked = False
        def refresh(self, *, refresh_token: str, rotation_request_id: str) -> RefreshResult:
            self.ids.append(rotation_request_id)
            return RefreshResult("access", "new-refresh")
        def revoke_family(self, *, refresh_token: str) -> None:
            self.revoked = True
    now = [100.0]
    coordinator = RefreshReceiptCoordinator(now=lambda: now[0])
    transport = Transport()
    coordinator.refresh(connection_id="bwc", refresh_token="old", transport=transport)
    now[0] = 150.0
    coordinator.refresh(connection_id="bwc", refresh_token="old", transport=transport)
    assert transport.ids[0] == transport.ids[1]
    now[0] = 161.0
    with pytest.raises(RefreshReuseError):
        coordinator.refresh(connection_id="bwc", refresh_token="old", transport=transport)
    assert transport.revoked


def test_rotation_clear_window_never_pairs_predecessor_with_new_receipt(tmp_path: Path) -> None:
    repository = BlueWayRepository(CourseRepository(tmp_path / "courses.db", "owner-a"))
    connection = repository.create_active_connection(external_subject="subject-a", scope_version="academic.read.v1")
    store = CredentialStore(tmp_path / "credentials", b"k" * 32)
    store.write(owner_user_id="owner-a", connection_id=connection.id, scope_version=connection.scope_version, refresh_token="old")
    old_receipt = repository.prepare_rotation(connection.id, expected_generation=connection.grant_generation)
    store.write_rotation_envelope(owner_user_id="owner-a", connection_id=connection.id, scope_version=connection.scope_version, refresh_token="old", rotation_request_id=old_receipt)
    store.write(owner_user_id="owner-a", connection_id=connection.id, scope_version=connection.scope_version, refresh_token="successor")
    repository.clear_rotation(connection.id, expected_generation=connection.grant_generation, request_id=old_receipt)
    new_receipt = repository.prepare_rotation(connection.id, expected_generation=connection.grant_generation)
    assert new_receipt != old_receipt
    assert store.read_rotation_envelope(owner_user_id="owner-a", connection_id=connection.id, scope_version=connection.scope_version, expected_rotation_request_id=new_receipt) is None
    assert store.read(owner_user_id="owner-a", connection_id=connection.id, scope_version=connection.scope_version) == "successor"


def test_bundle_failure_fails_run_instead_of_reporting_completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, courses = _service(tmp_path, monkeypatch)
    attempt = service.start_connection()
    service.complete_connection_for_transport(attempt_id=attempt.id, exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"))
    monkeypatch.setattr("deeptutor.integrations.blueway.bundles.build_index", lambda *_args: False)
    run = service.queue_sync()
    with pytest.raises(RuntimeError):
        service.run_queued_sync(run_id=run.id)
    assert BlueWayRepository(courses).get_run(run.id).state == "failed"


def test_second_of_two_bundle_builds_failing_exposes_no_new_ready_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, courses = _service(tmp_path, monkeypatch)
    attempt = service.start_connection()
    service.complete_connection_for_transport(attempt_id=attempt.id, exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"))
    calls = [0]
    def second_fails(*_args):
        calls[0] += 1
        return calls[0] != 2
    monkeypatch.setattr("deeptutor.integrations.blueway.bundles.build_index", second_fails)
    run = service.queue_sync()
    with pytest.raises(RuntimeError):
        service.run_queued_sync(run_id=run.id)
    assert BlueWayRepository(courses).get_run(run.id).state == "failed"
    assert all(not [source for source in courses.list_sources(course.id) if source.state == "ready"] for course in courses.list_courses())


def test_failed_bundle_retries_same_snapshot_with_one_ready_source_per_course(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, courses = _service(tmp_path, monkeypatch)
    attempt = service.start_connection()
    service.complete_connection_for_transport(attempt_id=attempt.id, exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"))
    original = __import__("deeptutor.integrations.blueway.bundles", fromlist=["build_index"]).build_index
    monkeypatch.setattr("deeptutor.integrations.blueway.bundles.build_index", lambda *_args: False)
    with pytest.raises(RuntimeError):
        service.run_queued_sync(run_id=service.queue_sync().id)
    assert all(source.idempotency_key is None for course in courses.list_courses() for source in courses.list_sources(course.id) if source.state == "failed")
    monkeypatch.setattr("deeptutor.integrations.blueway.bundles.build_index", original)
    assert service.run_queued_sync(run_id=service.queue_sync().id).state == "completed"
    assert all(len([source for source in courses.list_sources(course.id) if source.state == "ready"]) == 1 for course in courses.list_courses())


def test_changed_snapshot_second_bundle_failure_preserves_prior_ready_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, courses = _service(tmp_path, monkeypatch)
    attempt = service.start_connection()
    service.complete_connection_for_transport(attempt_id=attempt.id, exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"))
    first = service.run_queued_sync(run_id=service.queue_sync().id)
    assert first.state == "completed"
    class Changed(FakeTransport):
        def fetch_snapshot(self, *, access_token: str, cursor: str | None) -> dict:
            snapshot = _snapshot()
            snapshot["snapshot_id"] = "bws_" + "d" * 64
            snapshot["snapshot_revision"] = 2
            for record in snapshot["datasets"]["transcripts"]:
                record["revision"] = record["content_sha256"] = "b" * 64
            snapshot["payload_sha256"] = canonical_snapshot_hash(snapshot)
            return snapshot
    service.transport = Changed()
    calls = [0]
    def second_fails(*_args):
        calls[0] += 1
        return calls[0] != 2
    monkeypatch.setattr("deeptutor.integrations.blueway.bundles.build_index", second_fails)
    run = service.queue_sync()
    with pytest.raises(RuntimeError):
        service.run_queued_sync(run_id=run.id)
    assert BlueWayRepository(courses).get_run(run.id).state == "failed"
    assert all(len([source for source in courses.list_sources(course.id) if source.state == "ready"]) == 1 for course in courses.list_courses())


def test_identical_snapshot_replay_is_a_noop_completed_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, _courses = _service(tmp_path, monkeypatch)
    attempt = service.start_connection()
    service.complete_connection_for_transport(attempt_id=attempt.id, exchange=TokenExchange("grant-a", "subject-a", "access", "2026-07-23T00:00:00Z", "refresh-secret"))
    assert service.run_queued_sync(run_id=service.queue_sync().id).state == "completed"
    assert service.run_queued_sync(run_id=service.queue_sync().id).state == "completed"


def test_api_status_is_stable_and_disabled_by_default() -> None:
    from deeptutor.integrations.blueway import router as blueway_router

    app = FastAPI()
    app.include_router(blueway_router.router, prefix="/api/v1/integrations/blueway")
    blueway_router.set_test_service(BlueWayService(BlueWaySettings(enabled=False)))
    try:
        response = TestClient(app).get("/api/v1/integrations/blueway")
    finally:
        blueway_router.set_test_service(None)
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "connection": None, "active_run": None}
