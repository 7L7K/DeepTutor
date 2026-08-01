"""Local-only HTTP authority and runtime harness for Phase 3A.

This deliberately models *BlueWay after its own sign-in step*.  It exposes
stable opaque external subjects, device approval, grant rotation, export, and
revocation over the same HTTP contract used by :class:`HttpBlueWayTransport`.
It does not pretend to issue Apple credentials or validate BlueWay's hosted
deployment configuration.
"""

from __future__ import annotations

import base64
import copy
from dataclasses import dataclass
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import courses as course_router
from deeptutor.courses import service as course_service_module
from deeptutor.courses.repository import CourseRepository
from deeptutor.integrations.blueway import router as blueway_router
from deeptutor.integrations.blueway.config import BlueWaySettings
from deeptutor.integrations.blueway.service import BlueWayService
from deeptutor.integrations.blueway.snapshot import canonical_snapshot_hash
from deeptutor.integrations.blueway.transport import HttpBlueWayTransport
from deeptutor.multi_user import identity, paths
from deeptutor.services.auth import TokenPayload

_INTEGRATION_PREFIX = "/api/v1/integrations/blueway"
_COURSE_PREFIX = "/api/v1/courses"
_TEST_API_SECRET = "h" * 32
_TEST_MASTER_KEY = b"k" * 32


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def phase3a_snapshot(*, marker: str) -> dict[str, Any]:
    """A valid, minimal academic export with one no-speech transcript.

    Equal titles force consumers to use opaque course identity.  The marker is
    deliberately unique to each synthetic BlueWay subject so cross-owner data
    leakage cannot be hidden by identical fixtures.
    """

    def record(kind: str, record_id: str, **fields: Any) -> dict[str, Any]:
        return {
            "id": record_id,
            "state": "current",
            "revision": _digest(f"revision:{marker}:{kind}:{record_id}"),
            "content_sha256": _digest(f"content:{marker}:{kind}:{record_id}"),
            **fields,
        }

    datasets: dict[str, list[dict[str, Any]]] = {
        "courses": [
            record(
                "courses", "remote-course-a", course_id="remote-course-a", title="Shared Seminar"
            ),
            record(
                "courses", "remote-course-b", course_id="remote-course-b", title="Shared Seminar"
            ),
        ],
        "class_meetings": [],
        "schedule_events": [],
        "assignments": [],
        "class_notes": [],
        "class_links": [],
        "course_profiles": [],
        "syllabus_facts": [],
        "source_texts": [],
        "capture_metadata": [],
        "capture_notes": [],
        "transcripts": [
            record(
                "transcripts",
                "remote-no-speech",
                course_id="remote-course-a",
                duration_ms=0,
                language="en",
                layer="raw",
                segments=[],
            ),
            record(
                "transcripts",
                "remote-speech",
                course_id="remote-course-b",
                duration_ms=1_500,
                language="en",
                layer="raw",
                segments=[{"start_ms": 0, "end_ms": 1_500, "text": f"Lecture marker: {marker}"}],
            ),
        ],
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "snapshot_id": f"bws_{_digest(f'snapshot:{marker}')}",
        "snapshot_revision": 1,
        "generated_at": "2026-07-28T00:00:00Z",
        "complete": True,
        "next_cursor": None,
        "datasets": datasets,
        "unavailable": [],
    }
    payload["payload_sha256"] = canonical_snapshot_hash(payload)
    return payload


@dataclass
class _Request:
    request_id: str
    device_code: str
    user_code: str
    code_challenge: str
    approved_subject: str | None = None
    grant_id: str | None = None


@dataclass
class _Grant:
    id: str
    subject: str
    refresh_token: str
    access_token: str
    state: str = "active"


