"""Partner visibility guards for non-admin users.

Partners are admin-managed, process-wide resources: the whole
``/api/v1/partners`` CRUD router is admin-gated, and a partner runs in its own
isolated workspace scope (``data/partners/{id}/``), never the caller's. A
non-admin can't create or manage partners, but an admin can *assign* specific
partners to specific users through the grant system — the same mechanism that
shares knowledge bases and skills.

An assigned user may then see the partner, connect it as a subagent, and
consult it in chat; the consult still drives the partner in its own scope, so
the user only ever exchanges messages with it — exactly as when an admin
consults it. This module is the read-side counterpart of ``skill_access``.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .context import get_current_user
from .grants import load_grant


def assigned_partner_ids(user_id: str | None = None) -> set[str]:
    """The partner ids an admin has assigned to the user (empty for admins)."""
    user = get_current_user()
    uid = user_id or user.id
    return {
        str(item.get("partner_id") or item.get("id") or "").strip()
        for item in load_grant(uid).get("partners", []) or []
        if str(item.get("partner_id") or item.get("id") or "").strip()
    }


def assert_partner_assigned_to_user(partner_id: str, user_id: str) -> None:
    """Revalidate an assignment for an explicit delegated principal.

    Runtime boundaries must not infer this principal from the ambient user:
    Partner execution later enters an owner-scoped synthetic user context.
    """
    pid = str(partner_id or "").strip()
    uid = str(user_id or "").strip()
    allowed = {
        str(item.get("partner_id") or item.get("id") or "").strip()
        for item in load_grant(uid).get("partners", []) or []
        if str(item.get("partner_id") or item.get("id") or "").strip()
    }
    if not uid or pid not in allowed:
        raise HTTPException(status_code=403, detail="Partner is not assigned to you")


def assert_partner_allowed(partner_id: str, user_id: str | None = None) -> None:
    """Raise 403 when a non-admin tries to use a partner not assigned to them.

    Admins may use any partner; this is a no-op for them (and for single-user
    deployments, where the current user resolves to the local admin).
    """
    user = get_current_user()
    if user.is_admin:
        return
    pid = str(partner_id or "").strip()
    if pid not in assigned_partner_ids(user_id or user.id):
        raise HTTPException(status_code=403, detail="Partner is not assigned to you")

    # This guard is called by the consult tool before it resolves a backend or
    # increments the turn budget.  Keep the Partner model's lending policy at
    # this shared authorization boundary so an assigned learner cannot spend
    # budget—or start any provider/session work—on an owner-bound OAuth model.
    from deeptutor.multi_user.model_access import assert_delegated_partner_models_shareable
    from deeptutor.services.partners import get_partner_manager

    manager = get_partner_manager()
    if not manager.partner_exists(pid):
        # Existence has its own 404/"no longer exists" contract at each caller.
        return
    instance = manager.get_partner(pid)
    partner_config = instance.config if instance is not None else manager.load_config(pid)
    try:
        assert_delegated_partner_models_shareable(partner_config)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None


# Identity-only card fields a consumer needs (partner list page, connect modal).
# Deliberately excludes channels / llm_selection / tool config so a non-admin
# only ever sees a partner's face, never its wiring.
_CARD_FIELDS = (
    "partner_id",
    "name",
    "description",
    "emoji",
    "color",
    "avatar",
    "language",
    "running",
)


def _project_card(partner: dict[str, Any]) -> dict[str, Any]:
    card = {field: partner.get(field) for field in _CARD_FIELDS}
    card["partner_id"] = str(partner.get("partner_id") or "")
    return card


def visible_partner_cards() -> list[dict[str, Any]]:
    """Partners the current user may consult: all for an admin, or just the
    assigned subset for a non-admin. Returns identity-only card dicts."""
    user = get_current_user()

    from deeptutor.services.partners import get_partner_manager

    everything = get_partner_manager().list_partners()
    if user.is_admin:
        return [_project_card(item) for item in everything]
    allowed = assigned_partner_ids(user.id)
    return [
        _project_card(item) for item in everything if str(item.get("partner_id") or "") in allowed
    ]
