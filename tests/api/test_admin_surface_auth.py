"""Structural authorization contracts for admin-only API surfaces."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers.auth import require_admin, require_auth


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
    ):
        route = routes[(path, frozenset({method}))]
        assert any(
            dependency.call is require_admin for dependency in route.dependant.dependencies
        ), f"{method} {path} must require admin access"

    # Learner-owned KB creation, upload, and content reads keep their existing
    # authenticated-user policy; this change must not turn them into admin APIs.
    for path, method in (
        ("/create", "POST"),
        ("/{kb_name}/upload", "POST"),
        ("/{kb_name}", "GET"),
        ("/{kb_name}/files", "GET"),
        ("/{kb_name}/config", "GET"),
    ):
        route = routes[(path, frozenset({method}))]
        assert all(
            dependency.call is not require_admin for dependency in route.dependant.dependencies
        ), f"{method} {path} must remain available to authenticated learners"


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
