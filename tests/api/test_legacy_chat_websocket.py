"""Production boundary tests for the obsolete chat WebSocket route."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import chat as chat_router


def test_production_rejects_legacy_chat_socket_before_auth_or_provider_work(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TEEECHR_ENVIRONMENT", "production")
    monkeypatch.delenv("TEEECHR_ENABLE_LEGACY_CHAT_WEBSOCKET", raising=False)

    from deeptutor.api.routers import auth as auth_router

    auth_started = False
    provider_started = False

    async def _unexpected_auth(_websocket):
        nonlocal auth_started
        auth_started = True
        raise AssertionError("disabled route must not start authentication")

    def _unexpected_provider():
        nonlocal provider_started
        provider_started = True
        raise AssertionError("disabled route must not read provider configuration")

    monkeypatch.setattr(auth_router, "ws_require_auth", _unexpected_auth)
    monkeypatch.setattr(chat_router, "get_llm_config", _unexpected_provider)

    class FakeWebSocket:
        def __init__(self) -> None:
            self.close_codes: list[int] = []

        async def close(self, *, code: int) -> None:
            self.close_codes.append(code)

    websocket = FakeWebSocket()
    asyncio.run(chat_router.websocket_chat(websocket))

    assert websocket.close_codes == [1008]
    assert auth_started is False
    assert provider_started is False


def test_production_legacy_socket_opt_in_is_explicit(monkeypatch) -> None:
    monkeypatch.setenv("TEEECHR_ENVIRONMENT", "production")
    monkeypatch.delenv("TEEECHR_ENABLE_LEGACY_CHAT_WEBSOCKET", raising=False)
    assert chat_router._legacy_chat_websocket_enabled() is False

    monkeypatch.setenv("TEEECHR_ENABLE_LEGACY_CHAT_WEBSOCKET", "true")
    assert chat_router._legacy_chat_websocket_enabled() is True


def test_production_legacy_socket_closure_does_not_affect_session_rest_api(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TEEECHR_ENVIRONMENT", "production")
    monkeypatch.delenv("TEEECHR_ENABLE_LEGACY_CHAT_WEBSOCKET", raising=False)

    class Sessions:
        def list_sessions(self, *, limit: int, include_messages: bool):
            assert limit == 20
            assert include_messages is False
            return [{"session_id": "session-1"}]

    monkeypatch.setattr(chat_router, "_get_session_manager", Sessions)
    app = FastAPI()
    app.include_router(chat_router.router, prefix="/api/v1")

    response = TestClient(app).get("/api/v1/chat/sessions")

    assert response.status_code == 200
    assert response.json() == [{"session_id": "session-1"}]
