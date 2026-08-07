"""HTTP boundary checks for the assertion-only workspace route."""

from __future__ import annotations

import pytest
import logging

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
    monkeypatch.setattr(blueway_router, "project_workspace", lambda _: {
        "schema_version": "teeechr.workspace.v1", "status": "ready",
    })
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
        record = next(
            item for item in caplog.records
            if item.message == "blueway_workspace_request_received" and item.request_id
        )
        assert record.request_id == "slice-a-route-001"
        assert record.course_id == "course-1"
        assert record.has_term is True
        altered = {"course_id": "course-2", "term_id": "fall"}
        assert client.post("/api/v1/integrations/blueway/workspace", headers=headers, json=altered).status_code == 400
        old_contract = {"external_course_id": "course-1", "external_term_id": "fall"}
        assert client.post("/api/v1/integrations/blueway/workspace", headers=headers, json=old_contract).status_code == 422
        extra = {**valid, "user_id": "attacker"}
        assert client.post("/api/v1/integrations/blueway/workspace", headers=headers, json=extra).status_code == 422
