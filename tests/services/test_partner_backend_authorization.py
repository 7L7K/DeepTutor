"""Partner backend authorization stays live after a connection is created."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.multi_user import partner_access
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.subagent.partner import PartnerBackend


@pytest.mark.asyncio
async def test_partner_backend_refuses_revoked_assignment_before_manager_lookup(
    monkeypatch,
) -> None:
    """Defence in depth for callers that bypass the HTTP/router binding paths."""
    from fastapi import HTTPException

    def deny(partner_id: str) -> None:
        assert partner_id == "paul"
        raise HTTPException(status_code=403, detail="Partner is not assigned to you")

    monkeypatch.setattr(partner_access, "assert_partner_allowed", deny)

    def manager_must_not_be_resolved():
        raise AssertionError("revoked assignment must fail before Partner manager lookup")

    monkeypatch.setattr(
        "deeptutor.services.partners.get_partner_manager",
        manager_must_not_be_resolved,
    )

    async def on_event(_event) -> None:
        raise AssertionError("a revoked partner must not emit an event")

    result = await PartnerBackend().consult("hello", on_event=on_event, partner_id="paul")

    assert result.success is False
    assert result.error == "Partner is not assigned to you"


@pytest.mark.asyncio
async def test_partner_backend_refuses_missing_auth_context_before_manager_lookup(
    monkeypatch,
) -> None:
    from deeptutor.multi_user import context as user_context
    from deeptutor.services import auth as auth_service

    def manager_must_not_be_resolved():
        raise AssertionError("missing authority must fail before Partner manager lookup")

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        "deeptutor.services.partners.get_partner_manager",
        manager_must_not_be_resolved,
    )
    token = user_context._current_user.set(None)
    try:
        result = await PartnerBackend().consult(
            "hello",
            on_event=lambda _event: None,
            partner_id="paul",
        )
    finally:
        user_context.reset_current_user(token)

    assert result.success is False
    assert result.error == "Authenticated user context is unavailable"


@pytest.mark.asyncio
async def test_partner_backend_rejects_owner_bound_default_before_start_or_session(
    tmp_path, monkeypatch
) -> None:
    """A learner may use a deployment model, never the operator's OAuth identity."""
    from deeptutor.multi_user import model_access

    config = SimpleNamespace(llm_selection=None, backup_llm_selection=None)

    class UnsafeManager:
        def partner_exists(self, _partner_id):
            return True

        def get_partner(self, _partner_id):
            return SimpleNamespace(running=False, config=config)

        async def start_partner(self, _partner_id):
            raise AssertionError("unsafe Partner must be denied before startup")

        async def send_message(self, *_args, **_kwargs):
            raise AssertionError("unsafe Partner must be denied before session creation")

    catalog = {
        "services": {
            "llm": {
                "active_profile_id": "p-owner",
                "profiles": [{"id": "p-owner", "owner_bound": True, "models": []}],
            }
        }
    }
    monkeypatch.setattr(partner_access, "assert_partner_allowed", lambda _partner_id: None)
    monkeypatch.setattr(model_access, "admin_catalog", lambda: catalog)
    monkeypatch.setattr("deeptutor.services.partners.get_partner_manager", lambda: UnsafeManager())
    learner = CurrentUser(
        id="u_learner",
        username="learner",
        role="user",
        scope=UserScope(kind="user", user_id="u_learner", root=tmp_path / "learner"),
    )
    token = set_current_user(learner)
    try:
        result = await PartnerBackend().consult(
            "hello",
            on_event=lambda _event: None,
            partner_id="paul",
        )
    finally:
        reset_current_user(token)

    assert result.success is False
    assert result.session_id is None
    assert result.error == "Assigned Partner cannot use an owner-bound model profile."


@pytest.mark.asyncio
async def test_admin_partner_consult_preserves_owner_bound_owner_behavior(
    tmp_path, monkeypatch
) -> None:
    """The non-lending rule narrows assignment; it does not block the owner."""
    from deeptutor.multi_user import model_access

    config = SimpleNamespace(llm_selection=None, backup_llm_selection=None)

    class OwnerManager:
        def partner_exists(self, _partner_id):
            return True

        def get_partner(self, _partner_id):
            return SimpleNamespace(running=True, config=config)

        async def send_message(self, *_args, **kwargs):
            assert "delegated_user_id" not in kwargs
            return "owner reply"

    def shareability_must_not_run_for_owner(_config):
        raise AssertionError("admin owner must not pass through delegated model policy")

    monkeypatch.setattr(
        model_access,
        "assert_delegated_partner_models_shareable",
        shareability_must_not_run_for_owner,
    )
    monkeypatch.setattr("deeptutor.services.partners.get_partner_manager", lambda: OwnerManager())
    admin = CurrentUser(
        id="u_admin",
        username="admin",
        role="admin",
        scope=UserScope(kind="admin", user_id="u_admin", root=tmp_path / "admin"),
    )
    token = set_current_user(admin)
    try:
        result = await PartnerBackend().consult(
            "hello",
            on_event=lambda _event: None,
            partner_id="paul",
        )
    finally:
        reset_current_user(token)

    assert result.success is True
    assert result.final_text == "owner reply"


@pytest.mark.asyncio
async def test_learner_partner_consult_redacts_provider_exception(tmp_path, monkeypatch) -> None:
    """Learners may retry a failed delegated call but never receive provider diagnostics."""

    class FailingManager:
        def partner_exists(self, _partner_id):
            return True

        def get_partner(self, _partner_id):
            return SimpleNamespace(running=True, config=SimpleNamespace())

        async def send_message(self, *_args, **_kwargs):
            raise RuntimeError("provider token rejected: secret-detail")

    monkeypatch.setattr(partner_access, "assert_partner_allowed", lambda _partner_id: None)
    from deeptutor.multi_user import model_access

    monkeypatch.setattr(
        model_access,
        "assert_delegated_partner_models_shareable",
        lambda _config: None,
    )
    monkeypatch.setattr("deeptutor.services.partners.get_partner_manager", lambda: FailingManager())
    learner = CurrentUser(
        id="u_learner",
        username="learner",
        role="user",
        scope=UserScope(kind="user", user_id="u_learner", root=tmp_path / "learner"),
    )
    token = set_current_user(learner)
    try:
        result = await PartnerBackend().consult(
            "hello", on_event=lambda _event: None, partner_id="paul"
        )
    finally:
        reset_current_user(token)

    assert result.success is False
    assert "secret-detail" not in result.error
    assert result.error == "The assigned Partner could not complete that request. Please try again later."
