from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.courses.migrations.runner import discover_migrations
from deeptutor.courses.repository import CourseConflictError, CourseRepository
from deeptutor.integrations.blueway import config as blueway_config
from deeptutor.integrations.blueway.config import BlueWaySettings
from deeptutor.integrations.blueway.credential_authority import (
    CredentialAuthorityError,
    PersistentBlueWaySecrets,
    PrivateFileCredentialAuthority,
    resolve_persistent_blueway_secrets,
)
from deeptutor.integrations.blueway.credentials import CredentialStore
from deeptutor.integrations.blueway.repository import BlueWayRepository
from deeptutor.integrations.blueway.service import (
    BlueWayCredentialRecoveryRequired,
    BlueWayService,
)
from deeptutor.integrations.blueway.transport import (
    BlueWayTransportError,
    DeviceAuthorization,
    TokenExchange,
)
from deeptutor.services.path_service import PathService


class RecoveryTransport:
    def __init__(self) -> None:
        self.revocations: list[str] = []
        self.refreshes: list[tuple[str, str]] = []
        self.starts = 0
        self.exchange_calls = 0
        self.exchange_result: TokenExchange | None = None
        self.exchange_error: Exception | None = None
        self.cancellations: list[tuple[str, str]] = []
        self.cancel_result = "cancelled"

    def begin_device_authorization(
        self, *, client_id: str, audience: str, device_code: str,
        user_code: str, pkce_challenge: str,
    ) -> DeviceAuthorization:
        self.starts += 1
        return DeviceAuthorization(
            device_code, user_code, "https://blueway.example/verify",
            4_102_444_800.0, f"request-{self.starts}",
        )

    def revoke(self, *, refresh_token: str) -> None:
        self.revocations.append(refresh_token)

    def refresh(self, *, refresh_token: str, rotation_request_id: str):
        self.refreshes.append((refresh_token, rotation_request_id))
        raise AssertionError("refresh must not run during credential recovery")

    def exchange(self, *, request_id: str, device_code: str, code_verifier: str):
        self.exchange_calls += 1
        if self.exchange_error is not None:
            raise self.exchange_error
        if self.exchange_result is None:
            raise AssertionError("tests inject the approved exchange")
        return self.exchange_result

    def cancel(self, *, request_id: str, device_code: str) -> str:
        self.cancellations.append((request_id, device_code))
        return self.cancel_result

    def fetch_snapshot(self, *, access_token: str, cursor: str | None):
        raise AssertionError("snapshot fetch must not run during credential recovery")


def _settings(key: bytes) -> BlueWaySettings:
    return BlueWaySettings(
        enabled=True,
        base_url="https://blueway.example",
        client_id="client-test",
        api_secret="s" * 32,
        approval_url="https://blueway.example/verify",
        master_key=key,
    )


def _service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, key: bytes,
    transport: RecoveryTransport | None = None,
) -> tuple[BlueWayService, CourseRepository, PathService, RecoveryTransport]:
    courses = CourseRepository(tmp_path / "courses.db", "owner-a")
    paths = PathService(tmp_path / "workspace")
    selected = transport or RecoveryTransport()
    service = BlueWayService(_settings(key), selected)
    monkeypatch.setattr(
        "deeptutor.integrations.blueway.service.get_current_user_or_none",
        lambda: SimpleNamespace(id="owner-a"),
    )
    monkeypatch.setattr(
        "deeptutor.integrations.blueway.service._current_personal_user",
        lambda _owner: SimpleNamespace(id="owner-a"),
    )
    monkeypatch.setattr(
        "deeptutor.integrations.blueway.service.get_current_course_service",
        lambda: SimpleNamespace(repository=courses),
    )
    monkeypatch.setattr(
        "deeptutor.integrations.blueway.service.get_personal_path_service",
        lambda _owner: paths,
    )
    return service, courses, paths, selected


