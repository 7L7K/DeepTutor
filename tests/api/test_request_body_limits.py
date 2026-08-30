from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from deeptutor.api.request_body_limits import (
    _NOTEBOOK_UPSERT_PATH,
    NotebookUpsertBodyLimitMiddleware,
)


def _limited_app(seen: list[int]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(NotebookUpsertBodyLimitMiddleware)

    @app.post(_NOTEBOOK_UPSERT_PATH)
    async def upsert(request: Request):
        body = await request.body()
        seen.append(len(body))
        return {"size": len(body)}

    return app


def test_content_length_over_limit_is_rejected_before_downstream(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.api.request_body_limits.notebook_upsert_body_limit", lambda: 8
    )
    seen: list[int] = []

    with TestClient(_limited_app(seen)) as client:
        response = client.post(
            _NOTEBOOK_UPSERT_PATH,
            content=b"123456789",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large"}
    assert seen == []


@pytest.mark.parametrize("body", [b"ok", b"12345678"])
def test_notebook_body_at_or_under_limit_reaches_route(monkeypatch, body: bytes) -> None:
    monkeypatch.setattr(
        "deeptutor.api.request_body_limits.notebook_upsert_body_limit", lambda: 8
    )
    seen: list[int] = []

    with TestClient(_limited_app(seen)) as client:
        response = client.post(
            _NOTEBOOK_UPSERT_PATH,
            content=body,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 200
    assert response.json() == {"size": len(body)}
    assert seen == [len(body)]


def test_chunked_body_over_limit_is_rejected_without_materializing(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.api.request_body_limits.notebook_upsert_body_limit", lambda: 8
    )
    seen: list[int] = []
    app = _limited_app(seen)
    messages = iter(
        [
            {"type": "http.request", "body": b"1234", "more_body": True},
            {"type": "http.request", "body": b"56789", "more_body": False},
        ]
    )
    sent: list[dict] = []

    async def receive() -> dict:
        return next(messages)

    async def send(message: dict) -> None:
        sent.append(message)

    async def invoke() -> None:
        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": _NOTEBOOK_UPSERT_PATH,
                "raw_path": _NOTEBOOK_UPSERT_PATH.encode(),
                "query_string": b"",
                "headers": [(b"content-type", b"application/json")],
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 80),
            },
            receive,
            send,
        )

    asyncio.run(invoke())

    assert sent[0]["status"] == 413
    assert seen == []


@pytest.mark.parametrize("content_length", [b"invalid", b"-1"])
def test_invalid_content_length_is_rejected(monkeypatch, content_length: bytes) -> None:
    monkeypatch.setattr(
        "deeptutor.api.request_body_limits.notebook_upsert_body_limit", lambda: 8
    )
    seen: list[int] = []
    app = _limited_app(seen)
    sent: list[dict] = []

    async def receive() -> dict:
        raise AssertionError("invalid content length must be rejected before receive")

    async def send(message: dict) -> None:
        sent.append(message)

    async def invoke() -> None:
        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": _NOTEBOOK_UPSERT_PATH,
                "raw_path": _NOTEBOOK_UPSERT_PATH.encode(),
                "query_string": b"",
                "headers": [(b"content-length", content_length)],
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 80),
            },
            receive,
            send,
        )

    asyncio.run(invoke())

    assert sent[0]["status"] == 413
    assert seen == []
