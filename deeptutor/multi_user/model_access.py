"""Server-side model grant resolution and redacted model views.

Grants carry LLM assignments only (grant v2): embedding and search always
resolve from the deployment's active profiles, so per-user grants for them
were never enforced and are not stored.
"""

from __future__ import annotations

from typing import Any

from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.model_selection import list_llm_options
from deeptutor.services.provider_registry import find_by_name

from .context import get_current_user
from .grants import load_grant
from .paths import get_admin_path_service


def admin_catalog_service() -> ModelCatalogService:
    return ModelCatalogService(path=get_admin_path_service().get_settings_file("model_catalog"))


def admin_catalog() -> dict[str, Any]:
    return admin_catalog_service().load()


def _profile_by_id(catalog: dict[str, Any], service: str, profile_id: str) -> dict[str, Any] | None:
    for profile in catalog.get("services", {}).get(service, {}).get("profiles", []) or []:
        if str(profile.get("id") or "") == profile_id:
            return profile
    return None


def _model_by_id(profile: dict[str, Any], model_id: str) -> dict[str, Any] | None:
    for model in profile.get("models", []) or []:
        if str(model.get("id") or "") == model_id:
            return model
    return None


def is_owner_bound(profile: dict[str, Any]) -> bool:
    """Whether a profile is tied to the identity of the operator who set it up.

    OAuth providers such as Codex authenticate one individual's plan rather than
    a billable team key, so those profiles are never lent to other accounts
    through grants — each user signs in for themselves or goes without.
    """
    # ``owner_bound`` is durable metadata for profiles whose provider does not
    # express this property. It cannot make a registry-classified OAuth profile
    # shareable: a persisted catalog is operator-controlled state, while the
    # provider registry is the canonical credential-mode classification.
    if bool(profile.get("owner_bound")):
        return True

    spec = find_by_name(str(profile.get("binding") or ""))
    # A delegated Partner must not become a way to exercise a credential whose
    # mode we cannot classify. Normalized catalog profiles always have a known
    # binding; this fail-closed branch protects malformed/legacy records before
    # they are lent to a learner.
    return spec is None or spec.is_oauth


def _effective_profile_for_selection(
    catalog: dict[str, Any], selection: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Resolve the catalog profile a Partner selection would activate.

    ``None`` is the Partner's implicit system-default selection.  Match the
    model catalog service's fallback exactly: use ``active_profile_id`` when it
    resolves, otherwise the first configured profile.
    """
    service = catalog.get("services", {}).get("llm", {})
    profiles = service.get("profiles", []) or []
    profile_id = str((selection or {}).get("profile_id") or "").strip()
    if not profile_id:
        profile_id = str(service.get("active_profile_id") or "").strip()
    if profile_id:
        for profile in profiles:
            if str(profile.get("id") or "") == profile_id:
                return profile
    return profiles[0] if not selection and profiles else None


def assert_delegated_partner_models_shareable(partner_config: Any) -> None:
    """Reject owner-bound model profiles before a learner drives a Partner.

    A Partner uses deployment model configuration rather than the learner's
    personal LLM grant.  That delegation may use deployment-owned API-key or
    local profiles, but it must never lend the operator's owner-bound OAuth
    identity.  Check every model the turn can reach up front: the primary
    selection (including the implicit system default) and the optional backup.
    """
    catalog = admin_catalog()
    primary = getattr(partner_config, "llm_selection", None) if partner_config else None
    backup = getattr(partner_config, "backup_llm_selection", None) if partner_config else None
    candidates: tuple[dict[str, Any] | None, ...] = (
        primary or None,
        *((backup,) if backup else ()),
    )
    for selection in candidates:
        profile = _effective_profile_for_selection(catalog, selection)
        if profile is None:
            raise PermissionError(
                "Assigned Partner model profile is not approved for delegated use."
            )
        if is_owner_bound(profile):
            raise PermissionError("Assigned Partner cannot use an owner-bound model profile.")


def redacted_model_access(user_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    user = get_current_user()
    if user_id is None:
        user_id = user.id
    grant = load_grant(user_id)
    catalog = admin_catalog()
    result: dict[str, list[dict[str, Any]]] = {"llm": []}
    for item in grant.get("models", {}).get("llm", []) or []:
        profile_id = str(item.get("profile_id") or item.get("id") or "")
        profile = _profile_by_id(catalog, "llm", profile_id)
        if profile is not None and is_owner_bound(profile):
            # A grant may predate the profile becoming owner-bound. Drop it here,
            # the one place every caller resolves grants through, so the option
            # list, the capability gate, and selection validation all agree.
            continue
        if not profile:
            result["llm"].append(
                {
                    "profile_id": profile_id,
                    "name": item.get("name") or profile_id or "Unavailable profile",
                    "source": "admin",
                    "available": False,
                }
            )
            continue
        for model_id in item.get("model_ids") or []:
            model = _model_by_id(profile, str(model_id))
            result["llm"].append(
                {
                    "profile_id": profile_id,
                    "model_id": str(model_id),
                    "name": (model or {}).get("name") or str(model_id),
                    "model": (model or {}).get("model") or "",
                    "source": "admin",
                    "available": model is not None,
                }
            )
    return result


def allowed_llm_options() -> dict[str, Any]:
    user = get_current_user()
    if user.is_admin:
        return list_llm_options(admin_catalog())
    options = [
        {
            "profile_id": item.get("profile_id"),
            "model_id": item.get("model_id"),
            "profile_name": item.get("name") or item.get("profile_id") or "LLM",
            "model_name": item.get("name") or item.get("model") or item.get("model_id"),
            "label": item.get("name") or item.get("model") or item.get("model_id"),
            "model": item.get("model") or "",
            "provider": "",
            "source": "admin",
            "is_active_default": False,
        }
        for item in redacted_model_access(user.id).get("llm", [])
        if item.get("available")
    ]
    return {"active": None, "options": options}


def has_capability_access(capability: str, user_id: str | None = None) -> bool:
    """Whether the user has at least one usable model for ``capability``.

    Admins are never gated — they manage the catalog directly. For ordinary
    users this mirrors exactly what ``redacted_model_access`` exposes to the
    frontend, so the server-side gate and the UI lock always agree.
    """
    user = get_current_user()
    if user.is_admin:
        return True
    if user_id is None:
        user_id = user.id
    items = redacted_model_access(user_id).get(capability, []) or []
    return any(item.get("available") for item in items)


def apply_allowed_llm_selection(selection: dict[str, Any] | None) -> dict[str, Any] | None:
    """Allow only admin-granted LLM profile/model selections for ordinary users."""
    user = get_current_user()
    if user.is_admin or not selection:
        return selection
    profile_id = str(selection.get("profile_id") or "")
    model_id = str(selection.get("model_id") or "")
    for item in redacted_model_access(user.id).get("llm", []):
        if item.get("profile_id") == profile_id and item.get("model_id") == model_id:
            return selection
    raise PermissionError("This model is not assigned to your account.")
