"""Privacy and branch-contract tests for the browser login endpoint."""

from __future__ import annotations

import asyncio
import json
import logging
import re

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError

from deeptutor.api.auth_validation import login_validation_exception_handler
from deeptutor.api.routers import auth as auth_router
from deeptutor.services import auth as auth_service
from deeptutor.services.auth_diagnostics import (
    LoginFailureLimiter,
    attempt_id_is_valid,
    emit_auth_attempt,
    identifier_details,
    resolve_attempt_id,
    validated_request_id,
)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/auth")
    return app


def _validation_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, login_validation_exception_handler)
    app.include_router(auth_router.router, prefix="/api/v1/auth")
    return app


def _event_messages(caplog) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for record in caplog.records:
        if record.name != "deeptutor.auth" or not record.message.startswith("auth_login_attempt "):
            continue
        events.append(json.loads(record.message.split(" ", 1)[1]))
    return events


@pytest.fixture
def auth_users(monkeypatch: pytest.MonkeyPatch) -> str:
    password_hash = auth_service.hash_password("correct-password")
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "AUTH_SECRET", "diagnostic-test-secret")
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "diagnostic-test-secret")
    monkeypatch.setattr(
        auth_service,
        "_load_users",
        lambda: {
            "User@example.com": {
                "id": "u_test",
                "hash": password_hash,
                "role": "user",
                "disabled": False,
            },
            "disabled@example.com": {
                "id": "u_disabled",
                "hash": password_hash,
                "role": "user",
                "disabled": True,
            },
        },
    )
    return password_hash


def test_attempt_id_is_fresh_and_request_ids_are_bounded() -> None:
    generated = resolve_attempt_id()
    assert generated.startswith("auth_")
    assert attempt_id_is_valid(generated)
    assert resolve_attempt_id() != generated
    assert attempt_id_is_valid("phone-login-001")
    request_reference = validated_request_id("phone-login-001", auth_secret="secret")
    assert request_reference is not None
    assert request_reference.startswith("req_")
    assert request_reference == validated_request_id("phone-login-001", auth_secret="secret")
    assert "phone-login-001" not in request_reference
    assert validated_request_id("bad id with spaces") is None
    assert validated_request_id(None) is None
    assert not attempt_id_is_valid("bad id with spaces")


def test_identifier_mask_and_hmac_are_safe_and_deterministic() -> None:
    first = identifier_details("  User@EXAMPLE.COM  ", auth_secret="secret")
    second = identifier_details("user@example.com", auth_secret="secret")

    assert first.kind == "email"
    assert first.masked == "U***@example.com"
    assert first.fingerprint == second.fingerprint
    assert "User@EXAMPLE.COM" not in first.masked
    assert "secret" not in first.fingerprint


def test_login_failure_limiter_is_bounded_and_expires_without_raw_identifiers() -> None:
    clock = [100.0]
    limiter = LoginFailureLimiter(
        max_failures=2,
        window_seconds=10.0,
        max_keys=2,
        clock=lambda: clock[0],
    )

    assert limiter.retry_after_seconds("hmac-a") is None
    limiter.reserve_attempt("hmac-a")
    limiter.reserve_attempt("hmac-a")
    assert limiter.retry_after_seconds("hmac-a") == 10

    clock[0] = 109.1
    assert limiter.retry_after_seconds("hmac-a") == 1
    clock[0] = 110.0
    assert limiter.retry_after_seconds("hmac-a") is None

    limiter.reserve_attempt("hmac-a")
    limiter.clear("hmac-a")
    assert limiter.retry_after_seconds("hmac-a") is None
    assert limiter.retry_after_seconds(None) is None


def test_standard_login_runs_sync_credential_check_in_worker_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "AUTH_SECRET", "threading-test-secret")
    monkeypatch.setattr(auth_router, "_LOGIN_FAILURE_LIMITER", LoginFailureLimiter())
    payload = auth_service.TokenPayload(username="alice", role="user", user_id="u_alice")
    result = auth_service.AuthenticationResult(
        payload=payload,
        lookup="exact",
        account_state="active",
        password_result="match",
    )
    monkeypatch.setattr(auth_router, "authenticate_detailed", lambda *_args: result)
    monkeypatch.setattr(auth_router, "create_token", lambda *_args: "test-token")
    calls: list[tuple[object, tuple[object, ...]]] = []

    async def _fake_to_thread(function, /, *args, **kwargs):
        calls.append((function, args))
        return function(*args, **kwargs)

    monkeypatch.setattr(auth_router.asyncio, "to_thread", _fake_to_thread)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/login",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )

    response = Response()
    body = auth_router.LoginRequest(username="alice", password="correct-password")
    response_body = asyncio.run(auth_router.login(body, request, response))

    assert response_body["ok"] is True
    assert calls == [(auth_router.authenticate_detailed, ("alice", "correct-password"))]
    assert response.headers["x-auth-attempt-id"].startswith("auth_")


