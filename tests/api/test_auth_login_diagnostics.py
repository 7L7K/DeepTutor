"""Privacy and branch-contract tests for the browser login endpoint."""

from __future__ import annotations

import json
import logging
import re

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
from fastapi import FastAPI

from deeptutor.api.routers import auth as auth_router
from deeptutor.services import auth as auth_service
from deeptutor.services.auth_diagnostics import (
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
    assert validated_request_id("phone-login-001") == "phone-login-001"
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
    assert unknown.json() == wrong_password.json() == {
        "detail": "Incorrect username or password"
    }
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
    assert event["request_id"] == "phone-login-002"
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


def test_direct_diagnostic_event_never_contains_auth_material(caplog) -> None:
    caplog.set_level(logging.INFO, logger="deeptutor.auth")
    password = "correct-password"
    password_hash = "$2b$12$not-a-real-hash-for-this-test"
    emit_auth_attempt(
        attempt_id="safe-001",
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
    assert "alice@example.com" not in message