class SyntheticBlueWayAuthority:
    """Threaded loopback implementation of the bounded BlueWay HTTP contract.

    The public ``approve`` helper is test control-plane code.  It represents
    approval in BlueWay after an external identity provider has authenticated
    the person; it is never visible to TEEECHR's production transport.
    """

    def __init__(self, *, snapshots: dict[str, dict[str, Any]]) -> None:
        self._snapshots = copy.deepcopy(snapshots)
        self._lock = threading.RLock()
        self._counter = 0
        self._requests: dict[str, _Request] = {}
        self._grants: dict[str, _Grant] = {}
        self._refresh_tokens: dict[str, str] = {}
        self._access_tokens: dict[str, str] = {}
        self.revoked_grant_ids: list[str] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def approval_url(self) -> str:
        return f"{self.base_url}/teeechr-connect"

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def approve(self, request_id: str, *, external_subject: str) -> None:
        """Approve one pending request as a stable synthetic BlueWay account."""
        with self._lock:
            request = self._requests.get(request_id)
            if request is None:
                raise AssertionError(f"Unknown synthetic pairing request: {request_id}")
            if request.approved_subject is not None:
                raise AssertionError("Synthetic pairing request was already approved")
            if external_subject not in self._snapshots:
                raise AssertionError("Synthetic BlueWay subject has no fixture export")
            request.approved_subject = external_subject

    def grant_id_for_subject(self, subject: str) -> str:
        with self._lock:
            matching = [grant.id for grant in self._grants.values() if grant.subject == subject]
        if not matching:
            raise AssertionError(f"No synthetic grant was created for {subject}")
        return matching[-1]

    def grant_is_revoked(self, grant_id: str) -> bool:
        with self._lock:
            grant = self._grants.get(grant_id)
            return grant is not None and grant.state == "revoked"

    def _next(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter:08d}"

    @staticmethod
    def _challenge(verifier: str) -> str:
        return (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )

    def _json_response(
        self, handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]
    ) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    @staticmethod
    def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any] | None:
        raw = handler.headers.get("Content-Length")
        try:
            size = int(raw or "0")
        except ValueError:
            return None
        if size < 0 or size > 128 * 1024:
            return None
        try:
            value = json.loads(handler.rfile.read(size))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _handle_pairing(self, handler: BaseHTTPRequestHandler, payload: dict[str, Any]) -> None:
        if handler.headers.get("x-teeechr-integration-secret") != _TEST_API_SECRET:
            self._json_response(handler, 401, {"error": "unauthorized"})
            return
        action = payload.get("action")
        with self._lock:
            if action == "start":
                fields = ("client_id", "audience", "device_code", "user_code", "code_challenge")
                if not all(
                    isinstance(payload.get(field), str) and payload[field] for field in fields
                ):
                    self._json_response(handler, 400, {"error": "invalid_request"})
                    return
                request_id = self._next("req")
                self._requests[request_id] = _Request(
                    request_id=request_id,
                    device_code=str(payload["device_code"]),
                    user_code=str(payload["user_code"]),
                    code_challenge=str(payload["code_challenge"]),
                )
                self._json_response(
                    handler,
                    200,
                    {"request_id": request_id, "expires_at": "2099-01-01T00:00:00Z"},
                )
                return
            if action == "exchange":
                request_id = payload.get("request_id")
                request = self._requests.get(request_id) if isinstance(request_id, str) else None
                if request is None or payload.get("device_code") != request.device_code:
                    self._json_response(handler, 401, {"error": "unauthorized"})
                    return
                verifier = payload.get("code_verifier")
                if (
                    not isinstance(verifier, str)
                    or self._challenge(verifier) != request.code_challenge
                ):
                    self._json_response(handler, 401, {"error": "unauthorized"})
                    return
                if request.approved_subject is None:
                    self._json_response(handler, 202, {"error": "authorization_pending"})
                    return
                if request.grant_id is None:
                    grant_id = self._next("grant")
                    grant = _Grant(
                        id=grant_id,
                        subject=request.approved_subject,
                        refresh_token=self._next("refresh"),
                        access_token=self._next("access"),
                    )
                    self._grants[grant.id] = grant
                    self._refresh_tokens[grant.refresh_token] = grant.id
                    self._access_tokens[grant.access_token] = grant.id
                    request.grant_id = grant.id
                grant = self._grants[request.grant_id]
                self._json_response(handler, 200, self._exchange_payload(grant))
                return
            if action == "refresh":
                token = payload.get("refresh_token")
                grant = self._grant_from_refresh(token)
                if grant is None or grant.state != "active":
                    self._json_response(handler, 401, {"error": "unauthorized"})
                    return
                self._refresh_tokens.pop(grant.refresh_token, None)
                grant.refresh_token = self._next("refresh")
                grant.access_token = self._next("access")
                self._refresh_tokens[grant.refresh_token] = grant.id
                self._access_tokens[grant.access_token] = grant.id
                self._json_response(
                    handler,
                    200,
                    {
                        "access_token": grant.access_token,
                        "access_expires_at": "2099-01-01T00:00:00Z",
                        "refresh_token": grant.refresh_token,
                    },
                )
                return
            if action == "revoke_refresh":
                grant = self._grant_from_refresh(payload.get("refresh_token"))
                if grant is None:
                    self._json_response(handler, 401, {"error": "unauthorized"})
                    return
                if grant.state != "revoked":
                    grant.state = "revoked"
                    self.revoked_grant_ids.append(grant.id)
                self._json_response(handler, 200, {"revoked": True})
                return
        self._json_response(handler, 400, {"error": "invalid_action"})

    def _grant_from_refresh(self, raw_token: object) -> _Grant | None:
        if not isinstance(raw_token, str):
            return None
        grant_id = self._refresh_tokens.get(raw_token)
        return self._grants.get(grant_id) if grant_id else None

    @staticmethod
    def _exchange_payload(grant: _Grant) -> dict[str, str]:
        return {
            "grant_id": grant.id,
            "external_subject": grant.subject,
            "access_token": grant.access_token,
            "access_expires_at": "2099-01-01T00:00:00Z",
            "refresh_token": grant.refresh_token,
        }

    def _handle_export(self, handler: BaseHTTPRequestHandler) -> None:
        authorization = handler.headers.get("Authorization") or ""
        scheme, _, token = authorization.partition(" ")
        with self._lock:
            grant_id = self._access_tokens.get(token) if scheme == "Bearer" else None
            grant = self._grants.get(grant_id) if grant_id else None
            if grant is None or grant.state != "active":
                self._json_response(handler, 401, {"error": "unauthorized"})
                return
            payload = copy.deepcopy(self._snapshots[grant.subject])
        self._json_response(handler, 200, payload)

    def _handler(self):
        authority = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract.
                if urlsplit(self.path).path != "/functions/v1/teeechr-pairing":
                    authority._json_response(self, 404, {"error": "not_found"})
                    return
                payload = authority._read_json(self)
                if payload is None:
                    authority._json_response(self, 400, {"error": "invalid_json"})
                    return
                authority._handle_pairing(self, payload)

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract.
                if urlsplit(self.path).path != "/functions/v1/teeechr-export":
                    authority._json_response(self, 404, {"error": "not_found"})
                    return
                authority._handle_export(self)

        return Handler


