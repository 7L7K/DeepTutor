"""Tests for FastAPI CORS settings."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
import pytest

from deeptutor.api import main as api_main


def test_cors_allows_remote_http_origins_when_auth_disabled(
    monkeypatch,
) -> None:
    # Explicitly disable auth for this test. Removing the environment variable
    # must not silently override the persisted runtime setting.
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.delenv("CORS_ORIGIN", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("FRONTEND_PORT", "3782")

    settings = api_main._build_cors_settings()

    assert settings["allow_origin_regex"] == r"https?://.*"
    assert "http://localhost:3782" in settings["allow_origins"]
    assert "http://127.0.0.1:3782" in settings["allow_origins"]


def test_cors_requires_explicit_origins_when_auth_enabled(monkeypatch) -> None:
    monkeypatch.delenv("TEEECHR_ENVIRONMENT", raising=False)
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


def test_production_cors_allows_only_configured_https_origins(monkeypatch) -> None:
    monkeypatch.setenv("TEEECHR_ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "https://learn.example.com, http://localhost:3000, https://localhost, https://127.0.0.1, https://[::1], *, null, https://staff.example.com/",
    )

    settings = api_main._build_cors_settings()

    assert settings["mode"] == "production"
    assert settings["allow_origin_regex"] is None
    assert settings["allow_origins"] == [
        "https://learn.example.com",
        "https://staff.example.com",
    ]
    assert "http://localhost:3000" not in settings["allow_origins"]
    assert "https://localhost" not in settings["allow_origins"]
    assert "https://127.0.0.1" not in settings["allow_origins"]
    assert "https://[::1]" not in settings["allow_origins"]


def test_auth_enabled_cors_never_allows_wildcard_origin(monkeypatch) -> None:
    monkeypatch.setenv("TEEECHR_ENVIRONMENT", "development")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("CORS_ORIGIN", "*")
    monkeypatch.setenv("CORS_ORIGINS", "null, https://learn.example.com")

    settings = api_main._build_cors_settings()

    assert "*" not in settings["allow_origins"]
    assert "null" not in settings["allow_origins"]
    assert "https://learn.example.com" in settings["allow_origins"]


def test_production_startup_rejects_disabled_or_missing_auth(monkeypatch) -> None:
    monkeypatch.setattr(api_main, "is_production_environment", lambda: True)
    monkeypatch.setattr(api_main, "load_auth_settings", lambda: {"enabled": False})

    with pytest.raises(RuntimeError, match="Production requires authentication"):
        api_main.validate_production_auth_configuration()


def test_production_startup_accepts_enabled_auth(monkeypatch) -> None:
    monkeypatch.setattr(api_main, "is_production_environment", lambda: True)
    monkeypatch.setattr(
        api_main,
        "load_auth_settings",
        lambda: {"enabled": True, "cookie_secure": True},
    )
    monkeypatch.setattr(api_main, "_has_durable_production_identity", lambda _settings: True)

    api_main.validate_production_auth_configuration()


def test_production_startup_rejects_insecure_auth_cookie(monkeypatch) -> None:
    monkeypatch.setattr(api_main, "is_production_environment", lambda: True)
    monkeypatch.setattr(
        api_main,
        "load_auth_settings",
        lambda: {"enabled": True, "cookie_secure": False},
    )

    with pytest.raises(RuntimeError, match="secure authentication cookies"):
        api_main.validate_production_auth_configuration()


def test_production_startup_rejects_missing_durable_identity(monkeypatch) -> None:
    monkeypatch.setattr(api_main, "is_production_environment", lambda: True)
    monkeypatch.setattr(
        api_main,
        "load_auth_settings",
        lambda: {"enabled": True, "cookie_secure": True},
    )
    monkeypatch.setattr(api_main, "_has_durable_production_identity", lambda _settings: False)

    with pytest.raises(RuntimeError, match="durable owner identity"):
        api_main.validate_production_auth_configuration()


def test_durable_identity_accepts_persisted_admin_store(monkeypatch, tmp_path) -> None:
    from deeptutor.multi_user import identity

    users_file = tmp_path / "auth" / "users.json"
    monkeypatch.setattr(identity, "USERS_FILE", users_file)
    assert not api_main._has_durable_production_identity({"enabled": True})

    users_file.parent.mkdir(parents=True)
    users_file.write_text(
        '{"owner": {"id": "u_owner", "hash": "hash", "role": "admin", "disabled": false}}',
        encoding="utf-8",
    )
    assert api_main._has_durable_production_identity({"enabled": True})


def test_durable_identity_accepts_persisted_single_user_bootstrap() -> None:
    assert api_main._has_durable_production_identity(
        {"enabled": True, "username": "owner", "password_hash": "hash"}
    )


def test_local_startup_allows_auth_disabled_for_single_user_development(monkeypatch) -> None:
    monkeypatch.setattr(api_main, "is_production_environment", lambda: False)
    monkeypatch.setattr(api_main, "load_auth_settings", lambda: {"enabled": False})

    api_main.validate_production_auth_configuration()


def test_production_websocket_origin_policy_matches_cors(monkeypatch) -> None:
    from deeptutor.services.config import load_system_settings
    from deeptutor.services.config.origins import browser_origins

    monkeypatch.setenv("TEEECHR_ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ORIGIN", "https://learn.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://staff.example.com")

    assert set(browser_origins(load_system_settings())) == {
        "https://learn.example.com",
        "https://staff.example.com",
    }


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


def test_auth_disabled_production_websocket_rejects_foreign_browser_origin(monkeypatch) -> None:
    from types import SimpleNamespace

    from deeptutor.api.routers import auth as auth_router

    closed: list[int] = []

    async def close(*, code: int) -> None:
        closed.append(code)

    websocket = SimpleNamespace(
        headers={"origin": "https://attacker.example"},
        close=close,
    )
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", False)
    monkeypatch.setattr(auth_router, "_BROWSER_ORIGINS", frozenset({"https://learn.example.com"}))
    monkeypatch.setattr(auth_router, "is_production_environment", lambda: True)

    result = asyncio.run(auth_router.ws_require_auth(websocket))

    assert result is auth_router.ws_auth_failed
    assert closed == [4003]


def test_phase2_startup_rejects_pocketbase(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.pocketbase_client.is_pocketbase_enabled", lambda: True
    )
    with pytest.raises(RuntimeError, match="PocketBase Course ownership"):
        api_main.validate_course_backend_compatibility()
