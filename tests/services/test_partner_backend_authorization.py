"""Partner backend authorization stays live after a connection is created."""

from __future__ import annotations

import pytest

from deeptutor.multi_user import partner_access
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
