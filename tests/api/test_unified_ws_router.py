from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

import deeptutor.api.routers.unified_ws as unified_ws_router

router = unified_ws_router.router


class _FakeAccessManager:
    async def get_tester_from_token(self, _token: str) -> dict:
        return {
            "id": "tester-1",
            "tester_id": "tester-1",
            "display_name": "Tester One",
        }


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


def test_unified_ws_heartbeat_ping_returns_pong(monkeypatch) -> None:
    monkeypatch.setattr(
        unified_ws_router,
        "get_access_manager",
        lambda: _FakeAccessManager(),
    )
    with TestClient(_build_app()) as client:
        with client.websocket_connect("/api/v1/ws") as websocket:
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json() == {"type": "pong"}


def test_unified_ws_unknown_type_still_returns_error(monkeypatch) -> None:
    monkeypatch.setattr(
        unified_ws_router,
        "get_access_manager",
        lambda: _FakeAccessManager(),
    )
    with TestClient(_build_app()) as client:
        with client.websocket_connect("/api/v1/ws") as websocket:
            websocket.send_json({"type": "mystery"})
            assert websocket.receive_json() == {
                "type": "error",
                "content": "Unknown type: mystery",
            }
