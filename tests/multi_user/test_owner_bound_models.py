"""Owner-bound profiles are never lent to other accounts through grants.

Codex authenticates one person's ChatGPT plan rather than a billable team key,
so granting that profile to other users would run a whole deployment on a single
subscription. Administrators still use their own sign-in: they resolve models
straight from the catalog and never pass through the grant view tested here.
"""

from types import SimpleNamespace

import pytest

from deeptutor.multi_user import model_access
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope

CODEX_PROFILE = "llm-profile-openai-codex-managed"


def make_user(tmp_path):
    return CurrentUser(
        id="u_alice",
        username="alice",
        role="user",
        scope=UserScope(kind="user", user_id="u_alice", root=tmp_path / "u_alice"),
    )


def _catalog(*, owner_bound: bool) -> dict:
    profile: dict = {
        "id": CODEX_PROFILE,
        "name": "OpenAI Codex",
        "binding": "openai",
        "api_key": "shared-api-key",
        "models": [{"id": "m-sol", "name": "GPT-5.6-Sol", "model": "gpt-5.6-sol"}],
    }
    if owner_bound:
        profile["owner_bound"] = True
    return {"services": {"llm": {"profiles": [profile]}}}


def _grant(_user_id=None) -> dict:
    return {"models": {"llm": [{"profile_id": CODEX_PROFILE, "model_ids": ["m-sol"]}]}}


def test_owner_bound_profile_is_withheld_from_granted_users(tmp_path, monkeypatch):
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _catalog(owner_bound=True))
    monkeypatch.setattr(model_access, "load_grant", _grant)
    token = set_current_user(make_user(tmp_path))
    try:
        assert model_access.redacted_model_access()["llm"] == []
        assert model_access.allowed_llm_options()["options"] == []
        assert model_access.has_capability_access("llm") is False
        with pytest.raises(PermissionError):
            model_access.apply_allowed_llm_selection(
                {"profile_id": CODEX_PROFILE, "model_id": "m-sol"}
            )
    finally:
        reset_current_user(token)


def test_owner_bound_profile_is_not_offered_as_assignable(tmp_path, monkeypatch):
    """Admins must not be shown a grant the server would silently discard."""
    from deeptutor.multi_user import router as multi_user_router

    monkeypatch.setattr(
        multi_user_router,
        "ModelCatalogService",
        lambda path=None: SimpleNamespace(load=lambda: _catalog(owner_bound=True)),
    )
    monkeypatch.setattr(
        multi_user_router,
        "get_admin_path_service",
        lambda: SimpleNamespace(get_settings_file=lambda _name: tmp_path / "catalog.json"),
    )

    assert multi_user_router._admin_catalog_summary() == {"llm": []}


def test_ordinary_shared_profiles_stay_grantable(tmp_path, monkeypatch):
    """The filter has to stay narrow: an API-key profile is still shareable."""
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _catalog(owner_bound=False))
    monkeypatch.setattr(model_access, "load_grant", _grant)
    token = set_current_user(make_user(tmp_path))
    try:
        granted = model_access.redacted_model_access()["llm"]
        assert [item["model_id"] for item in granted] == ["m-sol"]
        assert model_access.has_capability_access("llm") is True
        assert model_access.apply_allowed_llm_selection(
            {"profile_id": CODEX_PROFILE, "model_id": "m-sol"}
        ) == {"profile_id": CODEX_PROFILE, "model_id": "m-sol"}
    finally:
        reset_current_user(token)


def test_granted_model_without_concrete_api_model_is_unavailable(tmp_path, monkeypatch):
    catalog = _catalog(owner_bound=False)
    catalog["services"]["llm"]["profiles"][0]["models"][0]["model"] = "  "
    monkeypatch.setattr(model_access, "admin_catalog", lambda: catalog)
    monkeypatch.setattr(model_access, "load_grant", _grant)
    token = set_current_user(make_user(tmp_path))
    selection = {"profile_id": CODEX_PROFILE, "model_id": "m-sol"}
    try:
        granted = model_access.redacted_model_access()["llm"]
        assert granted[0]["available"] is False
        assert model_access.allowed_llm_options()["options"] == []
        assert model_access.has_capability_access("llm") is False
        with pytest.raises(PermissionError):
            model_access.apply_allowed_llm_selection(selection)
    finally:
        reset_current_user(token)