@dataclass
class HermeticPhase3AHarness:
    """A disposable, authenticated two-owner TEEECHR integration runtime."""

    client: TestClient
    authority: SyntheticBlueWayAuthority
    settings: BlueWaySettings
    service: BlueWayService
    tokens: dict[str, str]
    owner_ids: dict[str, str]
    workspace_root: Path
    _services: list[BlueWayService]
    worker_errors: list[str]

    def headers(self, owner: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[owner]}"}

    def connection_start(self, owner: str) -> dict[str, Any]:
        response = self.client.post(
            f"{_INTEGRATION_PREFIX}/connect/start", headers=self.headers(owner)
        )
        assert response.status_code == 200, response.text
        return response.json()

    def approve(self, *, start: dict[str, Any], subject: str) -> None:
        query = parse_qs(urlsplit(str(start["verification_uri"])).query)
        request_id = query.get("request_id", [None])[0]
        assert isinstance(request_id, str) and request_id
        self.authority.approve(request_id, external_subject=subject)

    def poll_connection(self, owner: str, attempt_id: str) -> dict[str, Any]:
        response = self.client.post(
            f"{_INTEGRATION_PREFIX}/connect/{attempt_id}/poll", headers=self.headers(owner)
        )
        assert response.status_code == 202, response.text
        return response.json()

    def wait_for_run(self, owner: str, run_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + 8
        last: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            response = self.client.get(
                f"{_INTEGRATION_PREFIX}/sync-runs/{run_id}", headers=self.headers(owner)
            )
            assert response.status_code == 200, response.text
            last = response.json()
            if last["state"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)
        assert last is not None and last["state"] == "completed", {
            "run": last,
            "worker_errors": self.worker_errors,
        }
        return last

    def connect_approve_sync(
        self, *, owner: str, subject: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        start = self.connection_start(owner)
        self.approve(start=start, subject=subject)
        polled = self.poll_connection(owner, str(start["attempt_id"]))
        connection = polled["connection"]
        active_run = polled["active_run"]
        assert isinstance(connection, dict) and isinstance(active_run, dict)
        self.wait_for_run(owner, str(active_run["id"]))
        return connection, active_run

    def status(self, owner: str) -> dict[str, Any]:
        response = self.client.get(_INTEGRATION_PREFIX, headers=self.headers(owner))
        assert response.status_code == 200, response.text
        return response.json()

    def restart_service(self) -> BlueWayService:
        """Reinstantiate the service against the same files; no state is copied."""
        replacement = BlueWayService(
            self.settings,
            HttpBlueWayTransport(self.settings),
        )
        self._observe_worker_errors(replacement)
        blueway_router.set_test_service(replacement)
        self.service = replacement
        self._services.append(replacement)
        return replacement

    def _observe_worker_errors(self, service: BlueWayService) -> None:
        original = service._run_queued_sync_for_owner  # noqa: SLF001 - retain thread exception evidence.

        def observed(*, owner_user_id: str, run_id: str):
            try:
                return original(owner_user_id=owner_user_id, run_id=run_id)
            except Exception as exc:  # noqa: BLE001 - report a background failure to the test.
                self.worker_errors.append(f"{type(exc).__name__}: {exc}")
                raise

        service._run_queued_sync_for_owner = observed  # type: ignore[method-assign]  # noqa: SLF001

    def repository(self, owner: str) -> CourseRepository:
        path = (
            self.workspace_root / "data" / "users" / self.owner_ids[owner] / "user" / "courses.db"
        )
        return CourseRepository(path, self.owner_ids[owner])

    def credential_path(self, owner: str, connection_id: str) -> Path:
        return (
            self.workspace_root
            / "data"
            / "users"
            / self.owner_ids[owner]
            / "user"
            / "integration_credentials"
            / f"{connection_id}.enc"
        )

    def close(self) -> None:
        blueway_router.set_test_service(None)
        for service in self._services:
            service._executor.shutdown(wait=True)  # noqa: SLF001 - deterministic test cleanup.
        self.authority.close()


@pytest.fixture
def hermetic_phase3a(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HermeticPhase3AHarness:
    """Build real local profile auth, SQLite, credential files, routes and HTTP."""
    workspace_root = (tmp_path / "runtime").resolve()
    admin_root = workspace_root / "data"
    users_root = admin_root / "users"
    system_root = admin_root / "system"
    monkeypatch.setattr(paths, "PROJECT_ROOT", workspace_root)
    monkeypatch.setattr(paths, "USERS_ROOT", users_root)
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", workspace_root / "missing-legacy")
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(identity, "PROJECT_ROOT", workspace_root)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", workspace_root / "missing-users.json")
    monkeypatch.setattr(identity, "LEGACY_SECRET_FILE", workspace_root / "missing-secret")
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(course_service_module, "is_pocketbase_enabled", lambda: False)
    course_service_module._repository_for.cache_clear()

    alice = identity.save_user("alice", "$2b$12$placeholder", role="admin")
    bob = identity.save_user("bob", "$2b$12$placeholder", role="user")
    owner_ids = {"alice": str(alice["id"]), "bob": str(bob["id"])}
    payloads = {
        "alice-token": TokenPayload("alice", "admin", owner_ids["alice"]),
        "bob-token": TokenPayload("bob", "user", owner_ids["bob"]),
    }
    monkeypatch.setattr(auth_router, "decode_token", lambda token: payloads.get(token))

    authority = SyntheticBlueWayAuthority(
        snapshots={
            "blueway-subject-alice": phase3a_snapshot(marker="PHASE3A_ALICE_ONLY"),
            "blueway-subject-bob": phase3a_snapshot(marker="PHASE3A_BOB_ONLY"),
        }
    )
    authority.start()
    settings = BlueWaySettings(
        enabled=True,
        base_url=authority.base_url,
        client_id="phase3a-hermetic-client",
        api_secret=_TEST_API_SECRET,
        approval_url=authority.approval_url,
        master_key=_TEST_MASTER_KEY,
    )
    service = BlueWayService(settings, HttpBlueWayTransport(settings))
    blueway_router.set_test_service(service)
    app = FastAPI()
    auth_dependency = [Depends(auth_router.require_auth)]
    app.include_router(course_router.router, prefix=_COURSE_PREFIX, dependencies=auth_dependency)
    app.include_router(
        blueway_router.router, prefix=_INTEGRATION_PREFIX, dependencies=auth_dependency
    )
    harness = HermeticPhase3AHarness(
        client=TestClient(app),
        authority=authority,
        settings=settings,
        service=service,
        tokens={"alice": "alice-token", "bob": "bob-token"},
        owner_ids=owner_ids,
        workspace_root=workspace_root,
        _services=[service],
        worker_errors=[],
    )
    harness._observe_worker_errors(service)
    try:
        yield harness
    finally:
        harness.close()
        course_service_module._repository_for.cache_clear()
