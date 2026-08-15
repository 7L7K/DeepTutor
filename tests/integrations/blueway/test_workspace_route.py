"""HTTP boundary checks for the assertion-only workspace route."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
from fastapi import FastAPI

from deeptutor.integrations.blueway import router as blueway_router
from deeptutor.integrations.blueway.observability import safe_request_ref


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
        assert calls == [{"consume_replay": True, "request_ref": safe_request_ref("slice-a-route-001")}]
        assert "slice-a-route-001" not in repr(calls)
        assert not any("course-1" in record.getMessage() for record in caplog.records)
        altered = {"course_id": "course-2", "term_id": "fall"}
        assert client.post("/api/v1/integrations/blueway/workspace", headers=headers, json=altered).status_code == 400
        old_contract = {"external_course_id": "course-1", "external_term_id": "fall"}
        assert client.post("/api/v1/integrations/blueway/workspace", headers=headers, json=old_contract).status_code == 422
        extra = {**valid, "user_id": "attacker"}
        assert client.post("/api/v1/integrations/blueway/workspace", headers=headers, json=extra).status_code == 422


def test_launch_route_hashes_caller_request_reference_before_emission(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(blueway_router.router, prefix="/api/v1/integrations/blueway")
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(
        blueway_router,
        "get_current_course_service",
        lambda: SimpleNamespace(
            repository=SimpleNamespace(owner_user_id="owner-a", ensure_schema=lambda: None)
        ),
    )
    monkeypatch.setattr(
        blueway_router,
        "resolve_course_launch",
        lambda *_args, **_kwargs: SimpleNamespace(
            status="ready",
            trace_id="bwr_11111111-1111-4111-8111-111111111111",
            connection_ref="bwc_connection",
            as_dict=lambda: {"status": "ready"},
        ),
    )
    monkeypatch.setattr(
        blueway_router,
        "emit_blueway_event",
        lambda _event, **fields: emitted.append(fields),
    )

    raw_request_id = "phone-attempt-20260815-001"
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/integrations/blueway/launch?external_course_id=course-1",
            headers={"X-Request-ID": raw_request_id},
        )

    assert response.status_code == 200
    assert emitted == [
        {
            "trace_id": "bwr_11111111-1111-4111-8111-111111111111",
            "connection_ref": "bwc_connection",
            "request_ref": safe_request_ref(raw_request_id),
            "reason_code": "ready",
            "outcome": "allowed",
        }
    ]
    assert raw_request_id not in repr(emitted)


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
