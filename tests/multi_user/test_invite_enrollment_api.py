from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def enrollment_client(mu_isolated_root, monkeypatch):
    import deeptutor.api.routers.auth as auth_router
    from deeptutor.multi_user import enrollment
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services import auth as auth_service
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.config import runtime_settings

    settings = runtime_settings.RuntimeSettingsService(
        mu_isolated_root / "settings", process_env={}
    )
    settings.save_auth({"enabled": True, "cookie_secure": False})
    admin = save_user("admin", auth_service.hash_password("password1234"), role="admin")

    monkeypatch.setattr(runtime_settings, "get_runtime_settings_service", lambda: settings)
    monkeypatch.setattr(auth_router, "load_auth_settings", lambda: settings.load_auth())
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "_SECURE", False)
    monkeypatch.setattr(auth_router, "_SAMESITE", "lax")
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "invite-test-secret")
    monkeypatch.setattr(
        enrollment,
        "current_luna_target",
        lambda: enrollment.LunaTarget(
            profile_id="llm-openai-global",
            model_id="llm-gpt-5-6-luna",
        ),
    )
    monkeypatch.setattr(enrollment, "_THROTTLE", enrollment.InvalidCodeThrottle())
    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda token: (
            TokenPayload(username="admin", role="admin", user_id=admin["id"])
            if token == "admin-token"
            else auth_service.decode_token(token)
        ),
    )

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1/auth")
    return TestClient(app), settings


def _admin() -> dict[str, str]:
    return {"Authorization": "Bearer admin-token"}


def test_admin_rotation_is_cas_protected_and_plaintext_is_one_time(enrollment_client) -> None:
    client, _settings = enrollment_client
    before = client.get("/api/v1/auth/enrollment", headers=_admin())
    assert before.status_code == 200
    assert before.json()["state"] == "not_configured"
    assert "code" not in before.text and "hash" not in before.text

    rotated = client.post(
        "/api/v1/auth/enrollment/code",
        headers=_admin(),
        json={"expected_revision": before.json()["revision"]},
    )
    assert rotated.status_code == 200
    code = rotated.json()["code"]
    assert code.startswith("TEEECHR-")
    assert rotated.headers["cache-control"] == "no-store"
    assert rotated.headers["pragma"] == "no-cache"

    reread = client.get("/api/v1/auth/enrollment", headers=_admin())
    assert reread.json()["state"] == "active"
    assert code not in reread.text
    assert "invite_code_hash" not in reread.text

    stale = client.post(
        "/api/v1/auth/enrollment/code",
        headers=_admin(),
        json={"expected_revision": before.json()["revision"]},
    )
    assert stale.status_code == 409


