"""M5 regression — first user becomes admin atomically; concurrent races safe."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, get_ident

from fastapi import HTTPException


def test_first_save_user_promotes_to_admin(mu_isolated_root):
    from deeptutor.multi_user.identity import list_user_info, save_user

    save_user("alice", "$2b$12$placeholder", role="user")
    users = {u["username"]: u for u in list_user_info()}
    assert users["alice"]["role"] == "admin"


def test_second_save_user_keeps_user_role(mu_isolated_root):
    from deeptutor.multi_user.identity import list_user_info, save_user

    save_user("alice", "$2b$12$placeholder", role="user")
    save_user("bob", "$2b$12$placeholder", role="user")
    users = {u["username"]: u for u in list_user_info()}
    assert users["alice"]["role"] == "admin"
    assert users["bob"]["role"] == "user"


def test_concurrent_first_save_only_one_admin(mu_isolated_root):
    """``_USERS_WRITE_LOCK`` must serialise read-modify-write so only one
    concurrent first-time registration can flip the empty-store branch."""
    from deeptutor.multi_user.identity import list_user_info, save_user

    def _save(name):
        try:
            save_user(name, "$2b$12$placeholder", role="user")
            return True
        except Exception:
            return False

    names = [f"u{i}" for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_save, names))

    users = list_user_info()
    admins = [u for u in users if u["role"] == "admin"]
    assert len(admins) == 1
    assert len(users) == 8


def test_concurrent_bootstrap_registration_accepts_only_one_request(mu_isolated_root, monkeypatch):
    """The public endpoint must not split its empty-store check from its write."""
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user.identity import list_user_info

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "AUTH_USERNAME", "")
    monkeypatch.setattr(auth_router, "AUTH_PASSWORD_HASH", "")

    names = [f"bootstrap-{index}" for index in range(8)]
    hash_calls = 0
    hash_calls_lock = Lock()

    def _hash_once(password: str) -> str:
        nonlocal hash_calls
        assert password == "password1234"
        with hash_calls_lock:
            hash_calls += 1
        return "$2b$12$placeholder"

    monkeypatch.setattr(auth_router, "hash_password", _hash_once)

    def _register(name: str):
        request = auth_router.RegisterRequest(username=name, password="password1234")
        try:
            return asyncio.run(auth_router.register(request))
        except HTTPException as exc:
            return exc

    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        results = list(pool.map(_register, names))

    accepted = [result for result in results if isinstance(result, dict)]
    rejected = [result for result in results if isinstance(result, HTTPException)]

    assert len(accepted) == 1
    assert accepted[0]["role"] == "admin"
    assert accepted[0]["is_admin"] is True
    assert [user["username"] for user in list_user_info()] == [accepted[0]["username"]]
    assert len(rejected) == len(names) - 1
    assert all(exc.status_code == 403 for exc in rejected)
    assert all(
        exc.detail == "Self-registration is closed. Ask an administrator to create your account."
        for exc in rejected
    )
    assert hash_calls == 1


def test_closed_registration_rejects_before_hashing(mu_isolated_root, monkeypatch):
    """A closed public route must not spend bcrypt work on rejected requests."""
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user.identity import save_user

    save_user("existing-admin", "$2b$12$placeholder", role="admin")
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "AUTH_USERNAME", "")
    monkeypatch.setattr(auth_router, "AUTH_PASSWORD_HASH", "")

    def _unexpected_hash(_password: str) -> str:
        raise AssertionError("closed registration must reject before hashing")

    monkeypatch.setattr(auth_router, "hash_password", _unexpected_hash)
    request = auth_router.RegisterRequest(username="attacker", password="password1234")

    try:
        asyncio.run(auth_router.register(request))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("closed registration unexpectedly accepted a request")


def test_settings_bootstrap_admin_keeps_direct_registration_closed(mu_isolated_root, monkeypatch):
    """The settings-backed admin is identity authority even without users.json."""
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user import identity

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "AUTH_USERNAME", "configured-admin")
    monkeypatch.setattr(auth_router, "AUTH_PASSWORD_HASH", "$2b$12$configured")

    def _unexpected_hash(_password: str) -> str:
        raise AssertionError("configured admin must close bootstrap before hashing")

    monkeypatch.setattr(auth_router, "hash_password", _unexpected_hash)
    request = auth_router.RegisterRequest(username="attacker", password="password1234")

    try:
        asyncio.run(auth_router.register(request))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("settings-backed admin was displaced")

    assert not identity.USERS_FILE.exists()


def test_bootstrap_hash_runs_off_event_loop_thread(mu_isolated_root, monkeypatch):
    """The only admitted bcrypt operation must not block the FastAPI event loop."""
    from deeptutor.api.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "AUTH_USERNAME", "")
    monkeypatch.setattr(auth_router, "AUTH_PASSWORD_HASH", "")
    event_loop_thread = get_ident()

    def _off_loop_hash(_password: str) -> str:
        assert get_ident() != event_loop_thread
        return "$2b$12$placeholder"

    monkeypatch.setattr(auth_router, "hash_password", _off_loop_hash)
    request = auth_router.RegisterRequest(username="first-admin", password="password1234")

    result = asyncio.run(auth_router.register(request))

    assert result["username"] == "first-admin"
    assert result["is_admin"] is True