def test_rate_limited_login_rejects_before_starting_credential_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "AUTH_SECRET", "limiter-test-secret")
    limiter = LoginFailureLimiter()
    monkeypatch.setattr(auth_router, "_LOGIN_FAILURE_LIMITER", limiter)
    body = auth_router.LoginRequest(username="alice", password="wrong-password")
    fingerprint = identifier_details(body.username, auth_secret="limiter-test-secret").fingerprint
    for _ in range(5):
        limiter.reserve_attempt(fingerprint)
    worker_started = False

    async def _unexpected_to_thread(*_args, **_kwargs):
        nonlocal worker_started
        worker_started = True
        raise AssertionError("a throttled login must not start credential verification")

    monkeypatch.setattr(auth_router.asyncio, "to_thread", _unexpected_to_thread)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/login",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(auth_router.login(body, request, Response()))

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Too many login attempts. Try again later."
    assert exc_info.value.headers is not None
    assert int(exc_info.value.headers["Retry-After"]) >= 1
    assert worker_started is False


def test_simultaneous_login_burst_reserves_bcrypt_budget_before_workers_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "AUTH_SECRET", "concurrent-limiter-test-secret")
    monkeypatch.setattr(auth_router, "_LOGIN_FAILURE_LIMITER", LoginFailureLimiter())
    failed_result = auth_service.AuthenticationResult(
        payload=None,
        lookup="exact",
        account_state="active",
        password_result="mismatch",
    )
    monkeypatch.setattr(auth_router, "authenticate_detailed", lambda *_args: failed_result)

    async def _exercise() -> list[int]:
        release_workers = asyncio.Event()
        worker_started = 0

        async def _blocked_to_thread(function, /, *args, **kwargs):
            nonlocal worker_started
            worker_started += 1
            await release_workers.wait()
            return function(*args, **kwargs)

        monkeypatch.setattr(auth_router.asyncio, "to_thread", _blocked_to_thread)

        async def _attempt() -> int:
            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/auth/login",
                    "headers": [],
                    "client": ("127.0.0.1", 12345),
                }
            )
            body = auth_router.LoginRequest(username="alice", password="wrong-password")
            try:
                await auth_router.login(body, request, Response())
            except HTTPException as exc:
                return exc.status_code
            raise AssertionError("the mocked authentication result must fail")

        attempts = [asyncio.create_task(_attempt()) for _ in range(6)]
        for _ in range(3):
            await asyncio.sleep(0)
        assert worker_started == 5
        release_workers.set()
        return await asyncio.gather(*attempts)

    statuses = asyncio.run(_exercise())

    assert sorted(statuses) == [401, 401, 401, 401, 401, 429]


def test_login_unknown_and_wrong_password_keep_the_same_public_error(auth_users, caplog) -> None:
    caplog.set_level(logging.INFO, logger="deeptutor.auth")
    with TestClient(_app()) as client:
        unknown = client.post(
            "/auth/login",
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
            },
            json={"username": "unknown@example.com", "password": "wrong-password"},
        )
        wrong_password = client.post(
            "/auth/login",
            json={"username": "User@example.com", "password": "wrong-password"},
        )

    assert unknown.status_code == 401
    assert wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json() == {"detail": "Incorrect username or password"}
    assert attempt_id_is_valid(unknown.headers["x-auth-attempt-id"])
    events = _event_messages(caplog)
    assert [event["lookup"] for event in events[-2:]] == ["none", "exact"]
    assert events[-2]["password_result"] == "not_checked"
    assert events[-1]["password_result"] == "mismatch"
    assert events[-2]["client"] == "iphone-safari"
    assert "unknown@example.com" not in caplog.text
    assert "wrong-password" not in caplog.text


def test_login_accepts_casefold_email_and_emits_success_diagnostic(auth_users, caplog) -> None:
    caplog.set_level(logging.INFO, logger="deeptutor.auth")
    with TestClient(_app()) as client:
        response = client.post(
            "/auth/login",
            headers={"X-Request-ID": "phone-login-002"},
            json={"username": " user@EXAMPLE.COM ", "password": "correct-password"},
        )

    assert response.status_code == 200
    assert attempt_id_is_valid(response.headers["x-auth-attempt-id"])
    event = _event_messages(caplog)[-1]
    assert event["request_id"] == validated_request_id(
        "phone-login-002", auth_secret="diagnostic-test-secret"
    )
    assert event["lookup"] == "casefold"
    assert event["password_result"] == "match"
    assert event["outcome"] == "success"
    assert event["identifier_masked"] == "u***@example.com"
    assert "correct-password" not in caplog.text


