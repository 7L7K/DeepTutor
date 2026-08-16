"""Structural authorization contracts for admin-only API surfaces."""

from __future__ import annotations

import importlib

import pytest

from deeptutor.api.routers.auth import require_admin


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
    assert any(
        dependency.dependency is require_admin for dependency in module.router.dependencies
    )


def test_subagent_management_routes_are_admin_only_but_partner_routes_are_not() -> None:
    module = importlib.import_module("deeptutor.api.routers.subagents")
    routes = {route.path: route for route in module.router.routes}

    for path in ("/detect", "/backends/options", "/backends/{kind}/sync", "/settings"):
        route = routes[path]
        assert any(
            dependency.call is require_admin for dependency in route.dependant.dependencies
        )

    for path in ("/partners", "/connections"):
        route = routes[path]
        assert all(
            dependency.call is not require_admin for dependency in route.dependant.dependencies
        )


def test_provider_connection_tests_are_admin_only() -> None:
    module = importlib.import_module("deeptutor.api.routers.system")
    routes = {route.path: route for route in module.router.routes}

    for path in ("/test/llm", "/test/embeddings", "/test/search"):
        route = routes[path]
        assert any(
            dependency.call is require_admin for dependency in route.dependant.dependencies
        )