def test_credential_empty_grant_cannot_borrow_same_binding_profile(tmp_path, monkeypatch):
    granted_profile = _catalog(owner_bound=False)["services"]["llm"]["profiles"][0]
    granted_profile["api_key"] = ""
    ungranted_profile = {
        "id": "p-ungranted",
        "name": "Ungrantable OpenAI",
        "binding": "openai",
        "api_key": "ungranted-key",
        "base_url": "https://ungranted.example/v1",
        "models": [{"id": "m-ungranted", "model": "gpt-ungranted"}],
    }
    catalog = {"services": {"llm": {"profiles": [granted_profile, ungranted_profile]}}}
    monkeypatch.setattr(model_access, "admin_catalog", lambda: catalog)
    monkeypatch.setattr(model_access, "load_grant", _grant)
    token = set_current_user(make_user(tmp_path))
    selection = {"profile_id": CODEX_PROFILE, "model_id": "m-sol"}
    try:
        granted = model_access.redacted_model_access()["llm"]
        assert granted[0]["available"] is False
        assert model_access.has_capability_access("llm") is False
        with pytest.raises(PermissionError):
            model_access.apply_allowed_llm_selection(selection)
    finally:
        reset_current_user(token)


@pytest.mark.parametrize(
    ("primary", "backup", "active_profile_id"),
    [
        ({"profile_id": CODEX_PROFILE, "model_id": "m-sol"}, None, "p-shared"),
        (
            {"profile_id": "p-shared", "model_id": "m-shared"},
            {"profile_id": CODEX_PROFILE, "model_id": "m-sol"},
            "p-shared",
        ),
        (None, None, CODEX_PROFILE),
    ],
    ids=("primary", "backup", "implicit-default"),
)
def test_delegated_partner_rejects_every_owner_bound_model_path(
    monkeypatch, primary, backup, active_profile_id
):
    catalog = {
        "services": {
            "llm": {
                "active_profile_id": active_profile_id,
                "profiles": [
                    {
                        "id": "p-shared",
                        "binding": "openai",
                        "models": [{"id": "m-shared", "model": "gpt-shared"}],
                    },
                    {
                        "id": CODEX_PROFILE,
                        "binding": "openai_codex",
                        "owner_bound": True,
                        "models": [{"id": "m-sol", "model": "gpt-5.6-sol"}],
                    },
                ],
            }
        }
    }
    monkeypatch.setattr(model_access, "admin_catalog", lambda: catalog)
    config = SimpleNamespace(
        llm_selection=primary,
        backup_llm_selection=backup,
    )

    with pytest.raises(PermissionError, match="owner-bound"):
        model_access.assert_delegated_partner_models_shareable(config)


def test_delegated_partner_allows_deployment_owned_primary_and_backup(monkeypatch):
    catalog = {
        "services": {
            "llm": {
                "active_profile_id": "p-primary",
                "profiles": [
                    {"id": "p-primary", "binding": "openai", "models": [{"id": "m-primary"}]},
                    {"id": "p-backup", "binding": "openai", "models": [{"id": "m-backup"}]},
                ],
            }
        }
    }
    monkeypatch.setattr(model_access, "admin_catalog", lambda: catalog)
    config = SimpleNamespace(
        llm_selection={"profile_id": "p-primary", "model_id": "m-primary"},
        backup_llm_selection={"profile_id": "p-backup", "model_id": "m-backup"},
    )

    model_access.assert_delegated_partner_models_shareable(config)


@pytest.mark.parametrize(
    ("primary", "backup", "active_profile_id"),
    [
        ({"profile_id": "p-oauth", "model_id": "m-oauth"}, None, "p-shared"),
        (
            {"profile_id": "p-shared", "model_id": "m-shared"},
            {"profile_id": "p-oauth", "model_id": "m-oauth"},
            "p-shared",
        ),
        (None, None, "p-oauth"),
    ],
    ids=("primary", "backup", "implicit-default"),
)
def test_delegated_partner_rejects_registry_oauth_without_mutable_flag(
    monkeypatch, primary, backup, active_profile_id
):
    catalog = {
        "services": {
            "llm": {
                "active_profile_id": active_profile_id,
                "profiles": [
                    {"id": "p-shared", "binding": "openai", "models": [{"id": "m-shared"}]},
                    {"id": "p-oauth", "binding": "openai-codex", "models": [{"id": "m-oauth"}]},
                ],
            }
        }
    }
    monkeypatch.setattr(model_access, "admin_catalog", lambda: catalog)
    config = SimpleNamespace(llm_selection=primary, backup_llm_selection=backup)

    with pytest.raises(PermissionError, match="owner-bound"):
        model_access.assert_delegated_partner_models_shareable(config)


def test_delegated_partner_rejects_unknown_profile_binding(monkeypatch):
    monkeypatch.setattr(
        model_access,
        "admin_catalog",
        lambda: {
            "services": {
                "llm": {
                    "active_profile_id": "p-unknown",
                    "profiles": [{"id": "p-unknown", "binding": "unreviewed-provider"}],
                }
            }
        },
    )
    config = SimpleNamespace(llm_selection=None, backup_llm_selection=None)

    with pytest.raises(PermissionError, match="owner-bound"):
        model_access.assert_delegated_partner_models_shareable(config)
