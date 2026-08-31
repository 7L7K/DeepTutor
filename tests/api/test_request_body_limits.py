from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from deeptutor.api.request_body_limits import (
    _MASTERY_STRUCTURE_BODY_BYTES,
    _NOTEBOOK_UPSERT_PATH,
    _QUIZ_RESULTS_BODY_BYTES,
    _VOICE_STT_BODY_BYTES,
    _VOICE_STT_PATH,
    _VOICE_TTS_BODY_BYTES,
    _VOICE_TTS_PATH,
    NotebookUpsertBodyLimitMiddleware,
    QuotaExceeded,
    _request_body_limit,
    partner_chat_body_limit,
)


def _limited_app(seen: list[int], path: str = _NOTEBOOK_UPSERT_PATH) -> FastAPI:
    app = FastAPI()
    app.add_middleware(NotebookUpsertBodyLimitMiddleware)

    @app.post(path)
    async def upsert(request: Request):
        body = await request.body()
        seen.append(len(body))
        return {"size": len(body)}

    @app.post("/api/v1/courses/{course_id}/sources")
    async def course_source(request: Request):
        body = await request.body()
        seen.append(len(body))
        return {"size": len(body)}

    @app.post("/api/v1/courses/{course_id}/sources/nested")
    async def nested_course_path(request: Request):
        body = await request.body()
        seen.append(len(body))
        return {"size": len(body)}

    return app


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (_VOICE_TTS_PATH, _VOICE_TTS_BODY_BYTES),
        (_VOICE_STT_PATH, _VOICE_STT_BODY_BYTES),
    ],
)
def test_voice_routes_have_request_body_limits(path: str, expected: int) -> None:
    assert _request_body_limit({"path": path, "method": "POST"}) == expected


def test_partner_chat_routes_have_policy_sized_raw_body_limits(monkeypatch) -> None:
    class Limits:
        max_total_bytes = 6

    monkeypatch.setattr(
        "deeptutor.api.request_body_limits.get_chat_attachment_limits", lambda: Limits()
    )
    expected = partner_chat_body_limit()
    assert _request_body_limit({"path": "/api/v1/partners/demo/chat", "method": "POST"}) == expected
    assert (
        _request_body_limit({"path": "/api/v1/partners/demo/chat/execute-stream", "method": "POST"})
        == expected
    )
    assert (
        _request_body_limit({"path": "/api/v1/partners/demo/chat/nested", "method": "POST"}) is None
    )


def test_content_length_over_limit_is_rejected_before_downstream(monkeypatch) -> None:
    monkeypatch.setattr("deeptutor.api.request_body_limits.notebook_upsert_body_limit", lambda: 8)
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