def _connected(
    service: BlueWayService, *, subject: str = "subject-a",
    refresh_token: str = "old-refresh",
):
    attempt = service.start_connection()
    return service.complete_connection_for_transport(
        attempt_id=attempt.id,
        exchange=TokenExchange(
            "grant-a", subject, "access", "2026-07-23T00:00:00Z",
            refresh_token,
        ),
    )


def test_private_secret_authority_is_stable_private_and_exclusive(tmp_path: Path) -> None:
    authority_path = tmp_path / "system" / "blueway-secret-authority.json"
    authority = PrivateFileCredentialAuthority(authority_path)
    expected = PersistentBlueWaySecrets(
        key_id="bwa_test",
        master_key=b"k" * 32,
        api_secret="p" * 48,
    )
    authority.create(expected)

    assert authority.load() == expected
    assert authority_path.stat().st_mode & 0o777 == 0o600
    assert authority_path.parent.stat().st_mode & 0o777 == 0o700
    with pytest.raises(CredentialAuthorityError, match="already exists"):
        authority.create(expected)

    payload = json.loads(authority_path.read_text())
    assert base64.b64decode(payload["master_key_b64"]) == b"k" * 32
    assert payload["schema_version"] == 1


def test_private_secret_authority_rejects_symlink_hardlink_and_permissive_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "authority.json"
    authority = PrivateFileCredentialAuthority(target)
    secrets = PersistentBlueWaySecrets("bwa_test", b"k" * 32, "p" * 48)
    authority.create(secrets)

    target.chmod(0o644)
    with pytest.raises(CredentialAuthorityError):
        authority.load()
    target.chmod(0o600)

    hardlink = tmp_path / "authority-hardlink.json"
    os.link(target, hardlink)
    with pytest.raises(CredentialAuthorityError):
        authority.load()
    hardlink.unlink()

    target.unlink()
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    target.symlink_to(outside)
    with pytest.raises(CredentialAuthorityError):
        authority.load()


