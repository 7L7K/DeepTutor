"""Tests for FastAPI CORS settings."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from deeptutor.api import main as api_main


def test_cors_allows_remote_http_origins_when_auth_disabled(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    monkeypatch.delenv("CORS_ORIGIN", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("FRONTEND_PORT", "3782")

    settings = api_main._build_cors_settings()

    assert settings["allow_origin_regex"] == r"https?://.*"
    assert "http://localhost:3782" in settings["allow_origins"]
    assert "http://127.0.0.1:3782" in settings["allow_origins"]


def test_cors_requires_explicit_origins_when_auth_enabled(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("CORS_ORIGIN", "https://app.example.com/")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "https://foo.example.com, https://bar.example.com\nhttps://foo.example.com",
    )

    settings = api_main._build_cors_settings()

    assert settings["allow_origin_regex"] is None
    assert "https://app.example.com" in settings["allow_origins"]
    assert "https://foo.example.com" in settings["allow_origins"]
    assert "https://bar.example.com" in settings["allow_origins"]
    assert settings["allow_origins"].count("https://foo.example.com") == 1


def test_cors_normalizes_common_origin_input_mistakes(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "CORS_ORIGIN",
        "172.26.0.10:3782; https://learn.example.com/app/",
    )
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000;api.example.com")

    settings = api_main._build_cors_settings()

    assert settings["allow_origin_regex"] is None
    assert "http://172.26.0.10:3782" in settings["allow_origins"]
    assert "https://learn.example.com" in settings["allow_origins"]
    assert "http://api.example.com" in settings["allow_origins"]


def test_cors_preflight_allows_partner_patch_save() -> None:
    client = TestClient(api_main.app)

    response = client.options(
        "/api/v1/partners/partner",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    allowed_methods = {
        method.strip() for method in response.headers["access-control-allow-methods"].split(",")
    }
    assert "PATCH" in allowed_methods


def test_cookie_mutation_rejects_unapproved_origin() -> None:
    client = TestClient(api_main.app)
    client.cookies.set("dt_token", "test-token")

    response = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Origin not allowed"}


def test_cookie_mutation_rejects_missing_or_malformed_origin() -> None:
    client = TestClient(api_main.app)
    client.cookies.set("dt_token", "test-token")

    missing = client.post("/api/v1/auth/logout")
    malformed = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "null"},
    )

    assert missing.status_code == 403
    assert malformed.status_code == 403


def test_explicit_bearer_client_does_not_require_browser_origin() -> None:
    client = TestClient(api_main.app)
    client.cookies.set("dt_token", "stale-cookie")

    response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": "Bearer explicit-client-token"},
    )

    assert response.status_code == 200


def test_cookie_mutation_allows_configured_origin() -> None:
    client = TestClient(api_main.app)
    client.cookies.set("dt_token", "test-token")

    response = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 200


def test_websocket_origin_requires_configured_frontend(monkeypatch) -> None:
    from types import SimpleNamespace

    from deeptutor.api.routers import auth as auth_router

    monkeypatch.setattr(
        auth_router,
        "_allowed_browser_origins",
        lambda: {"https://learn.example.com"},
    )
    allowed = SimpleNamespace(headers={"origin": "https://learn.example.com"})
    denied = SimpleNamespace(headers={"origin": "https://attacker.example"})
    cli = SimpleNamespace(headers={})

    assert auth_router._websocket_origin_allowed(allowed) is True
    assert auth_router._websocket_origin_allowed(denied) is False
    assert auth_router._websocket_origin_allowed(cli) is True


def test_phase2_startup_rejects_pocketbase(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.pocketbase_client.is_pocketbase_enabled", lambda: True
    )
    with pytest.raises(RuntimeError, match="PocketBase Course ownership"):
        api_main.validate_course_backend_compatibility()
