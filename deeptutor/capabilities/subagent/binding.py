"""Resolve which connected subagent (if any) the current turn targets.

Mirrors :mod:`deeptutor.capabilities.obsidian.binding`: the binding is derived
once per turn from the user's selected knowledge bases — the first selection
whose KB metadata is ``type == subagent`` wins, and its ``agent_kind`` plus its
target (``cwd`` for a local CLI, ``partner_id`` for a partner) become the live
connection the consult tool drives. Cached on ``context.metadata`` so
``is_active`` / ``augment_kwargs`` / ``system_block`` share one lookup. Pure
read; access errors resolve to "no connection".
"""

from __future__ import annotations

from deeptutor.core.context import UnifiedContext
from deeptutor.knowledge.kb_types import SUBAGENT_KB_TYPE
from deeptutor.services.subagent.partner import PARTNER_BACKEND_KIND

# Cached on context.metadata: a {"name", "kind", "cwd", "partner_id"} dict, or ""
# once we've looked and found none. Absence of the key means "not resolved yet".
_CACHE_KEY = "_subagent_connection"
_UNSET = object()


def _has_current_user_authority() -> bool:
    from deeptutor.multi_user.context import MissingCurrentUserContext, get_current_user

    try:
        get_current_user()
        return True
    except MissingCurrentUserContext:
        return False


def connection_for_turn(context: UnifiedContext) -> dict[str, str] | None:
    """Return ``{"name", "kind", "cwd", "partner_id"}`` of the selected subagent, or ``None``."""
    if not _has_current_user_authority():
        return None
    cached = context.metadata.get(_CACHE_KEY, _UNSET)
    if cached is not _UNSET:
        # The cached dict is a lookup optimization, never cached authority. A
        # UnifiedContext may accidentally cross principal or grant boundaries;
        # re-check admin/Partner authority before every return.
        return _authorize_connection(cached) if isinstance(cached, dict) else None
    resolved = _resolve(context)
    context.metadata[_CACHE_KEY] = resolved or ""
    return resolved


def _resolve(context: UnifiedContext) -> dict[str, str] | None:
    from deeptutor.multi_user.knowledge_access import resolve_kb_metadata

    for ref in context.knowledge_bases or []:
        ref = str(ref).strip()
        if not ref:
            continue
        meta = resolve_kb_metadata(ref)
        connection = _usable_connection(ref, meta)
        if connection is not None:
            return connection
    return None


def _usable_connection(ref: str, meta: object) -> dict[str, str] | None:
    """Return a selected connection only when it remains authorized now.

    Partner connection metadata is retained after grant edits so it can be
    cleaned up later. It is not authority to consult the Partner: every fresh
    chat turn rechecks the current user's assignment before activating the
    capability. Local CLI connections keep their existing admin-only API gate.
    """
    if not isinstance(meta, dict) or meta.get("type") != SUBAGENT_KB_TYPE:
        return None
    kind = str(meta.get("agent_kind") or "").strip()
    if not kind:
        return None
    partner_id = str(meta.get("partner_id") or "").strip()
    return _authorize_connection(
        {
            "name": str(meta.get("name") or ref),
            "kind": kind,
            "cwd": str(meta.get("cwd") or "").strip(),
            "partner_id": partner_id,
        }
    )


def _authorize_connection(connection: dict[str, str]) -> dict[str, str] | None:
    """Return ``connection`` only while the current principal may use it."""
    from deeptutor.multi_user.context import MissingCurrentUserContext, get_current_user

    kind = str(connection.get("kind") or "").strip()
    if not kind:
        return None
    try:
        user = get_current_user()
    except MissingCurrentUserContext:
        return None

    # Connected host CLIs are deployment authority. A learner can only activate
    # an assigned Partner, even if stale or cached metadata points at an
    # administrator's local subagent connection.
    if not user.is_admin and kind != PARTNER_BACKEND_KIND:
        return None
    if kind == PARTNER_BACKEND_KIND:
        from fastapi import HTTPException

        from deeptutor.multi_user.partner_access import assert_partner_allowed

        try:
            assert_partner_allowed(str(connection.get("partner_id") or "").strip())
        except (HTTPException, MissingCurrentUserContext):
            # A revoked grant makes this stale selection inert. The caller
            # proceeds as an ordinary chat turn rather than consulting it.
            return None
    return connection


def subagent_refs(context: UnifiedContext) -> set[str]:
    """Return every selected KB ref that resolves to a connected subagent.

    A subagent "KB" is a delegate consulted via ``consult_subagent``, not a rag
    index — exclude these refs from the rag surface so a co-selected real KB
    stays reachable (issue #650) and the agent ref never appears as a rag choice.
    """
    if not _has_current_user_authority():
        return set()

    from deeptutor.multi_user.knowledge_access import resolve_kb_metadata

    refs: set[str] = set()
    for ref in context.knowledge_bases or []:
        ref = str(ref).strip()
        if not ref:
            continue
        meta = resolve_kb_metadata(ref)
        if _usable_connection(ref, meta) is not None:
            refs.add(ref)
    return refs


__all__ = ["connection_for_turn", "subagent_refs"]
