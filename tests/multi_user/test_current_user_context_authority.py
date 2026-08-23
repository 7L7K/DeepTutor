"""Auth-enabled authority must never fall back to the deployment owner."""

from __future__ import annotations

import pytest

from deeptutor.capabilities.obsidian import binding as obsidian_binding
from deeptutor.capabilities.subagent import binding as subagent_binding
from deeptutor.core.context import UnifiedContext
from deeptutor.multi_user import context as user_context
from deeptutor.multi_user import knowledge_access
from deeptutor.multi_user import partner_access
from deeptutor.multi_user.models import LOCAL_ADMIN_ID
from deeptutor.services import auth as auth_service


def _clear_current_user():
    """Install an explicit empty value and return its reset token."""
    return user_context._current_user.set(None)


def test_auth_disabled_missing_context_uses_local_admin(monkeypatch) -> None:
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", False)
    token = _clear_current_user()
    try:
        current = user_context.get_current_user()
        assert current.id == LOCAL_ADMIN_ID
        assert current.is_admin is True
        assert user_context.get_current_user_or_none() is None
    finally:
        user_context.reset_current_user(token)


def test_auth_enabled_missing_context_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    token = _clear_current_user()
    try:
        with pytest.raises(
            user_context.MissingCurrentUserContext,
            match="Authenticated user context is unavailable",
        ):
            user_context.get_current_user()
        assert user_context.get_current_user_or_none() is None
    finally:
        user_context.reset_current_user(token)


@pytest.mark.parametrize("role", ["admin", "user"])
def test_auth_enabled_explicit_principal_is_preserved(
    as_user,
    monkeypatch,
    role: str,
) -> None:
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    with as_user(f"u_{role}", role=role):
        current = user_context.get_current_user()
        assert current.id == f"u_{role}"
        assert current.role == role


def test_auth_enabled_missing_context_denies_connected_kb_before_resolution(
    monkeypatch,
) -> None:
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    token = _clear_current_user()
    try:
        with pytest.raises(user_context.MissingCurrentUserContext):
            knowledge_access.resolve_kb("personal:kb:LegacyVault")
    finally:
        user_context.reset_current_user(token)


def test_auth_enabled_missing_context_denies_partner_visibility_before_manager(
    monkeypatch,
) -> None:
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)

    def manager_must_not_be_resolved():
        raise AssertionError("missing authority must fail before Partner manager lookup")

    monkeypatch.setattr(
        "deeptutor.services.partners.get_partner_manager",
        manager_must_not_be_resolved,
    )
    token = _clear_current_user()
    try:
        with pytest.raises(user_context.MissingCurrentUserContext):
            partner_access.visible_partner_cards()
    finally:
        user_context.reset_current_user(token)


def test_auth_enabled_missing_context_keeps_discovery_bindings_inert(monkeypatch) -> None:
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)

    def metadata_must_not_be_resolved(_ref: str):
        raise AssertionError("missing authority must fail before metadata resolution")

    monkeypatch.setattr(
        knowledge_access,
        "resolve_kb_metadata",
        metadata_must_not_be_resolved,
    )
    token = _clear_current_user()
    try:
        subagent_turn = UnifiedContext(user_message="hi", knowledge_bases=["AdminClaude"])
        obsidian_turn = UnifiedContext(user_message="hi", knowledge_bases=["AdminVault"])

        assert subagent_binding.connection_for_turn(subagent_turn) is None
        assert subagent_binding.subagent_refs(subagent_turn) == set()
        assert obsidian_binding.vault_for_turn(obsidian_turn) is None
        assert obsidian_binding.obsidian_vault_refs(obsidian_turn) == set()
    finally:
        user_context.reset_current_user(token)


def test_cached_admin_obsidian_binding_cannot_cross_authority_boundaries(
    as_user,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        knowledge_access,
        "resolve_kb_metadata",
        lambda ref: {"name": ref, "type": "obsidian", "vault_path": "/admin/vault"},
    )
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["AdminVault"])

    with as_user("u_admin", role="admin"):
        assert obsidian_binding.vault_for_turn(ctx) == {
            "name": "AdminVault",
            "path": "/admin/vault",
        }

    with as_user("u_learner", role="user"):
        assert obsidian_binding.vault_for_turn(ctx) is None

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    token = _clear_current_user()
    try:
        assert obsidian_binding.vault_for_turn(ctx) is None
        assert obsidian_binding.obsidian_vault_refs(ctx) == set()
    finally:
        user_context.reset_current_user(token)
