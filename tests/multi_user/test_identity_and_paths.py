from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from deeptutor.multi_user import identity, paths
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.path_service import get_path_service


def test_identity_migrates_legacy_users_with_stable_uid(tmp_path, monkeypatch):
    legacy = tmp_path / "data" / "user" / "auth_users.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"alice":{"hash":"h1","role":"admin","created_at":"t"},"bob":"h2"}')
    users_file = tmp_path / "data" / "system" / "auth" / "users.json"

    monkeypatch.setattr(identity, "USERS_FILE", users_file)
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", legacy)

    users = identity.load_users()

    assert users["alice"]["id"].startswith("u_")
    assert users["alice"]["role"] == "admin"
    assert users["bob"]["role"] == "user"
    assert users_file.exists()
    assert stat.S_IMODE(users_file.stat().st_mode) == 0o600


def test_corrupt_existing_identity_store_fails_closed(tmp_path, monkeypatch) -> None:
    users_file = tmp_path / "data" / "system" / "auth" / "users.json"
    users_file.parent.mkdir(parents=True)
    users_file.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(identity, "USERS_FILE", users_file)
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "missing-users.json")

    with pytest.raises(RuntimeError, match="authentication is locked"):
        identity.load_users()
    assert users_file.read_text(encoding="utf-8") == "{broken"


def test_duplicate_immutable_user_ids_fail_closed(tmp_path, monkeypatch) -> None:
    users_file = tmp_path / "data" / "system" / "auth" / "users.json"
    users_file.parent.mkdir(parents=True)
    users_file.write_text(
        '{"alice":{"id":"u_same","hash":"h1","role":"admin"},'
        '"bob":{"id":"u_same","hash":"h2","role":"user"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(identity, "USERS_FILE", users_file)
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "missing-users.json")

    with pytest.raises(RuntimeError, match="duplicate immutable user id"):
        identity.load_users()


def test_path_service_uses_current_user_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ensure_user_workspace", lambda _uid: tmp_path)
    user_root = tmp_path / "data" / "users" / "u_alice"
    user = CurrentUser(
        id="u_alice",
        username="alice",
        role="user",
        scope=UserScope(kind="user", user_id="u_alice", root=user_root),
    )

    token = set_current_user(user)
    try:
        service = get_path_service()
        assert service.workspace_root == user_root.resolve()
        assert service.get_chat_history_db() == user_root.resolve() / "user" / "chat_history.db"
        assert service.get_knowledge_bases_root() == user_root.resolve() / "knowledge_bases"
    finally:
        reset_current_user(token)


def test_personal_path_service_keeps_admin_course_data_private(mu_isolated_root, make_user):
    from deeptutor.multi_user.paths import get_personal_path_service

    admin = make_user("u_admin", role="admin", username="alice")
    token = set_current_user(admin)
    try:
        service = get_personal_path_service()
    finally:
        reset_current_user(token)

    expected = (mu_isolated_root / "data" / "users" / "u_admin").resolve()
    assert service.workspace_root == expected
    assert service.workspace_root != paths.ADMIN_WORKSPACE_ROOT.resolve()
    assert stat.S_IMODE(service.workspace_root.stat().st_mode) == 0o700


def test_personal_path_service_fails_without_authenticated_context() -> None:
    from deeptutor.multi_user.paths import get_personal_path_service

    with pytest.raises(RuntimeError, match="Authenticated user context"):
        get_personal_path_service()


def test_admin_course_mastery_uses_private_personal_learning_root(
    mu_isolated_root, make_user
) -> None:
    from deeptutor.capabilities.mastery.tools import _new_service

    admin = make_user("u_admin", role="admin", username="alice")
    token = set_current_user(admin)
    try:
        service = _new_service("lp_crs_one")
    finally:
        reset_current_user(token)

    expected = (
        mu_isolated_root
        / "data"
        / "users"
        / "u_admin"
        / "user"
        / "workspace"
        / "learning"
    ).resolve()
    assert service._store._root.resolve() == expected


@pytest.mark.parametrize("user_id", ["..", "../outside", "nested/user", "/tmp/outside"])
def test_personal_scope_rejects_ids_outside_one_workspace(
    mu_isolated_root, user_id: str
) -> None:
    with pytest.raises(ValueError, match="workspace"):
        paths.personal_scope_for_user(user_id)


