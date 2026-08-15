"""HTTP boundary checks for the assertion-only workspace route."""

from __future__ import annotations

import logging

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
from fastapi import FastAPI

from deeptutor.integrations.blueway import router as blueway_router


def test_route_requires_bearer_and_rejects_body_identity_override(monkeypatch, caplog) -> None:
    app = FastAPI()
    app.include_router(blueway_router.workspace_router, prefix="/api/v1/integrations/blueway")
    claims = {
        "external_course_id": "course-1", "external_term_id": "fall",
    }
    monkeypatch.setattr(blueway_router, "verify_assertion", lambda _: dict(claims))
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(blueway_router, "project_workspace", lambda _, **kwargs: (
        calls.append(kwargs) or {
            "schema_version": "teeechr.workspace.v1", "status": "ready",
        }
    ))
    caplog.set_level(logging.INFO, logger="deeptutor.integrations.blueway.router")
    with TestClient(app) as client:
        assert client.post("/api/v1/integrations/blueway/workspace", json={"course_id": "course-1", "term_id": "fall"}).status_code == 401
        headers = {"Authorization": "Bearer signed-assertion"}
        valid = {"course_id": "course-1", "term_id": "fall"}
        response = client.post(
            "/api/v1/integrations/blueway/workspace",
            headers={**headers, "X-Request-ID": "slice-a-route-001"},
            json=valid,
        )
        assert response.status_code == 200
        assert calls == [{"consume_replay": True, "request_ref": "slice-a-route-001"}]
        assert not any("course-1" in record.getMessage() for record in caplog.records)
        altered = {"course_id": "course-2", "term_id": "fall"}
        assert client.post("/api/v1/integrations/blueway/workspace", headers=headers, json=altered).status_code == 400
        old_contract = {"external_course_id": "course-1", "external_term_id": "fall"}
        assert client.post("/api/v1/integrations/blueway/workspace", headers=headers, json=old_contract).status_code == 422
        extra = {**valid, "user_id": "attacker"}
        assert client.post("/api/v1/integrations/blueway/workspace", headers=headers, json=extra).status_code == 422


def test_revoke_route_requires_distinct_scope_and_fences_exact_identity(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(blueway_router.workspace_router, prefix="/api/v1/integrations/blueway")
    claims = {
        "external_course_id": "course-1", "external_term_id": "fall",
        "authorization_id": "auth-1", "client_id": "blueway-client",
        "sub": "blueway-subject", "subject_hash": "subject-hash",
        "scope": "teeechr.workspace.revoke.v1", "jti": "revoke-jti", "exp": 1_800_000_060,
    }
    monkeypatch.setattr(blueway_router, "verify_assertion", lambda _, **kwargs: (
        claims if kwargs.get("expected_scope") == "teeechr.workspace.revoke.v1" else (_ for _ in ()).throw(AssertionError())
    ))
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(blueway_router, "revoke_workspace_authorization", lambda value: calls.append(value))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/integrations/blueway/workspace/revoke",
            headers={"Authorization": "Bearer signed-revocation"},
            json={"course_id": "course-1", "term_id": "fall"},
        )
    assert response.status_code == 204
    assert calls == [claims]
