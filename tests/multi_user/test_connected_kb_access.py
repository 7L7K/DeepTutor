"""Authorization contract for host/external pointer knowledge bases."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.multi_user import knowledge_access


class _FakeKBManager:
    def __init__(self, metadata: dict[str, dict]) -> None:
        self.metadata = metadata

    def list_knowledge_bases(self) -> list[str]:
        return list(self.metadata)

    def get_metadata(self, name: str | None = None) -> dict:
        return dict(self.metadata.get(str(name or ""), {}))

    def get_default(self) -> str | None:
        return next(iter(self.metadata), None)


def _install_managers(
    monkeypatch,
    tmp_path: Path,
    *,
    personal: dict[str, dict] | None = None,
    admin: dict[str, dict] | None = None,
) -> None:
    personal_manager = _FakeKBManager(personal or {})
    admin_manager = _FakeKBManager(admin or {})
    personal_root = (tmp_path / "personal-kbs").resolve()
    admin_root = (tmp_path / "admin-kbs").resolve()

    monkeypatch.setattr(knowledge_access, "current_kb_base_dir", lambda: personal_root)
    monkeypatch.setattr(knowledge_access, "admin_kb_base_dir", lambda: admin_root)
    monkeypatch.setattr(knowledge_access, "current_kb_manager", lambda: personal_manager)
    monkeypatch.setattr(knowledge_access, "admin_kb_manager", lambda: admin_manager)
    monkeypatch.setattr(
        knowledge_access,
        "manager_for_resource",
        lambda resource: personal_manager if resource.source == "user" else admin_manager,
    )
    monkeypatch.setattr(
        knowledge_access,
        "_manager_for",
        lambda base_dir: personal_manager
        if Path(base_dir).resolve() == personal_root
        else admin_manager,
    )


def _install_grant(monkeypatch, grant: dict) -> None:
    from deeptutor.multi_user import partner_access

    monkeypatch.setattr(knowledge_access, "load_grant", lambda _uid: grant)
    monkeypatch.setattr(partner_access, "load_grant", lambda _uid: grant)


@pytest.mark.parametrize(
    ("name", "metadata"),
    [
        ("OldVault", {"type": "obsidian", "vault_path": "/host/vault"}),
        ("OldIndex", {"type": "linked", "external_path": "/host/index"}),
    ],
)
def test_learner_cannot_activate_stale_personal_pointer(
    as_user,
    monkeypatch,
    tmp_path: Path,
    name: str,
    metadata: dict,
) -> None:
    _install_managers(monkeypatch, tmp_path, personal={name: metadata})
    _install_grant(monkeypatch, {"knowledge_bases": [], "partners": []})

    with as_user("u_learner", role="user"):
        with pytest.raises(HTTPException) as exc:
            knowledge_access.resolve_kb(f"personal:kb:{name}")
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException):
            knowledge_access.resolve_for_rag(f"personal:kb:{name}")
        assert knowledge_access.resolve_kb_metadata(f"personal:kb:{name}") is None
        assert knowledge_access.resolve_kb_manifest(f"personal:kb:{name}") is None


@pytest.mark.parametrize(
    ("name", "metadata"),
    [
        ("AdminVault", {"type": "obsidian", "vault_path": "/admin/vault"}),
        ("AdminIndex", {"type": "linked", "external_path": "/admin/index"}),
        ("RemoteRag", {"type": "lightrag_server", "server_url": "http://rag"}),
        ("RemoteIma", {"type": "ima", "knowledge_base_id": "ima-kb"}),
        ("AdminClaude", {"type": "subagent", "agent_kind": "claude_code"}),
    ],
)
def test_ordinary_kb_grant_cannot_assign_admin_pointer(
    as_user,
    monkeypatch,
    tmp_path: Path,
    name: str,
    metadata: dict,
) -> None:
    _install_managers(monkeypatch, tmp_path, admin={name: metadata})
    _install_grant(
        monkeypatch,
        {"knowledge_bases": [{"resource_id": f"admin:kb:{name}"}], "partners": []},
    )

    with as_user("u_learner", role="user"):
        with pytest.raises(HTTPException) as exc:
            knowledge_access.resolve_kb(f"admin:kb:{name}")
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException):
            knowledge_access.resolve_for_rag(f"admin:kb:{name}")
        assert knowledge_access.resolve_kb_metadata(f"admin:kb:{name}") is None
        assert knowledge_access.resolve_kb_manifest(f"admin:kb:{name}") is None


def test_ordinary_personal_and_assigned_admin_kbs_remain_available(
    as_user,
    monkeypatch,
    tmp_path: Path,
) -> None:
    _install_managers(
        monkeypatch,
        tmp_path,
        personal={"MyNotes": {"description": "ordinary"}},
        admin={"CourseNotes": {"description": "ordinary"}},
    )
    _install_grant(
        monkeypatch,
        {
            "knowledge_bases": [{"resource_id": "admin:kb:CourseNotes"}],
            "partners": [],
        },
    )

    with as_user("u_learner", role="user"):
        personal = knowledge_access.resolve_kb("personal:kb:MyNotes")
        assigned = knowledge_access.resolve_kb("admin:kb:CourseNotes")

    assert personal.source == "user" and personal.assigned is False
    assert assigned.source == "admin" and assigned.assigned is True
    assert assigned.read_only is True


def test_partner_connection_requires_personal_pointer_and_current_partner_grant(
    as_user,
    monkeypatch,
    tmp_path: Path,
) -> None:
    partner_meta = {
        "type": "subagent",
        "agent_kind": "partner",
        "partner_id": "paul",
    }
    _install_managers(
        monkeypatch,
        tmp_path,
        personal={"Paul": partner_meta},
        admin={"AdminPaul": partner_meta},
    )
    allowed_grant = {
        "knowledge_bases": [{"resource_id": "admin:kb:AdminPaul"}],
        "partners": [{"partner_id": "paul"}],
    }
    _install_grant(monkeypatch, allowed_grant)

    with as_user("u_learner", role="user"):
        personal = knowledge_access.resolve_kb_metadata("personal:kb:Paul")
        assert personal is not None and personal["partner_id"] == "paul"

        # A generic admin-KB grant never becomes a second Partner authority path.
        with pytest.raises(HTTPException):
            knowledge_access.resolve_kb("admin:kb:AdminPaul")

    _install_grant(
        monkeypatch,
        {
            "knowledge_bases": [{"resource_id": "admin:kb:AdminPaul"}],
            "partners": [],
        },
    )
    with as_user("u_learner", role="user"):
        with pytest.raises(HTTPException):
            knowledge_access.resolve_kb("personal:kb:Paul")


def test_visible_kb_inventory_filters_pointers_but_keeps_current_partner(
    as_user,
    monkeypatch,
    tmp_path: Path,
) -> None:
    _install_managers(
        monkeypatch,
        tmp_path,
        personal={
            "MyNotes": {"description": "ordinary"},
            "OldVault": {"type": "obsidian", "vault_path": "/host/vault"},
            "Paul": {
                "type": "subagent",
                "agent_kind": "partner",
                "partner_id": "paul",
            },
        },
        admin={
            "CourseNotes": {"description": "ordinary"},
            "AdminIndex": {"type": "linked", "external_path": "/admin/index"},
        },
    )
    grant = {
        "knowledge_bases": [
            {"resource_id": "admin:kb:CourseNotes"},
            {"resource_id": "admin:kb:AdminIndex"},
        ],
        "partners": [{"partner_id": "paul"}],
    }
    _install_grant(monkeypatch, grant)

    with as_user("u_learner", role="user"):
        visible = knowledge_access.list_visible_knowledge_bases()

    assert {item["id"] for item in visible} == {
        "user:kb:MyNotes",
        "user:kb:Paul",
        "admin:kb:CourseNotes",
    }

    _install_grant(
        monkeypatch,
        {
            "knowledge_bases": grant["knowledge_bases"],
            "partners": [],
        },
    )
    with as_user("u_learner", role="user"):
        visible_after_revocation = knowledge_access.list_visible_knowledge_bases()
    assert {item["id"] for item in visible_after_revocation} == {
        "user:kb:MyNotes",
        "admin:kb:CourseNotes",
    }


def test_admin_and_auth_disabled_local_admin_keep_connected_kb_access(
    as_user,
    monkeypatch,
    tmp_path: Path,
) -> None:
    metadata = {"AdminVault": {"type": "obsidian", "vault_path": "/admin/vault"}}
    _install_managers(monkeypatch, tmp_path, admin=metadata)

    with as_user("u_admin", role="admin"):
        assert knowledge_access.resolve_kb("AdminVault").name == "AdminVault"

    # With no request user set, get_current_user() is the local admin used by
    # auth-disabled/single-user deployments.
    assert knowledge_access.resolve_kb("AdminVault").name == "AdminVault"


def test_obsidian_binding_is_inert_for_learner_even_if_metadata_resolver_is_bypassed(
    as_user,
    monkeypatch,
    tmp_path: Path,
) -> None:
    from deeptutor.capabilities.obsidian import binding

    monkeypatch.setattr(
        knowledge_access,
        "resolve_kb_metadata",
        lambda ref: {"name": ref, "type": "obsidian", "vault_path": "/host/vault"},
    )

    with as_user("u_learner", role="user"):
        learner_turn = UnifiedContext(user_message="hi", knowledge_bases=["OldVault"])
        assert binding.vault_for_turn(learner_turn) is None
        assert binding.obsidian_vault_refs(learner_turn) == set()

    with as_user("u_admin", role="admin"):
        admin_turn = UnifiedContext(user_message="hi", knowledge_bases=["AdminVault"])
        assert binding.vault_for_turn(admin_turn) == {
            "name": "AdminVault",
            "path": "/host/vault",
        }
        assert binding.obsidian_vault_refs(admin_turn) == {"AdminVault"}

    # Even a mistakenly reused context cannot replay the cached admin path.
    with as_user("u_learner", role="user"):
        assert binding.vault_for_turn(admin_turn) is None