def test_partner_chat_body_is_rejected_before_fastapi_parsing(monkeypatch) -> None:
    monkeypatch.setattr("deeptutor.api.request_body_limits.partner_chat_body_limit", lambda: 8)
    seen: list[int] = []
    path = "/api/v1/partners/demo/chat"

    with TestClient(_limited_app(seen, path)) as client:
        response = client.post(
            path,
            content=b"123456789",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 413
    assert seen == []


@pytest.mark.parametrize("body", [b"ok", b"12345678"])
def test_notebook_body_at_or_under_limit_reaches_route(monkeypatch, body: bytes) -> None:
    monkeypatch.setattr("deeptutor.api.request_body_limits.notebook_upsert_body_limit", lambda: 8)
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
    monkeypatch.setattr("deeptutor.api.request_body_limits.notebook_upsert_body_limit", lambda: 8)
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


def test_voice_stt_intake_quota_rejects_before_downstream(monkeypatch) -> None:
    class DenyQuota:
        async def acquire(self, _key: str):
            raise QuotaExceeded("busy")

    monkeypatch.setattr("deeptutor.api.request_body_limits._VOICE_STT_INTAKE_QUOTA", DenyQuota())
    seen: list[int] = []

    with TestClient(_limited_app(seen, _VOICE_STT_PATH)) as client:
        response = client.post(
            _VOICE_STT_PATH,
            content=b"not parsed",
            headers={"content-type": "application/octet-stream"},
        )

    assert response.status_code == 429
    assert response.json() == {"detail": "Request capacity is busy. Retry shortly"}
    assert response.headers["retry-after"] == "1"
    assert seen == []


@pytest.mark.parametrize("content_length", [b"invalid", b"-1"])
def test_invalid_content_length_is_rejected(monkeypatch, content_length: bytes) -> None:
    monkeypatch.setattr("deeptutor.api.request_body_limits.notebook_upsert_body_limit", lambda: 8)
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


@pytest.mark.parametrize(
    ("path", "expected_limit"),
    [
        ("/api/v1/notebook/add_record", 64 * 1024),
        ("/api/v1/notebook/add_record/", 64 * 1024),
        ("/api/v1/notebook/add_record_with_summary", 64 * 1024),
        ("/api/v1/notebook/add_record_with_summary/", 64 * 1024),
        ("/api/v1/learning/progress/book-1/generate-from-notebook", 96 * 1024),
        ("/api/v1/learning/progress/book-1/generate-from-notebook/", 96 * 1024),
        ("/api/v1/learning/progress/book-1/init-modules", _MASTERY_STRUCTURE_BODY_BYTES),
        ("/api/v1/learning/progress/book-1/import-from-book", _MASTERY_STRUCTURE_BODY_BYTES),
        ("/api/v1/sessions/session-1/quiz-results", _QUIZ_RESULTS_BODY_BYTES),
    ],
)
def test_notebook_llm_routes_have_raw_body_limits(path: str, expected_limit: int) -> None:
    assert _request_body_limit({"method": "POST", "path": path}) == expected_limit


def test_notebook_summary_trailing_slash_is_rejected_before_downstream(monkeypatch) -> None:
    monkeypatch.setattr("deeptutor.api.request_body_limits._NOTEBOOK_SUMMARY_BODY_BYTES", 8)
    seen: list[int] = []
    path = "/api/v1/notebook/add_record/"

    with TestClient(_limited_app(seen, path)) as client:
        response = client.post(
            path,
            content=b"123456789",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 413
    assert seen == []


def test_mastery_notebook_trailing_slash_is_rejected_before_downstream(monkeypatch) -> None:
    monkeypatch.setattr("deeptutor.api.request_body_limits._MASTERY_NOTEBOOK_BODY_BYTES", 8)
    seen: list[int] = []
    path = "/api/v1/learning/progress/book-1/generate-from-notebook/"

    with TestClient(_limited_app(seen, path)) as client:
        response = client.post(
            path,
            content=b"123456789",
            headers={"content-type": "application/json"},
            follow_redirects=False,
        )

    assert response.status_code == 413
    assert seen == []


def test_exact_course_source_post_is_limited_before_multipart_parsing(monkeypatch) -> None:
    monkeypatch.setattr("deeptutor.api.request_body_limits.course_source_body_limit", lambda: 8)
    seen: list[int] = []

    with TestClient(_limited_app(seen)) as client:
        rejected = client.post(
            "/api/v1/courses/crs_one/sources",
            content=b"123456789",
            headers={"content-type": "multipart/form-data; boundary=test"},
        )
        trailing_slash = client.post(
            "/api/v1/courses/crs_one/sources/",
            content=b"123456789",
            headers={"content-type": "multipart/form-data; boundary=test"},
            follow_redirects=False,
        )
        nested = client.post(
            "/api/v1/courses/crs_one/sources/nested",
            content=b"123456789",
        )

    assert rejected.status_code == 413
    assert trailing_slash.status_code == 413
    assert nested.status_code == 200
    assert seen == [9]


def test_chunked_course_source_body_is_cumulatively_limited(monkeypatch) -> None:
    monkeypatch.setattr("deeptutor.api.request_body_limits.course_source_body_limit", lambda: 8)
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
        path = "/api/v1/courses/crs_one/sources"
        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "headers": [(b"content-type", b"multipart/form-data")],
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 80),
            },
            receive,
            send,
        )

    asyncio.run(invoke())

    assert sent[0]["status"] == 413
    assert seen == []
