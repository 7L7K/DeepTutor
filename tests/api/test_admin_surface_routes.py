"""Deployment-wide TEEECHR surfaces are administrator-only.

The public UI hides these routes, but the API must enforce the same boundary
for direct requests, stale clients, and WebSocket upgrades.
"""

from __future__ import annotations

from deeptutor.api import main
from deeptutor.api.routers.auth import require_admin

def test_admin_only_surface_routers_inherit_require_admin():
    prefixes = (
        "/api/v1/co_writer",
        "/api/v1/book",
        "/api/v1/memory",
        "/api/v1/imports",
        "/api/v1/subagents",
        "/api/v1/agent-config",
        "/api/v1/capabilities",
    )

    # FastAPI 0.135 keeps included routers as lazy _IncludedRouter wrappers;
    # inspect the include contract directly rather than relying on internal
    # route flattening.
    includes = {
        getattr(route.include_context, "prefix", ""): route.include_context
        for route in main.app.routes
        if hasattr(route, "include_context")
    }
    for prefix in prefixes:
        include = includes.get(prefix)
        assert include is not None, f"No include found for {prefix}"
        assert any(
            dependency.dependency is require_admin for dependency in include.dependencies
        ), f"{prefix} is not admin-gated"
