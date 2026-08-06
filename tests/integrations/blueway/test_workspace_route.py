"""HTTP boundary checks for the assertion-only workspace route."""

from __future__ import annotations

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
from fastapi import FastAPI

from deeptutor.integrations.blueway import router as blueway_router


def test_route_requires_bearer_and_rejects_body_identity_override(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(blueway_router.workspace_router, prefix="/api/v1/integrations/blueway")
    claims = {
        "external_course_id": "course-1", "external_term_id": "fall",
    }
    monkeypatch.setattr(blueway_router, "verify_assertion", lambda _: dict(claims))
    monkeypatch.setattr(blueway_router, "project_workspace", lambda _: {
        "schema_version": "teeechr.workspace.v1", "status": "ready",
    })
    with TestClient(app) as client:
        assert client.post("/api/v1/integrations/blueway/workspace", json={"course_id": "course-1", "term_id": "fall"}).status_code == 401
        headers = {"Authorization": "Bearer signed-assertion"}
        valid = {"course_id": "course-1", "term_id": "fall"}
        assert client.post("/api/v1/integrations/blueway/workspace", headers=headers, json=valid).status_code == 200
        altered = {"course_id": "course-2", "term_id": "fall"}
        assert client.post("/api/v1/integrations/blueway/workspace", headers=headers, json=altered).status_code == 400
        old_contract = {"external_course_id": "course-1", "external_term_id": "fall"}
        assert client.post("/api/v1/integrations/blueway/workspace", headers=headers, json=old_contract).status_code == 422
        extra = {**valid, "user_id": "attacker"}
        assert client.post("/api/v1/integrations/blueway/workspace", headers=headers, json=extra).status_code == 422