def test_login_disabled_account_is_generic_and_diagnostic_is_distinct(auth_users, caplog) -> None:
    caplog.set_level(logging.INFO, logger="deeptutor.auth")
    with TestClient(_app()) as client:
        response = client.post(
            "/auth/login",
            json={"username": "disabled@example.com", "password": "correct-password"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect username or password"}
    event = _event_messages(caplog)[-1]
    assert event["account_state"] == "disabled"
    assert event["password_result"] == "not_checked"
    assert event["outcome"] == "disabled"


def test_validation_failure_diagnostic_is_bounded(caplog) -> None:
    caplog.set_level(logging.INFO, logger="deeptutor.auth")
    emit_auth_attempt(
        attempt_id="validation-001",
        username=None,
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1",
        auth_secret="diagnostic-test-secret",
        lookup="none",
        account_state="unknown",
        password_result="not_checked",
        auth_mode="standard",
        outcome="validation_failure",
    )
    event = _event_messages(caplog)[-1]
    assert event["outcome"] == "validation_failure"
    assert "validation-001" in caplog.text
    assert event["identifier_kind"] == "invalid"


def test_malformed_login_request_uses_generic_response_and_safe_event(auth_users, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="deeptutor.auth")
    submitted_password = "submitted-password-must-not-be-logged"
    with TestClient(_validation_app()) as client:
        response = client.post(
            "/api/v1/auth/login",
            headers={"X-Request-ID": "eyJhbGciOiJIUzI1NiJ9.password-like-value"},
            json={"username": 42, "password": submitted_password},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid login request"}
    assert attempt_id_is_valid(response.headers["x-auth-attempt-id"])
    event = _event_messages(caplog)[-1]
    assert event["outcome"] == "validation_failure"
    assert event["request_id"].startswith("req_")
    assert "eyJhbGciOiJIUzI1NiJ9.password-like-value" not in caplog.text
    assert submitted_password not in caplog.text


def test_request_id_material_is_never_logged(auth_users, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="deeptutor.auth")
    token_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature"
    password_like = "Password123456789"
    with TestClient(_app()) as client:
        response = client.post(
            "/auth/login",
            headers={"X-Request-ID": token_like},
            json={"username": "unknown@example.com", "password": password_like},
        )

    assert response.status_code == 401
    event = _event_messages(caplog)[-1]
    assert event["request_id"].startswith("req_")
    assert token_like not in caplog.text
    assert password_like not in caplog.text


def test_pocketbase_rejected_credentials_and_provider_failure_are_distinct(
    monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", True)
    monkeypatch.setattr(auth_router, "AUTH_SECRET", "diagnostic-test-secret")
    caplog.set_level(logging.WARNING, logger="deeptutor.auth")

    rejected = auth_service.PocketBaseAuthenticationResult(
        payload=None, token=None, outcome="invalid_credentials"
    )
    provider_failure = auth_service.PocketBaseAuthenticationResult(
        payload=None, token=None, outcome="provider_failure"
    )
    results = iter((rejected, provider_failure))
    monkeypatch.setattr(
        auth_router,
        "authenticate_pb",
        lambda _username, _password: next(results),
    )

    with TestClient(_app()) as client:
        rejected_response = client.post(
            "/auth/login", json={"username": "alice@example.com", "password": "wrong"}
        )
        provider_response = client.post(
            "/auth/login", json={"username": "alice@example.com", "password": "wrong"}
        )

    assert rejected_response.status_code == provider_response.status_code == 401
    assert (
        rejected_response.json()
        == provider_response.json()
        == {"detail": "Incorrect username or password"}
    )
    events = _event_messages(caplog)[-2:]
    assert events[0]["outcome"] == "invalid_credentials"
    assert events[0]["password_result"] == "mismatch"
    assert events[1]["outcome"] == "provider_failure"
    assert events[1]["password_result"] == "not_checked"


def test_diagnostic_event_survives_warning_level_runtime_config(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="deeptutor.auth")
    emit_auth_attempt(
        attempt_id="warning-level-001",
        username="alice@example.com",
        user_agent="Safari",
        auth_secret="diagnostic-test-secret",
        lookup="none",
        account_state="unknown",
        password_result="not_checked",
        auth_mode="standard",
        outcome="invalid_credentials",
    )

    event = _event_messages(caplog)[-1]
    assert event["attempt_id"] == "warning-level-001"
    assert caplog.records[-1].levelno == logging.WARNING


def test_direct_diagnostic_event_never_contains_auth_material(caplog) -> None:
    caplog.set_level(logging.INFO, logger="deeptutor.auth")
    password = "correct-password"
    password_hash = "$2b$12$not-a-real-hash-for-this-test"
    emit_auth_attempt(
        attempt_id="safe-001",
        request_id="eyJraw-token-like-request-id.signature",
        username="alice@example.com",
        user_agent="Safari",
        auth_secret="diagnostic-test-secret",
        lookup="exact",
        account_state="active",
        password_result="mismatch",
        auth_mode="standard",
        outcome="invalid_credentials",
    )
    message = caplog.records[-1].message
    assert password not in message
    assert password_hash not in message
    assert "Bearer " not in message
    assert "dt_token" not in message
    assert "eyJraw-token-like-request-id.signature" not in message
    assert "alice@example.com" not in message