def test_legacy_secret_bootstrap_requires_every_existing_envelope_to_decrypt(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    user_root = data_root / "users" / "owner-a" / "user"
    repository = BlueWayRepository(
        CourseRepository(user_root / "courses.db", "owner-a")
    )
    connection = repository.create_active_connection(
        external_subject="subject-a", scope_version="academic.read.v1",
    )
    store = CredentialStore(
        user_root / "integration_credentials", b"k" * 32,
    )
    store.write(
        owner_user_id="owner-a",
        connection_id=connection.id,
        scope_version=connection.scope_version,
        refresh_token="old-refresh",
    )
    authority_path = data_root / "system" / "integrations" / "authority.json"

    with pytest.raises(CredentialAuthorityError, match="owner recovery"):
        resolve_persistent_blueway_secrets(
            authority_path=authority_path,
            data_root=data_root,
            candidate_master_key=b"x" * 32,
            candidate_api_secret="p" * 48,
            allow_bootstrap=True,
            allow_recovery_bootstrap=False,
        )
    assert not authority_path.exists()

    loaded = resolve_persistent_blueway_secrets(
        authority_path=authority_path,
        data_root=data_root,
        candidate_master_key=b"k" * 32,
        candidate_api_secret="p" * 48,
        allow_bootstrap=True,
        allow_recovery_bootstrap=False,
    )
    assert loaded.master_key == b"k" * 32


def test_secret_bootstrap_modes_are_mutually_exclusive(tmp_path: Path) -> None:
    authority_path = (
        tmp_path / "data" / "system" / "integrations" / "authority.json"
    )

    with pytest.raises(CredentialAuthorityError, match="mutually exclusive"):
        resolve_persistent_blueway_secrets(
            authority_path=authority_path,
            data_root=tmp_path / "data",
            candidate_master_key=b"k" * 32,
            candidate_api_secret="p" * 48,
            allow_bootstrap=True,
            allow_recovery_bootstrap=True,
        )

    assert not authority_path.exists()


def test_explicit_recovery_bootstrap_preserves_unreadable_envelope(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    user_root = data_root / "users" / "owner-a" / "user"
    repository = BlueWayRepository(
        CourseRepository(user_root / "courses.db", "owner-a")
    )
    connection = repository.create_active_connection(
        external_subject="subject-a", scope_version="academic.read.v1",
    )
    path = user_root / "integration_credentials" / f"{connection.id}.enc"
    CredentialStore(path.parent, b"k" * 32).write(
        owner_user_id="owner-a",
        connection_id=connection.id,
        scope_version=connection.scope_version,
        refresh_token="old-refresh",
    )
    before = path.read_bytes()

    loaded = resolve_persistent_blueway_secrets(
        authority_path=(
            data_root / "system" / "integrations" / "authority.json"
        ),
        data_root=data_root,
        candidate_master_key=b"x" * 32,
        candidate_api_secret="p" * 48,
        allow_bootstrap=False,
        allow_recovery_bootstrap=True,
    )

    assert loaded.master_key == b"x" * 32
    assert path.read_bytes() == before


def test_environment_bootstrap_becomes_stable_authority_across_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.multi_user import paths as multi_user_paths

    monkeypatch.setattr(blueway_config.auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(blueway_config, "is_pocketbase_enabled", lambda: False)
    monkeypatch.setattr(
        multi_user_paths, "SYSTEM_ROOT", tmp_path / "data" / "system",
    )
    monkeypatch.setenv("TEEECHR_BLUEWAY_INTEGRATION_ENABLED", "true")
    monkeypatch.setenv("TEEECHR_BLUEWAY_BASE_URL", "https://api.blueway.example")
    monkeypatch.setenv("TEEECHR_BLUEWAY_CLIENT_ID", "client-test")
    monkeypatch.setenv(
        "TEEECHR_BLUEWAY_APPROVAL_URL",
        "https://consent.blueway.example/approve",
    )
    monkeypatch.setenv("TEEECHR_BLUEWAY_API_SECRET", "p" * 48)
    monkeypatch.setenv(
        "TEEECHR_INTEGRATION_MASTER_KEY",
        base64.b64encode(b"k" * 32).decode("ascii"),
    )
    monkeypatch.setenv("TEEECHR_INTEGRATION_SECRET_BOOTSTRAP", "true")

    first = BlueWaySettings.from_environment()
    monkeypatch.delenv("TEEECHR_BLUEWAY_API_SECRET")
    monkeypatch.delenv("TEEECHR_INTEGRATION_MASTER_KEY")
    monkeypatch.delenv("TEEECHR_INTEGRATION_SECRET_BOOTSTRAP")
    second = BlueWaySettings.from_environment()

    assert second.master_key == first.master_key == b"k" * 32
    assert second.api_secret == first.api_secret == "p" * 48
    assert second.secret_key_id == first.secret_key_id


def test_existing_phase3a_connection_schema_is_adopted_with_healthy_status(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "courses.db"
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        conn.executescript(discover_migrations()[0].content.decode("utf-8"))
        conn.execute("DROP TABLE schema_migrations")
        conn.execute(
            """
            INSERT INTO blueway_connections (
                id, owner_user_id, external_subject, state, scope_version,
                revision, grant_generation, credential_ref, credential_status,
                created_at, updated_at, connected_at
            ) VALUES (
                'bwc_legacy', 'owner-a', 'subject-a', 'active',
                'academic.read.v1', 3, 4, 'blueway:bwc_legacy', 'healthy',
                1.0, 2.0, 1.0
            )
            """,
        )
    finally:
        conn.close()

    courses = CourseRepository(db_path, "owner-a")
    repository = BlueWayRepository(courses)
    connection = repository.get_connection("bwc_legacy")

    assert connection.credential_status == "healthy"
    assert connection.revision == 3
    assert connection.grant_generation == 4


def test_wrong_key_disconnect_enters_recovery_without_remote_revoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    good, courses, paths, transport = _service(
        tmp_path, monkeypatch, key=b"k" * 32,
    )
    connection = _connected(good)
    queued = good.queue_sync()
    original = (
        paths.get_integration_credentials_dir() / f"{connection.id}.enc"
    ).read_bytes()

    bad = BlueWayService(_settings(b"x" * 32), transport)
    with pytest.raises(BlueWayCredentialRecoveryRequired):
        bad.disconnect(expected_revision=connection.revision)

    recovered = BlueWayRepository(courses).get_connection(connection.id)
    assert recovered.state == "active"
    assert recovered.credential_status == "recovery_required"
    assert recovered.revision == connection.revision + 1
    assert recovered.grant_generation == connection.grant_generation + 1
    assert BlueWayRepository(courses).get_run(queued.id).state == "cancelled"
    assert transport.revocations == []
    assert (
        paths.get_integration_credentials_dir() / f"{connection.id}.enc"
    ).read_bytes() == original


def test_wrong_key_sync_creates_no_rotation_receipt_or_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    good, courses, _paths, transport = _service(
        tmp_path, monkeypatch, key=b"k" * 32,
    )
    connection = _connected(good)
    queued = good.queue_sync()

    bad = BlueWayService(_settings(b"x" * 32), transport)
    with pytest.raises(BlueWayCredentialRecoveryRequired):
        bad.run_queued_sync(run_id=queued.id)

    repository = BlueWayRepository(courses)
    after = repository.get_connection(connection.id)
    assert after.credential_status == "recovery_required"
    assert after.rotation_request_id is None
    assert repository.get_run(queued.id).state == "cancelled"
    assert transport.refreshes == []


def test_same_subject_recovery_preserves_connection_and_course_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    good, courses, paths, transport = _service(
        tmp_path, monkeypatch, key=b"k" * 32,
    )
    connection = _connected(good)
    repository = BlueWayRepository(courses)
    course = repository.create_course_map(
        connection_id=connection.id,
        external_course_id="remote-course",
        remote_title="Biology",
        remote_state="active",
        remote_hash="a" * 64,
        snapshot_id="snapshot-a",
        expected_generation=connection.grant_generation,
    )

    bad = BlueWayService(_settings(b"x" * 32), transport)
    assert bad.status()[0] is not None
    assert repository.get_connection(connection.id).credential_status == "recovery_required"

    attempt = bad.start_recovery()
    completed = bad.complete_recovery_for_transport(
        attempt_id=attempt.id,
        exchange=TokenExchange(
            "grant-new", "subject-a", "access",
            "2026-07-23T00:00:00Z", "new-refresh",
        ),
    )

    assert completed.id == connection.id
    assert completed.credential_status == "healthy"
    assert courses.get_course(course.id).id == course.id
    with courses._connect() as conn:  # noqa: SLF001 - exact preservation proof.
        row = conn.execute(
            "SELECT course_id FROM blueway_course_maps WHERE connection_id = ?",
            (connection.id,),
        ).fetchone()
    assert row is not None and row["course_id"] == course.id
    assert CredentialStore(
        paths.get_integration_credentials_dir(), b"x" * 32,
    ).read(
        owner_user_id="owner-a",
        connection_id=connection.id,
        scope_version=connection.scope_version,
    ) == "new-refresh"
    assert transport.revocations == []


def test_recovery_rejects_a_different_blueway_subject_and_revokes_new_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    good, courses, _paths, transport = _service(
        tmp_path, monkeypatch, key=b"k" * 32,
    )
    connection = _connected(good)
    bad = BlueWayService(_settings(b"x" * 32), transport)
    bad.status()
    attempt = bad.start_recovery()

    with pytest.raises(BlueWayCredentialRecoveryRequired, match="same BlueWay account"):
        bad.complete_recovery_for_transport(
            attempt_id=attempt.id,
            exchange=TokenExchange(
                "grant-other", "subject-other", "access",
                "2026-07-23T00:00:00Z", "other-refresh",
            ),
        )

    assert transport.revocations == ["other-refresh"]
    after = BlueWayRepository(courses).get_connection(connection.id)
    assert after.credential_status == "recovery_required"
    retry = bad.start_recovery()
    assert retry.id != attempt.id


def test_recovery_database_failure_never_reports_connection_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    good, courses, paths, transport = _service(
        tmp_path, monkeypatch, key=b"k" * 32,
    )
    connection = _connected(good)
    bad = BlueWayService(_settings(b"x" * 32), transport)
    bad.status()
    attempt = bad.start_recovery()

    def fail_commit(*_args, **_kwargs):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(
        BlueWayRepository, "complete_credential_recovery", fail_commit,
    )
    with pytest.raises(RuntimeError, match="database failure"):
        bad.complete_recovery_for_transport(
            attempt_id=attempt.id,
            exchange=TokenExchange(
                "grant-new", "subject-a", "access",
                "2026-07-23T00:00:00Z", "new-refresh",
            ),
        )

    after = BlueWayRepository(courses).get_connection(connection.id)
    assert after.credential_status == "recovery_required"
    assert transport.revocations == ["new-refresh"]
    quarantine = paths.get_integration_credentials_dir() / "quarantine"
    assert len(list(quarantine.glob(f"{connection.id}.*.enc"))) == 1


def test_recovery_poll_replay_returns_one_committed_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    good, _courses, _paths, transport = _service(
        tmp_path, monkeypatch, key=b"k" * 32,
    )
    connection = _connected(good)
    bad = BlueWayService(_settings(b"x" * 32), transport)
    bad.status()
    attempt = bad.start_recovery()
    transport.exchange_result = TokenExchange(
        "grant-new", "subject-a", "access",
        "2026-07-23T00:00:00Z", "new-refresh",
    )

    first, _run = bad.poll_recovery(attempt_id=attempt.id)
    second, _run = bad.poll_recovery(attempt_id=attempt.id)

    assert first is not None and first.id == connection.id
    assert second is not None and second.id == connection.id
    assert transport.exchange_calls == 1


def test_recovery_provider_failure_becomes_terminal_and_clears_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    good, _courses, _paths, transport = _service(
        tmp_path, monkeypatch, key=b"k" * 32,
    )
    _connected(good)
    bad = BlueWayService(_settings(b"x" * 32), transport)
    bad.status()
    attempt = bad.start_recovery()
    transport.exchange_error = BlueWayTransportError("provider unavailable")

    with pytest.raises(BlueWayTransportError, match="provider unavailable"):
        bad.poll_recovery(attempt_id=attempt.id)

    terminal = bad.get_attempt(attempt.id)
    assert terminal.state == "failed"
    assert terminal.device_code == ""
    assert terminal.verifier == ""
    assert terminal.error_code == "BlueWayTransportError"
    completed, run = bad.poll_recovery(attempt_id=attempt.id)
    assert completed is None and run is None
    assert transport.exchange_calls == 1


def test_recovery_cancel_has_its_own_route_and_cannot_use_connect_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.integrations.blueway import router as blueway_router

    good, _courses, _paths, transport = _service(
        tmp_path, monkeypatch, key=b"k" * 32,
    )
    _connected(good)
    bad = BlueWayService(_settings(b"x" * 32), transport)
    bad.status()
    attempt = bad.start_recovery()
    app = FastAPI()
    app.include_router(
        blueway_router.router, prefix="/api/v1/integrations/blueway",
    )
    blueway_router.set_test_service(bad)
    try:
        wrong_route = TestClient(app).post(
            f"/api/v1/integrations/blueway/connect/{attempt.id}/cancel",
        )
        response = TestClient(app).post(
            f"/api/v1/integrations/blueway/recovery/{attempt.id}/cancel",
        )
    finally:
        blueway_router.set_test_service(None)

    assert wrong_route.status_code == 404
    assert response.status_code == 200
    assert response.json()["attempt"]["mode"] == "recovery"
    assert response.json()["attempt"]["state"] == "cancelled"
    assert len(transport.cancellations) == 1


def test_provider_expiry_is_published_as_expired_when_recovery_is_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    good, _courses, _paths, transport = _service(
        tmp_path, monkeypatch, key=b"k" * 32,
    )
    _connected(good)
    bad = BlueWayService(_settings(b"x" * 32), transport)
    bad.status()
    attempt = bad.start_recovery()
    transport.cancel_result = "expired"

    cancelled = bad.cancel_attempt(attempt_id=attempt.id)

    assert cancelled.state == "expired"
    assert cancelled.error_code == "expired"
    assert cancelled.device_code == ""
    assert cancelled.verifier == ""


def test_concurrent_recovery_polls_exchange_and_commit_only_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingRecoveryTransport(RecoveryTransport):
        def __init__(self) -> None:
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()

        def exchange(
            self, *, request_id: str, device_code: str, code_verifier: str,
        ) -> TokenExchange:
            self.exchange_calls += 1
            self.entered.set()
            assert self.release.wait(5)
            assert self.exchange_result is not None
            return self.exchange_result

    transport = BlockingRecoveryTransport()
    good, _courses, _paths, _transport = _service(
        tmp_path, monkeypatch, key=b"k" * 32, transport=transport,
    )
    connection = _connected(good)
    bad = BlueWayService(_settings(b"x" * 32), transport)
    bad.status()
    attempt = bad.start_recovery()
    transport.exchange_result = TokenExchange(
        "grant-new", "subject-a", "access",
        "2026-07-23T00:00:00Z", "new-refresh",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            bad.poll_recovery, attempt_id=attempt.id,
        )
        assert transport.entered.wait(5)
        with pytest.raises(CourseConflictError, match="already being completed"):
            bad.poll_recovery(attempt_id=attempt.id)
        transport.release.set()
        completed, _run = first.result(timeout=5)

    assert completed is not None and completed.id == connection.id
    replay, _run = bad.poll_recovery(attempt_id=attempt.id)
    assert replay is not None and replay.id == connection.id
    assert transport.exchange_calls == 1


def test_recovery_cancel_is_fenced_while_provider_exchange_is_in_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingFailureTransport(RecoveryTransport):
        def __init__(self) -> None:
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()

        def exchange(
            self, *, request_id: str, device_code: str, code_verifier: str,
        ):
            self.exchange_calls += 1
            self.entered.set()
            assert self.release.wait(5)
            raise BlueWayTransportError("provider cancelled")

    transport = BlockingFailureTransport()
    good, _courses, _paths, _transport = _service(
        tmp_path, monkeypatch, key=b"k" * 32, transport=transport,
    )
    _connected(good)
    bad = BlueWayService(_settings(b"x" * 32), transport)
    bad.status()
    attempt = bad.start_recovery()

    with ThreadPoolExecutor(max_workers=1) as executor:
        poll = executor.submit(bad.poll_recovery, attempt_id=attempt.id)
        assert transport.entered.wait(5)
        with pytest.raises(CourseConflictError, match="already being completed"):
            bad.cancel_attempt(attempt_id=attempt.id)
        transport.release.set()
        with pytest.raises(BlueWayTransportError, match="provider cancelled"):
            poll.result(timeout=5)

    terminal = bad.get_attempt(attempt.id)
    assert terminal.state == "failed"
    assert terminal.device_code == ""
    assert transport.cancellations == []


def test_api_reports_only_safe_recovery_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.integrations.blueway import router as blueway_router

    good, _courses, _paths, transport = _service(
        tmp_path, monkeypatch, key=b"k" * 32,
    )
    connection = _connected(good)
    bad = BlueWayService(_settings(b"x" * 32), transport)
    app = FastAPI()
    app.include_router(
        blueway_router.router, prefix="/api/v1/integrations/blueway",
    )
    blueway_router.set_test_service(bad)
    try:
        response = TestClient(app).get("/api/v1/integrations/blueway")
    finally:
        blueway_router.set_test_service(None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["connection"] == {
        "id": connection.id,
        "state": "credential_recovery_required",
        "revision": 2,
        "scope_version": "academic.read.v1",
        "connected_at": connection.connected_at,
        "last_sync_at": None,
    }
    serialized = json.dumps(payload).lower()
    for forbidden in (
        "refresh", "master_key", "credential_ref", "key_id",
        "quarantine", "invalidtag",
    ):
        assert forbidden not in serialized