def test_invited_signup_gets_session_and_exact_luna_grant(enrollment_client) -> None:
    client, _settings = enrollment_client
    revision = client.get("/api/v1/auth/enrollment", headers=_admin()).json()["revision"]
    code = client.post(
        "/api/v1/auth/enrollment/code",
        headers=_admin(),
        json={"expected_revision": revision},
    ).json()["code"]

    with TestClient(client.app) as learner:
        public = learner.get("/api/v1/auth/status")
        assert public.json() == {"authenticated": False, "registration_mode": "invite"}
        created = learner.post(
            "/api/v1/auth/register",
            json={
                "username": "student1",
                "password": "password1234",
                "invite_code": code,
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["role"] == "user"
        assert learner.cookies.get("dt_token")
        status = learner.get("/api/v1/auth/status")
        assert status.json()["authenticated"] is True
        assert status.json()["username"] == "student1"

    from deeptutor.multi_user.grants import load_grant

    user_id = created.json()["user_id"]
    assert load_grant(user_id)["models"]["llm"] == [
        {
            "profile_id": "llm-openai-global",
            "model_ids": ["llm-gpt-5-6-luna"],
        }
    ]


def test_rotation_invalidates_old_code_and_disable_closes_registration(
    enrollment_client,
) -> None:
    client, _settings = enrollment_client
    initial = client.get("/api/v1/auth/enrollment", headers=_admin()).json()
    first = client.post(
        "/api/v1/auth/enrollment/code",
        headers=_admin(),
        json={"expected_revision": initial["revision"]},
    ).json()
    second = client.post(
        "/api/v1/auth/enrollment/code",
        headers=_admin(),
        json={"expected_revision": first["enrollment"]["revision"]},
    ).json()
    old = client.post(
        "/api/v1/auth/register",
        json={"username": "oldcode", "password": "password1234", "invite_code": first["code"]},
    )
    assert old.status_code == 403

    disabled = client.put(
        "/api/v1/auth/enrollment/enabled",
        headers=_admin(),
        json={"enabled": False, "expected_revision": second["enrollment"]["revision"]},
    )
    assert disabled.status_code == 200
    assert disabled.json()["state"] == "disabled"
    assert client.get("/api/v1/auth/status").json()["registration_mode"] == "closed"


def test_fifth_invalid_code_is_throttled_with_retry_after(enrollment_client) -> None:
    client, _settings = enrollment_client
    revision = client.get("/api/v1/auth/enrollment", headers=_admin()).json()["revision"]
    client.post(
        "/api/v1/auth/enrollment/code",
        headers=_admin(),
        json={"expected_revision": revision},
    )
    responses = [
        client.post(
            "/api/v1/auth/register",
            json={
                "username": f"probe{index}",
                "password": "password1234",
                "invite_code": "TEEECHR-0000-0000-0000-0000",
            },
        )
        for index in range(5)
    ]
    assert [item.status_code for item in responses[:4]] == [403, 403, 403, 403]
    assert responses[4].status_code == 429
    assert int(responses[4].headers["retry-after"]) > 0


def test_invite_code_is_checked_before_identity_syntax(enrollment_client) -> None:
    client, _settings = enrollment_client
    revision = client.get("/api/v1/auth/enrollment", headers=_admin()).json()["revision"]
    code = client.post(
        "/api/v1/auth/enrollment/code",
        headers=_admin(),
        json={"expected_revision": revision},
    ).json()["code"]

    wrong_code = client.post(
        "/api/v1/auth/register",
        json={
            "username": "not a valid username",
            "password": "short",
            "invite_code": "TEEECHR-0000-0000-0000-0000",
        },
    )
    assert wrong_code.status_code == 403
    assert "username" not in wrong_code.text.lower()
    assert "password" not in wrong_code.text.lower()

    valid_code = client.post(
        "/api/v1/auth/register",
        json={
            "username": "not a valid username",
            "password": "short",
            "invite_code": code,
        },
    )
    assert valid_code.status_code == 422
    assert "username" in valid_code.text.lower()


def test_concurrent_rotations_have_one_winner(enrollment_client) -> None:
    _client, _settings = enrollment_client
    from deeptutor.multi_user.enrollment import EnrollmentConflict, enrollment_status, rotate_invite_code

    revision = enrollment_status()["revision"]

    def rotate() -> str:
        try:
            return rotate_invite_code(expected_revision=revision)[0]
        except EnrollmentConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: rotate(), range(2)))
    assert results.count("conflict") == 1
    assert len([item for item in results if item.startswith("TEEECHR-")]) == 1


def test_concurrent_same_username_publishes_exactly_one_identity(enrollment_client) -> None:
    client, _settings = enrollment_client
    from deeptutor.multi_user.enrollment import (
        EnrollmentConflict,
        invited_signup,
        rotate_invite_code,
    )
    from deeptutor.multi_user.identity import load_users

    status = client.get("/api/v1/auth/enrollment", headers=_admin()).json()
    code, _enrollment = rotate_invite_code(expected_revision=status["revision"])

    def signup(index: int) -> str:
        try:
            invited_signup(
                username="same_student",
                password="password1234",
                invite_code=code,
                source=f"198.51.100.{index}",
            )
            return "created"
        except EnrollmentConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(signup, range(2)))
    assert sorted(results) == ["conflict", "created"]
    assert list(load_users()).count("same_student") == 1


def test_untrusted_peer_cannot_spoof_throttle_source() -> None:
    from deeptutor.multi_user.enrollment import resolve_client_source

    assert (
        resolve_client_source(
            direct_peer="203.0.113.10",
            canonical_forwarded="198.51.100.1",
            trusted_proxy_cidrs=["172.18.0.0/16"],
        )
        == "203.0.113.10"
    )
    assert (
        resolve_client_source(
            direct_peer="172.18.0.3",
            canonical_forwarded="198.51.100.1",
            trusted_proxy_cidrs=["172.18.0.0/16"],
        )
        == "198.51.100.1"
    )
    assert (
        resolve_client_source(
            direct_peer="172.18.0.3",
            canonical_forwarded="198.51.100.1, 192.0.2.5",
            trusted_proxy_cidrs=["172.18.0.0/16"],
        )
        == "172.18.0.3"
    )


