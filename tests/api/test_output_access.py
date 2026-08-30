"""Ownership checks for generated artifact delivery."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from deeptutor.api import main as api_main
from deeptutor.api.routers import auth as auth_router
from deeptutor.multi_user import paths as multi_user_paths
from deeptutor.services.auth import TokenPayload


def _configure_authenticated_users(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(multi_user_paths, "USERS_ROOT", tmp_path / "data" / "users")
    monkeypatch.setattr(multi_user_paths, "_path_services", {})

    identities = {
        "alice-token": TokenPayload(username="alice", role="user", user_id="u_alice"),
        "bob-token": TokenPayload(username="bob", role="user", user_id="u_bob"),
    }
    monkeypatch.setattr(auth_router, "decode_token", identities.get)


def test_outputs_require_authentication_and_are_scoped_to_the_owner(monkeypatch, tmp_path) -> None:
    _configure_authenticated_users(monkeypatch, tmp_path)
    relative_path = "workspace/chat/chat/turn-1/exec/report.txt"
    alice_output = tmp_path / "data" / "users" / "u_alice" / "user" / relative_path
    alice_output.parent.mkdir(parents=True)
    alice_output.write_text("alice private report")

    client = TestClient(api_main.app)

    unauthenticated = client.get(f"/api/outputs/{relative_path}")
    owner = client.get(
        f"/api/outputs/{relative_path}",
        headers={"Authorization": "Bearer alice-token"},
    )
    foreign_user = client.get(
        f"/api/outputs/{relative_path}",
        headers={"Authorization": "Bearer bob-token"},
    )

    assert unauthenticated.status_code == 401
    assert owner.status_code == 200
    assert owner.text == "alice private report"
    assert owner.headers["cache-control"] == "private, no-store"
    assert foreign_user.status_code == 404
    assert "alice private report" not in foreign_user.text


@pytest.mark.parametrize("suffix", [".html", ".svg", ".xml", ".xsl", ".xslt", ".js"])
def test_active_outputs_are_downloaded_with_browser_hardening(
    monkeypatch, tmp_path, suffix
) -> None:
    _configure_authenticated_users(monkeypatch, tmp_path)
    relative_path = f"workspace/chat/chat/turn-1/exec/report{suffix}"
    output = tmp_path / "data" / "users" / "u_alice" / "user" / relative_path
    output.parent.mkdir(parents=True)
    output.write_text("<script>window.pwned = true</script>")

    response = TestClient(api_main.app).get(
        f"/api/outputs/{relative_path}",
        headers={"Authorization": "Bearer alice-token"},
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == "attachment"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox; default-src 'none'"


def test_outputs_reject_a_path_outside_the_owner_workspace(monkeypatch, tmp_path) -> None:
    _configure_authenticated_users(monkeypatch, tmp_path)
    client = TestClient(api_main.app)

    response = client.get(
        "/api/outputs/%2e%2e/%2e%2e/system/auth/users.json",
        headers={"Authorization": "Bearer alice-token"},
    )

    assert response.status_code == 404
