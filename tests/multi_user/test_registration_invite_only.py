"""M5 regression — first user becomes admin atomically; concurrent races safe."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

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

    names = [f"bootstrap-{index}" for index in range(8)]
    pre_write_barrier = Barrier(len(names))

    def _empty_store_before_write() -> bool:
        # The pre-fix route performed this check before its separately locked
        # write. Hold every request here so that version deterministically
        # admits every caller; the fixed route no longer uses this probe.
        pre_write_barrier.wait(timeout=5)
        return True

    monkeypatch.setattr(auth_router, "is_first_user", _empty_store_before_write)

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