def test_bootstrap_latch_never_reopens_after_last_account_is_disabled(
    mu_isolated_root, monkeypatch
) -> None:
    from deeptutor.multi_user import enrollment
    from deeptutor.multi_user.identity import delete_user
    from deeptutor.services.auth import hash_password
    from deeptutor.services.config import runtime_settings

    settings = runtime_settings.RuntimeSettingsService(
        mu_isolated_root / "bootstrap-settings", process_env={}
    )
    settings.save_auth({"enabled": True})
    monkeypatch.setattr(runtime_settings, "get_runtime_settings_service", lambda: settings)
    assert enrollment.registration_mode() == "bootstrap"
    enrollment.complete_bootstrap(
        username="firstadmin", password_hash=hash_password("password1234")
    )
    assert delete_user("firstadmin") is True
    assert settings.load_auth(include_process_overrides=False)["bootstrap_completed_at"]
    assert enrollment.registration_mode() == "closed"


def test_existing_finalized_identity_permanently_latches_v1_migration(
    mu_isolated_root, monkeypatch
) -> None:
    import json

    from deeptutor.multi_user import enrollment
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.config import runtime_settings

    settings_dir = mu_isolated_root / "migrated-settings"
    settings_dir.mkdir()
    (settings_dir / "auth.json").write_text(
        json.dumps({"version": 1, "enabled": True}), encoding="utf-8"
    )
    settings = runtime_settings.RuntimeSettingsService(settings_dir, process_env={})
    save_user("existing_admin", "$2b$12$placeholder", role="admin")
    monkeypatch.setattr(runtime_settings, "get_runtime_settings_service", lambda: settings)

    assert enrollment.registration_mode() == "closed"
    migrated = settings.load_auth(include_process_overrides=False)
    assert migrated["version"] == 2
    assert migrated["bootstrap_completed_at"]


def test_startup_reconciliation_seals_bootstrap_before_public_status(
    mu_isolated_root, monkeypatch
) -> None:
    import json

    from deeptutor.multi_user import enrollment
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.config import runtime_settings

    settings_dir = mu_isolated_root / "startup-migration-settings"
    settings_dir.mkdir()
    (settings_dir / "auth.json").write_text(
        json.dumps({"version": 1, "enabled": True}), encoding="utf-8"
    )
    settings = runtime_settings.RuntimeSettingsService(settings_dir, process_env={})
    save_user("existing_admin", "$2b$12$placeholder", role="admin")
    monkeypatch.setattr(runtime_settings, "get_runtime_settings_service", lambda: settings)

    result = enrollment.reconcile_enrollment_journals()

    assert result.recovery_required is False
    assert settings.load_auth(include_process_overrides=False)["bootstrap_completed_at"]


def test_disable_racing_signup_never_leaves_half_provisioned_state(
    enrollment_client,
) -> None:
    client, _settings = enrollment_client
    from deeptutor.multi_user.enrollment import (
        EnrollmentUnavailable,
        invited_signup,
        rotate_invite_code,
        set_invite_enabled,
    )
    from deeptutor.multi_user.grants import grant_path
    from deeptutor.multi_user.identity import get_user

    initial = client.get("/api/v1/auth/enrollment", headers=_admin()).json()
    code, active = rotate_invite_code(expected_revision=initial["revision"])

    def signup() -> str:
        try:
            invited_signup(
                username="racing_student",
                password="password1234",
                invite_code=code,
                source="198.51.100.50",
            )
            return "created"
        except EnrollmentUnavailable:
            return "closed"

    def disable() -> str:
        set_invite_enabled(enabled=False, expected_revision=active["revision"])
        return "disabled"

    with ThreadPoolExecutor(max_workers=2) as pool:
        signup_future = pool.submit(signup)
        disable_future = pool.submit(disable)
        result = signup_future.result()
        assert disable_future.result() == "disabled"

    identity = get_user("racing_student")
    if result == "created":
        assert identity is not None
        assert grant_path(str(identity["id"])).exists()
    else:
        assert identity is None