def test_personal_scope_rejects_symlink_escape(mu_isolated_root) -> None:
    users_root = mu_isolated_root / "data" / "users"
    users_root.mkdir(parents=True, exist_ok=True)
    outside = mu_isolated_root / "outside"
    outside.mkdir()
    (users_root / "u_escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises((ValueError, RuntimeError), match="symbolic link|symlink|outside"):
        paths.personal_scope_for_user("u_escape")


def test_personal_scope_rejects_cross_user_symlink_alias(mu_isolated_root) -> None:
    users_root = mu_isolated_root / "data" / "users"
    victim = users_root / "u_victim"
    victim.mkdir(parents=True)
    (users_root / "u_attacker").symlink_to(victim, target_is_directory=True)

    with pytest.raises((ValueError, RuntimeError), match="symbolic link|symlink"):
        paths.personal_scope_for_user("u_attacker")


def test_private_workspace_repairs_existing_modes_without_changing_bytes(
    mu_isolated_root,
) -> None:
    root = mu_isolated_root / "data" / "users" / "u_private"
    nested = root / "knowledge_bases" / "kb" / "raw"
    nested.mkdir(parents=True)
    source = nested / "notes.txt"
    source.write_bytes(b"private bytes")
    root.chmod(0o755)
    nested.chmod(0o755)
    source.chmod(0o644)

    paths.ensure_user_workspace("u_private")

    assert source.read_bytes() == b"private bytes"
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(nested.stat().st_mode) == 0o700
    assert stat.S_IMODE(source.stat().st_mode) == 0o600


def test_private_workspace_fails_closed_on_nested_symlink(mu_isolated_root) -> None:
    root = mu_isolated_root / "data" / "users" / "u_private"
    root.mkdir(parents=True)
    outside = mu_isolated_root / "outside"
    outside.mkdir()
    (root / "knowledge_bases").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="symbolic link"):
        paths.ensure_user_workspace("u_private")


def test_private_workspace_fails_closed_on_cross_profile_hard_link(
    mu_isolated_root,
) -> None:
    users = mu_isolated_root / "data" / "users"
    victim_file = users / "u_victim" / "user" / "chat_history.db"
    victim_file.parent.mkdir(parents=True)
    victim_file.write_bytes(b"victim transcript")
    attacker_file = users / "u_attacker" / "user" / "chat_history.db"
    attacker_file.parent.mkdir(parents=True)
    attacker_file.hardlink_to(victim_file)

    with pytest.raises(RuntimeError, match="hard-linked"):
        paths.ensure_user_workspace("u_attacker")


@pytest.mark.skipif(not hasattr(paths.os, "geteuid"), reason="POSIX ownership check")
def test_private_workspace_fails_closed_on_os_owner_mismatch(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "private"
    root.mkdir()
    original_lstat = Path.lstat

    def mismatched_lstat(path: Path):
        result = original_lstat(path)
        if path == root:
            return SimpleNamespace(
                st_mode=result.st_mode,
                st_nlink=result.st_nlink,
                st_uid=paths.os.geteuid() + 1,
            )
        return result

    monkeypatch.setattr(Path, "lstat", mismatched_lstat)
    with pytest.raises(RuntimeError, match="owned by another OS account"):
        paths.restrict_private_tree_permissions(root)


def test_role_change_cannot_reenable_a_disabled_account(tmp_path, monkeypatch) -> None:
    users_file = tmp_path / "data" / "system" / "auth" / "users.json"
    monkeypatch.setattr(identity, "USERS_FILE", users_file)
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "missing-users.json")

    record = identity.save_user("alice", "hash", role="admin")
    assert identity.delete_user("alice") is True
    assert identity.set_role("alice", "user") is True

    current = identity.get_user_by_id(record["id"])
    assert current is not None
    assert current[1]["disabled"] is True
    assert current[1]["role"] == "user"


def test_legacy_multi_user_tree_migrates_into_data(tmp_path, monkeypatch):
    legacy = tmp_path / "multi-user"
    (legacy / "_system" / "auth").mkdir(parents=True)
    (legacy / "_system" / "auth" / "users.json").write_text("{}")
    (legacy / "u_alice" / "user").mkdir(parents=True)
    (legacy / "u_alice" / "user" / "chat_history.db").write_text("x")

    users_root = tmp_path / "data" / "users"
    system_root = tmp_path / "data" / "system"
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", legacy)
    monkeypatch.setattr(paths, "USERS_ROOT", users_root)
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "_legacy_migration_done", False)

    paths.migrate_legacy_multi_user_tree()

    assert (system_root / "auth" / "users.json").read_text() == "{}"
    assert (users_root / "u_alice" / "user" / "chat_history.db").read_text() == "x"
    assert not legacy.exists()


def test_legacy_migration_never_overwrites_existing_targets(tmp_path, monkeypatch):
    legacy = tmp_path / "multi-user"
    (legacy / "u_alice").mkdir(parents=True)
    (legacy / "u_alice" / "old.txt").write_text("legacy")
    (legacy / "u_bob").mkdir(parents=True)
    (legacy / "u_bob" / "data.txt").write_text("bob")

    users_root = tmp_path / "data" / "users"
    (users_root / "u_alice").mkdir(parents=True)
    (users_root / "u_alice" / "new.txt").write_text("current")

    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", legacy)
    monkeypatch.setattr(paths, "USERS_ROOT", users_root)
    monkeypatch.setattr(paths, "SYSTEM_ROOT", tmp_path / "data" / "system")
    monkeypatch.setattr(paths, "_legacy_migration_done", False)

    paths.migrate_legacy_multi_user_tree()

    # Existing target untouched; the colliding legacy dir stays for manual
    # reconciliation while non-colliding siblings still migrate.
    assert (users_root / "u_alice" / "new.txt").read_text() == "current"
    assert (legacy / "u_alice" / "old.txt").read_text() == "legacy"
    assert (users_root / "u_bob" / "data.txt").read_text() == "bob"
    assert legacy.exists()
