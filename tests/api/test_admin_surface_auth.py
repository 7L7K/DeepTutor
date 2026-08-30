"""Structural authorization contracts for admin-only API surfaces."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers.auth import (
    require_admin,
    require_auth,
    require_course_source_upload,
)


@pytest.mark.parametrize(
    "module_name",
    [
        "capabilities_settings",
        "memory",
        "co_writer",
        "book",
        "space_cli_apps",
        "plugins_api",
    ],
)
def test_admin_only_routers_inherit_require_admin(module_name: str) -> None:
    module = importlib.import_module(f"deeptutor.api.routers.{module_name}")
    assert any(dependency.dependency is require_admin for dependency in module.router.dependencies)


def test_subagent_management_routes_are_admin_only_but_partner_routes_are_not() -> None:
    module = importlib.import_module("deeptutor.api.routers.subagents")
    routes = {route.path: route for route in module.router.routes}

    for path in ("/detect", "/backends/options", "/backends/{kind}/sync", "/settings"):
        route = routes[path]
        assert any(dependency.call is require_admin for dependency in route.dependant.dependencies)

    for path in ("/partners", "/connections", "/consult-settings"):
        route = routes[path]
        assert all(
            dependency.call is not require_admin for dependency in route.dependant.dependencies
        )

    consult_settings = routes["/consult-settings"]
    assert any(
        dependency.call is require_auth for dependency in consult_settings.dependant.dependencies
    )


def test_regular_learner_can_read_consult_budget_but_not_admin_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("deeptutor.api.routers.subagents")
    monkeypatch.setattr(
        module,
        "load_subagent_settings",
        lambda: SimpleNamespace(consult_budget=5),
    )

    app = FastAPI()
    app.include_router(module.router, prefix="/api/v1/subagents")
    app.dependency_overrides[require_auth] = lambda: object()

    async def reject_regular_user() -> None:
        raise HTTPException(status_code=403, detail="Admin access required")

    app.dependency_overrides[require_admin] = reject_regular_user
    with TestClient(app) as client:
        consult_response = client.get("/api/v1/subagents/consult-settings")
        admin_response = client.get("/api/v1/subagents/settings")

    assert consult_response.status_code == 200
    assert consult_response.json() == {"consult_budget": 5}
    assert admin_response.status_code == 403


def test_provider_connection_tests_are_admin_only() -> None:
    module = importlib.import_module("deeptutor.api.routers.system")
    routes = {route.path: route for route in module.router.routes}

    for path in ("/test/llm", "/test/embeddings", "/test/search"):
        route = routes[path]
        assert any(dependency.call is require_admin for dependency in route.dependant.dependencies)


def test_deployment_wide_knowledge_settings_are_admin_only() -> None:
    module = importlib.import_module("deeptutor.api.routers.knowledge")
    routes = {
        (route.path, frozenset(route.methods)): route
        for route in module.router.routes
        if hasattr(route, "methods")
    }

    for path, method in (
        ("/health", "GET"),
        ("/rag-providers", "GET"),
        ("/rag-providers/{provider}/mode", "PUT"),
        ("/rag-pipelines/pageindex/config", "GET"),
        ("/rag-pipelines/pageindex/config", "PUT"),
        ("/rag-pipelines/llamaindex/config", "GET"),
        ("/rag-pipelines/llamaindex/config", "PUT"),
        ("/rag-pipelines/graphrag/config", "GET"),
        ("/rag-pipelines/graphrag/config", "PUT"),
        ("/rag-pipelines/lightrag/config", "GET"),
        ("/rag-pipelines/lightrag/config", "PUT"),
        ("/rag-pipelines/{provider}/preflight", "GET"),
        ("/rag-pipelines/model-options", "GET"),
        ("/rag-pipelines/active-model", "PUT"),
    ):
        route = routes[(path, frozenset({method}))]
        assert any(
            dependency.call is require_admin for dependency in route.dependant.dependencies
        ), f"{method} {path} must require admin access"


def test_host_path_and_external_connector_knowledge_routes_are_admin_only() -> None:
    module = importlib.import_module("deeptutor.api.routers.knowledge")
    routes = {
        (route.path, frozenset(route.methods)): route
        for route in module.router.routes
        if hasattr(route, "methods")
    }

    for path, method in (
        ("/configs", "GET"),
        ("/configs/sync", "POST"),
        ("/connect-obsidian", "POST"),
        ("/probe-folder", "POST"),
        ("/connect-folder", "POST"),
        ("/probe-lightrag-server", "POST"),
        ("/connect-lightrag-server", "POST"),
        ("/probe-ima", "POST"),
        ("/connect-ima", "POST"),
        ("/{kb_name}/link-folder", "POST"),
        ("/{kb_name}/linked-folders", "GET"),
        ("/{kb_name}/linked-folders/{folder_id}", "DELETE"),
        ("/{kb_name}/sync-folder/{folder_id}", "POST"),
        # Personal indexing remains deployment-owned for the controlled beta:
        # one learner account must not be able to consume shared disk, CPU, or
        # embedding-provider spend without durable per-user budgets.
        ("/create", "POST"),
        ("/{kb_name}/upload", "POST"),
        ("/{kb_name}/reindex", "POST"),
        ("/{kb_name}/retry", "POST"),
    ):
        route = routes[(path, frozenset({method}))]
        assert any(
            dependency.call is require_admin for dependency in route.dependant.dependencies
        ), f"{method} {path} must require admin access"

    # Learners retain assigned/personal KB reads and bounded retrieval choices;
    # only indexing work moves behind the controlled-beta owner boundary.
    for path, method in (
        ("/{kb_name}", "GET"),
        ("/{kb_name}/files", "GET"),
        ("/{kb_name}/config", "GET"),
    ):
        route = routes[(path, frozenset({method}))]
        assert all(
            dependency.call is not require_admin for dependency in route.dependant.dependencies
        ), f"{method} {path} must remain available to authenticated learners"


def test_course_source_indexing_requires_explicit_admission_but_reads_remain_available() -> None:
    module = importlib.import_module("deeptutor.api.routers.courses")
    routes = {
        (route.path, frozenset(route.methods)): route
        for route in module.router.routes
        if hasattr(route, "methods")
    }

    upload = routes[("/{course_id}/sources", frozenset({"POST"}))]
    assert any(
        dependency.call is require_course_source_upload
        for dependency in upload.dependant.dependencies
    )
    archive = routes[("/{course_id}/sources/{source_id}/archive", frozenset({"POST"}))]
    assert any(
        dependency.call is require_course_source_upload
        for dependency in archive.dependant.dependencies
    )

    for path in ("/{course_id}/sources", "/{course_id}/sources/{source_id}"):
        route = routes[(path, frozenset({"GET"}))]
        assert all(
            dependency.call is not require_admin for dependency in route.dependant.dependencies
        ), f"GET {path} must remain available to authenticated learners"


def test_regular_learner_course_source_upload_stops_before_ingestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("deeptutor.api.routers.courses")
    from starlette.requests import Request

    touched: list[str] = []
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.prepare_source_upload",
        lambda **_kwargs: touched.append("ingestion"),
    )
    original_form = Request.form

    def record_form(self, **kwargs):
        touched.append("multipart")
        return original_form(self, **kwargs)

    monkeypatch.setattr(Request, "form", record_form)

    async def reject_regular_user() -> None:
        raise HTTPException(
            status_code=403,
            detail="Course material upload access required",
        )

    app = FastAPI()
    app.include_router(module.router, prefix="/api/v1/courses")
    app.dependency_overrides[require_course_source_upload] = reject_regular_user
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/courses/crs_demo/sources",
            data={"display_name": "notes.txt"},
            files={"files": ("notes.txt", b"bounded notes", "text/plain")},
            headers={"Idempotency-Key": "learner-source-blocked"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Course material upload access required"
    assert touched == []


def test_course_source_archive_requires_live_admission_before_service_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.api.routers import courses as module
    from deeptutor.courses.models import CourseSource
    from deeptutor.services.auth import TokenPayload

    calls: list[tuple[str, str, int]] = []

    class Service:
        async def archive_source(
            self, course_id: str, source_id: str, expected_revision: int
        ) -> CourseSource:
            calls.append((course_id, source_id, expected_revision))
            return CourseSource(
                id=source_id,
                course_id=course_id,
                kind="notes",
                display_name="notes.txt",
                state="archived",
                manifest=[],
                content_sha256="a" * 64,
                revision=expected_revision + 1,
                created_at=1,
                updated_at=2,
            )

    monkeypatch.setattr(module, "_service", lambda: Service())
    app = FastAPI()
    app.include_router(module.router, prefix="/api/v1/courses")

    async def deny() -> None:
        raise HTTPException(
            status_code=403,
            detail="Course material upload access required",
        )

    app.dependency_overrides[require_course_source_upload] = deny
    with TestClient(app) as client:
        denied = client.post(
            "/api/v1/courses/crs_one/sources/src_one/archive",
            json={"expected_revision": 1},
        )
    assert denied.status_code == 403
    assert calls == []

    learner = TokenPayload("learner", "user", "user-one")
    app.dependency_overrides[require_course_source_upload] = lambda: learner
    with TestClient(app) as client:
        admitted = client.post(
            "/api/v1/courses/crs_one/sources/src_one/archive",
            json={"expected_revision": 1},
        )
    assert admitted.status_code == 200
    assert admitted.json()["state"] == "archived"
    assert calls == [("crs_one", "src_one", 1)]


@pytest.mark.asyncio
async def test_course_source_upload_dependency_is_strict_deny_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.services.auth import TokenPayload

    learner = TokenPayload(username="learner", role="user", user_id="user-one")
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "load_grant", lambda _user_id: {})
    with pytest.raises(HTTPException) as denied:
        await require_course_source_upload(learner)
    assert denied.value.status_code == 403

    monkeypatch.setattr(
        auth_router,
        "load_grant",
        lambda _user_id: {"course_source_uploads": True},
    )
    assert await require_course_source_upload(learner) == learner


def test_granted_learner_upload_uses_only_the_server_selected_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.api.routers import courses as module
    from deeptutor.courses.models import CourseSource
    from deeptutor.services.auth import TokenPayload

    learner = TokenPayload(username="learner", role="user", user_id="user-one")
    seen: list[dict] = []

    def prepared(**kwargs):
        seen.append(kwargs)
        return (
            CourseSource(
                id="src_one",
                course_id=kwargs["course_id"],
                kind=kwargs["kind"],
                display_name=kwargs["display_name"],
                manifest=[],
                content_sha256="a" * 64,
                operation_id="course_source_test",
                created_at=1,
                updated_at=1,
            ),
            None,
        )

    monkeypatch.setattr("deeptutor.courses.ingestion.prepare_source_upload", prepared)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/v1/courses")
    app.dependency_overrides[require_course_source_upload] = lambda: learner
    with TestClient(app) as client:
        rejected = client.post(
            "/api/v1/courses/crs_one/sources",
            data={"display_name": "notes.txt", "rag_provider": "graphrag"},
            files={"files": ("notes.txt", b"notes", "text/plain")},
            headers={"Idempotency-Key": "learner-provider-override"},
        )
        admitted = client.post(
            "/api/v1/courses/crs_one/sources",
            data={"display_name": "notes.txt"},
            files={"files": ("notes.txt", b"notes", "text/plain")},
            headers={"Idempotency-Key": "learner-server-provider"},
        )

    assert rejected.status_code == 403
    assert admitted.status_code == 202
    assert len(seen) == 1
    assert seen[0]["rag_provider"] is None


def test_regular_knowledge_account_cannot_read_global_model_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("deeptutor.api.routers.knowledge")
    monkeypatch.setattr(module, "_model_options_payload", lambda kinds: {"kinds": kinds})

    app = FastAPI()
    app.include_router(module.router, prefix="/api/v1/knowledge")

    async def reject_regular_user() -> None:
        raise HTTPException(status_code=403, detail="Admin access required")

    app.dependency_overrides[require_admin] = reject_regular_user
    with TestClient(app) as client:
        response = client.get("/api/v1/knowledge/rag-pipelines/model-options")
    assert response.status_code == 403


def test_admin_can_read_global_model_options(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("deeptutor.api.routers.knowledge")
    monkeypatch.setattr(module, "_model_options_payload", lambda kinds: {"kinds": kinds})

    app = FastAPI()
    app.include_router(module.router, prefix="/api/v1/knowledge")
    app.dependency_overrides[require_admin] = lambda: None

    with TestClient(app) as client:
        response = client.get("/api/v1/knowledge/rag-pipelines/model-options?kinds=llm")
    assert response.status_code == 200
    assert response.json() == {"kinds": ["llm"]}
