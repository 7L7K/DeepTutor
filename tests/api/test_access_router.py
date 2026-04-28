from __future__ import annotations

import asyncio
import importlib
import time

import pytest

from deeptutor.services.access import ACCESS_COOKIE_NAME, AccessManager, hash_access_code
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
access_router = importlib.import_module("deeptutor.api.routers.access")


def _build_app(store: SQLiteSessionStore) -> FastAPI:
    app = FastAPI()
    app.include_router(access_router.router, prefix="/api/v1/access")
    return app


@pytest.fixture
def store(tmp_path, monkeypatch) -> SQLiteSessionStore:
    instance = SQLiteSessionStore(db_path=tmp_path / "access.db")
    monkeypatch.setattr(
        access_router,
        "get_access_manager",
        lambda: AccessManager(instance),
    )
    return instance


def test_claim_valid_code_sets_cookie_and_me_returns_tester(store: SQLiteSessionStore) -> None:
    asyncio.run(
        store.upsert_tester(
            "owner-test",
            "Owner Test",
            hash_access_code("owner-code"),
        )
    )

    with TestClient(_build_app(store)) as client:
        claim = client.post("/api/v1/access/claim", json={"access_code": "owner-code"})
        assert claim.status_code == 200
        assert claim.json()["tester"]["tester_id"] == "owner-test"
        assert ACCESS_COOKIE_NAME in claim.cookies

        me = client.get("/api/v1/access/me")
        assert me.status_code == 200
        assert me.json()["tester"]["display_name"] == "Owner Test"


def test_invalid_code_is_rejected_and_sets_no_cookie(store: SQLiteSessionStore) -> None:
    asyncio.run(
        store.upsert_tester(
            "owner-test",
            "Owner Test",
            hash_access_code("owner-code"),
        )
    )

    with TestClient(_build_app(store)) as client:
        response = client.post("/api/v1/access/claim", json={"access_code": "wrong"})
        assert response.status_code == 401
        assert ACCESS_COOKIE_NAME not in response.cookies


def test_me_requires_cookie(store: SQLiteSessionStore) -> None:
    with TestClient(_build_app(store)) as client:
        response = client.get("/api/v1/access/me")
        assert response.status_code == 401


def test_logout_clears_cookie(store: SQLiteSessionStore) -> None:
    asyncio.run(
        store.upsert_tester(
            "owner-test",
            "Owner Test",
            hash_access_code("owner-code"),
        )
    )

    with TestClient(_build_app(store)) as client:
        claim = client.post("/api/v1/access/claim", json={"access_code": "owner-code"})
        assert claim.status_code == 200

        logout = client.post("/api/v1/access/logout")
        assert logout.status_code == 200

        me = client.get("/api/v1/access/me")
        assert me.status_code == 401


def test_disabled_tester_cannot_claim_code(store: SQLiteSessionStore) -> None:
    asyncio.run(
        store.upsert_tester(
            "owner-test",
            "Owner Test",
            hash_access_code("owner-code"),
            disabled_at=time.time(),
        )
    )

    with TestClient(_build_app(store)) as client:
        response = client.post("/api/v1/access/claim", json={"access_code": "owner-code"})
        assert response.status_code == 401
