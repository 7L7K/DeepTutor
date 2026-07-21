"""Path resolution for admin-local and per-user workspaces.

Everything lives under ``<runtime-home>/data`` so a deployment has exactly
one tree to mount and back up:

* ``data/user``           — the admin workspace (admin scope root is ``data/``)
* ``data/users/<uid>``    — one workspace per non-admin user
* ``data/partners/<id>``  — partner (synthetic-user) workspaces
* ``data/system``         — deployment state: accounts, grants, audit. Never
  mounted into the sandbox runner — see ``docker-compose.yml``.

Deployments upgraded from the sibling ``multi-user/`` layout are migrated
in place by :func:`migrate_legacy_multi_user_tree`.
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import threading
from typing import Iterator

from deeptutor.runtime.home import get_runtime_home
from deeptutor.services.path_service import PathService

from .models import LOCAL_ADMIN_ID, LOCAL_ADMIN_USERNAME, CurrentUser, UserScope

logger = logging.getLogger(__name__)

PROJECT_ROOT = get_runtime_home()
ADMIN_WORKSPACE_ROOT = PROJECT_ROOT / "data"
USERS_ROOT = ADMIN_WORKSPACE_ROOT / "users"
SYSTEM_ROOT = ADMIN_WORKSPACE_ROOT / "system"
LEGACY_MULTI_USER_ROOT = PROJECT_ROOT / "multi-user"

_path_services: dict[str, PathService] = {}

_legacy_migration_lock = threading.Lock()
_legacy_migration_done = False


def restrict_private_tree_permissions(root: Path) -> None:
    """Repair a private workspace tree without following symbolic links.

    The beta uses one OS account for the application, so directories need no
    group/world traversal and regular files need no group/world read access.
    Symlinks are forbidden in the application-managed private tree because a
    later legacy path join could otherwise follow one outside the profile.
    """
    root = Path(root)
    if root.is_symlink():
        raise ValueError("private workspace root cannot be a symbolic link")
    expected_uid = os.geteuid() if hasattr(os, "geteuid") else None

    def assert_owned(path: Path) -> None:
        if expected_uid is not None and path.lstat().st_uid != expected_uid:
            raise RuntimeError(
                f"private workspace path is owned by another OS account: {path}"
            )

    assert_owned(root)
    repaired_paths = [root]
    root.chmod(0o700)
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        assert_owned(current_path)
        repaired_paths.append(current_path)
        current_path.chmod(0o700)
        safe_dirs: list[str] = []
        for name in dirnames:
            child = current_path / name
            mode = child.lstat().st_mode
            assert_owned(child)
            if stat.S_ISLNK(mode):
                raise RuntimeError(f"symbolic link is not allowed in private workspace: {child}")
            if stat.S_ISDIR(mode):
                child.chmod(0o700)
                repaired_paths.append(child)
                safe_dirs.append(name)
        dirnames[:] = safe_dirs
        for name in filenames:
            child = current_path / name
            mode = child.lstat().st_mode
            assert_owned(child)
            if stat.S_ISLNK(mode):
                raise RuntimeError(f"symbolic link is not allowed in private workspace: {child}")
            if stat.S_ISREG(mode):
                if child.lstat().st_nlink > 1:
                    raise RuntimeError(
                        f"hard-linked file is not allowed in private workspace: {child}"
                    )
                child.chmod(0o600)
                repaired_paths.append(child)
    if sys.platform == "darwin":
        # POSIX mode bits do not override a macOS extended ACL. Strip inherited
        # or restored ACL entries before considering a private tree repaired.
        unique_paths = list(dict.fromkeys(repaired_paths))
        for offset in range(0, len(unique_paths), 200):
            try:
                subprocess.run(
                    ["/bin/chmod", "-N", *map(str, unique_paths[offset : offset + 200])],
                    check=True,
                    capture_output=True,
                )
            except (OSError, subprocess.CalledProcessError) as exc:
                raise RuntimeError(
                    f"Could not clear extended ACLs from private workspace {root}"
                ) from exc


def migrate_legacy_multi_user_tree() -> None:
    """One-time move of the pre-v1.5 sibling ``multi-user/`` tree into ``data/``.

    ``multi-user/_system`` becomes ``data/system``; every other child is a
    user id directory and becomes ``data/users/<uid>``. Existing targets are
    never overwritten — leftovers stay in place and are logged so an operator
    can reconcile by hand. Idempotent and cheap once migrated (one existence
    check), so callers on the auth/grants/workspace read paths can invoke it
    unconditionally.
    """
    global _legacy_migration_done
    if _legacy_migration_done:
        return
    with _legacy_migration_lock:
        if _legacy_migration_done:
            return
        legacy = LEGACY_MULTI_USER_ROOT
        if not legacy.is_dir():
            if USERS_ROOT.exists():
                for profile in USERS_ROOT.iterdir():
                    if profile.is_symlink():
                        raise RuntimeError(
                            f"symbolic link is not allowed as a private profile: {profile}"
                        )
                    if profile.is_dir():
                        restrict_private_tree_permissions(profile)
            _legacy_migration_done = True
            return
        leftovers: list[str] = []
        for child in sorted(legacy.iterdir()):
            target = SYSTEM_ROOT if child.name == "_system" else USERS_ROOT / child.name
            if target.exists():
                leftovers.append(child.name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(child), str(target))
            logger.info("Migrated legacy multi-user path %s -> %s", child, target)
        if USERS_ROOT.exists():
            for profile in USERS_ROOT.iterdir():
                if profile.is_symlink():
                    raise RuntimeError(
                        f"symbolic link is not allowed as a private profile: {profile}"
                    )
                if profile.is_dir():
                    restrict_private_tree_permissions(profile)
        if leftovers:
            for name in leftovers:
                leftover = legacy / name
                if name == "_system":
                    continue
                if leftover.is_symlink():
                    raise RuntimeError(
                        f"symbolic link is not allowed as a legacy private profile: {leftover}"
                    )
                if leftover.is_dir():
                    restrict_private_tree_permissions(leftover)
            logger.warning(
                "Legacy multi-user tree partially migrated; reconcile by hand: %s",
                ", ".join(str(legacy / name) for name in leftovers),
            )
            _legacy_migration_done = True
            return
        try:
            legacy.rmdir()
        except OSError:
            logger.warning("Could not remove legacy multi-user root %s", legacy)
        _legacy_migration_done = True


def admin_scope() -> UserScope:
    return UserScope(kind="admin", user_id=LOCAL_ADMIN_ID, root=ADMIN_WORKSPACE_ROOT.resolve())


def local_admin_user() -> CurrentUser:
    return CurrentUser(
        id=LOCAL_ADMIN_ID,
        username=LOCAL_ADMIN_USERNAME,
        role="admin",
        scope=admin_scope(),
    )


def scope_for_user(user_id: str, *, is_admin: bool) -> UserScope:
    if is_admin:
        return admin_scope()
    return personal_scope_for_user(user_id)


def personal_scope_for_user(user_id: str) -> UserScope:
    """Return the private workspace scope for an immutable user id.

    Authorization role and personal data ownership are deliberately separate:
    administrators still receive a private ``data/users/<uid>`` tree for
    courses and other learner-owned product data.  The legacy
    :func:`scope_for_user` contract continues to route generic admin features
    to the shared admin workspace.
    """
    if not user_id:
        raise ValueError("A non-empty user_id is required for a personal workspace")
    migrate_legacy_multi_user_tree()
    users_root = USERS_ROOT.resolve()
    candidate = users_root / user_id
    try:
        lexical_relative = candidate.relative_to(users_root)
    except ValueError as exc:
        raise ValueError("user_id resolves outside the private workspace root") from exc
    if lexical_relative.parts != (user_id,) or candidate.is_symlink():
        raise ValueError("user_id must identify exactly one non-symlink private workspace")
    root = candidate.resolve()
    try:
        relative = root.relative_to(users_root)
    except ValueError as exc:
        raise ValueError("user_id resolves outside the private workspace root") from exc
    if relative.parts != (user_id,):
        raise ValueError("user_id must identify exactly one private workspace")
    return UserScope(kind="user", user_id=user_id, root=root)


def ensure_user_workspace(user_id: str) -> Path:
    return ensure_scope_workspace(personal_scope_for_user(user_id))


def ensure_scope_workspace(scope: UserScope) -> Path:
    """Create the workspace tree for *scope* at its own root.

    Resolving from ``scope.root`` (instead of recomputing ``USERS_ROOT /
    user_id``) keeps this correct for synthetic scopes whose root lives
    elsewhere — e.g. partner workspaces under ``data/partners/<id>/workspace``.
    For regular users both paths are identical.
    """
    root = scope.root.resolve()
    if scope.kind == "user":
        # Private learner workspaces contain Course databases, source files,
        # transcripts, and mastery state.  Do not rely on the host process's
        # umask (commonly 022, which creates world-traversable directories).
        # The application process is the only OS principal that needs access
        # during the single-host beta.
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            restrict_private_tree_permissions(root)
        except OSError as exc:
            raise RuntimeError(
                f"Could not enforce private workspace permissions for {root}"
            ) from exc
    PathService(workspace_root=root).ensure_all_directories()
    (root / "knowledge_bases").mkdir(parents=True, exist_ok=True)
    (root / "memory").mkdir(parents=True, exist_ok=True)
    if scope.kind == "user":
        try:
            restrict_private_tree_permissions(root)
        except OSError as exc:
            raise RuntimeError(
                f"Could not enforce private workspace permissions for {root}"
            ) from exc
    return root


def ensure_system_dirs() -> None:
    migrate_legacy_multi_user_tree()
    for child in ("auth", "grants", "audit", "indexes"):
        (SYSTEM_ROOT / child).mkdir(parents=True, exist_ok=True)


def get_path_service_for_scope(scope: UserScope) -> PathService:
    key = scope.cache_key
    service = _path_services.get(key)
    if service is None:
        service = PathService(workspace_root=scope.root)
        _path_services[key] = service
    return service


def get_admin_path_service() -> PathService:
    return get_path_service_for_scope(admin_scope())


def get_current_path_service() -> PathService:
    from .context import get_current_user_or_none

    user = get_current_user_or_none()
    if user is None:
        return PathService.get_instance()
    if user.scope.kind == "user":
        ensure_scope_workspace(user.scope)
    return get_path_service_for_scope(user.scope)


def get_personal_path_service(user_id: str | None = None) -> PathService:
    """Resolve a private user workspace without any admin/default fallback.

    Course-owned services use this accessor instead of ``get_path_service``.
    When ``user_id`` is omitted an installed authenticated context is required;
    absence is a terminal ownership error rather than a route to admin data.
    """
    if user_id is None:
        from .context import get_current_user_or_none

        current = get_current_user_or_none()
        if current is None:
            raise RuntimeError("Authenticated user context is required")
        user_id = current.id
    scope = personal_scope_for_user(user_id)
    ensure_scope_workspace(scope)
    return get_path_service_for_scope(scope)


@contextmanager
def user_context(user: CurrentUser) -> Iterator[None]:
    from .context import reset_current_user, set_current_user

    token = set_current_user(user)
    try:
        yield
    finally:
        reset_current_user(token)
