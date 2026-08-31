"""Admission control for bounded notebook-originated LLM calls."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import Token
from typing import AsyncIterator
from urllib.parse import urlparse

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.model_selection.runtime import activate_llm_selection, reset_llm_selection
from deeptutor.services.sandbox.quota import QuotaExceeded, UserExecQuota

# Notebook summaries and learning-path generation are opt-in beta features
# backed by the same provider pool. Keep admission conservative for the
# single-container deployment; a multi-replica deployment needs shared state.
_NOTEBOOK_LLM_USER_QUOTA = UserExecQuota(max_concurrent=1, max_per_minute=6)
_NOTEBOOK_LLM_GLOBAL_QUOTA = UserExecQuota(max_concurrent=3, max_per_minute=24)
_NOTEBOOK_LLM_GLOBAL_KEY = "notebook-llm-global"


class NotebookLLMAdmissionError(PermissionError):
    """The current account has no usable, currently configured LLM grant."""


def _current_granted_llm_selection() -> tuple[str, dict[str, str] | None]:
    """Resolve a non-admin caller to one concrete grant-owned model."""
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.multi_user.model_access import has_capability_access, redacted_model_access

    user = get_current_user()
    if user.is_admin:
        return user.id, None
    if not has_capability_access("llm"):
        raise NotebookLLMAdmissionError("No LLM model is assigned to this account.")

    assignments = [
        item for item in redacted_model_access(user.id).get("llm", []) if item.get("available")
    ]
    if not assignments:
        raise NotebookLLMAdmissionError("No LLM model is assigned to this account.")
    selection = {
        "profile_id": str(assignments[0].get("profile_id") or ""),
        "model_id": str(assignments[0].get("model_id") or ""),
    }
    if not all(selection.values()):
        raise NotebookLLMAdmissionError("No LLM model is assigned to this account.")
    if not _selection_has_own_runtime_config(selection):
        raise NotebookLLMAdmissionError("No LLM model is assigned to this account.")
    return user.id, selection


def _selection_has_own_runtime_config(selection: dict[str, str]) -> bool:
    """Reject grants that would resolve through a different profile's secret."""
    from deeptutor.multi_user.model_access import admin_catalog

    catalog = admin_catalog()
    profiles = catalog.get("services", {}).get("llm", {}).get("profiles", []) or []
    profile = next(
        (
            item
            for item in profiles
            if str(item.get("id") or "") == selection["profile_id"]
        ),
        None,
    )
    if not isinstance(profile, dict):
        return False
    model = next(
        (
            item
            for item in profile.get("models", []) or []
            if str(item.get("id") or "") == selection["model_id"]
        ),
        None,
    )
    if not isinstance(model, dict) or not str(model.get("model") or "").strip():
        return False
    if str(profile.get("api_key") or "").strip():
        return True

    # A local endpoint has no provider credential, but it is still owned by
    # this exact profile. Never treat a remote endpoint with an empty key as
    # configured: runtime resolution would borrow another profile's key.
    base_url = str(profile.get("base_url") or "").strip()
    try:
        host = urlparse(base_url if "://" in base_url else f"http://{base_url}").hostname
    except ValueError:
        return False
    normalized_host = str(host or "").lower()
    return normalized_host in {"localhost", "127.0.0.1", "::1"} or normalized_host.endswith(
        ".local"
    )


@asynccontextmanager
async def admitted_notebook_llm_call() -> AsyncIterator[LLMConfig]:
    """Bind one beta LLM call to the caller's live grant and local quotas."""
    user_id, selection = _current_granted_llm_selection()
    llm_config: LLMConfig
    llm_scope_token: Token[LLMConfig | None] | None = None
    try:
        try:
            llm_config, llm_scope_token = activate_llm_selection(selection)
        except (KeyError, TypeError, ValueError) as exc:
            raise NotebookLLMAdmissionError(
                "No LLM model is assigned to this account."
            ) from exc
        async with AsyncExitStack() as quota_stack:
            user_quota_lease = await _NOTEBOOK_LLM_USER_QUOTA.acquire(user_id)
            await quota_stack.enter_async_context(user_quota_lease)
            global_quota_lease = await _NOTEBOOK_LLM_GLOBAL_QUOTA.acquire(
                _NOTEBOOK_LLM_GLOBAL_KEY
            )
            await quota_stack.enter_async_context(global_quota_lease)
            yield llm_config
    finally:
        if llm_scope_token is not None:
            reset_llm_selection(llm_scope_token)


__all__ = [
    "NotebookLLMAdmissionError",
    "QuotaExceeded",
    "admitted_notebook_llm_call",
]
