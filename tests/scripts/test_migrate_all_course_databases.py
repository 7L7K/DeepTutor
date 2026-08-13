from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from deeptutor.courses.migrations.runner import (
    discover_migrations,
    ensure_course_schema,
    open_course_connection,
)


def _module():
    path = Path(__file__).parents[2] / "scripts" / "migrate-all-course-databases.py"
    spec = importlib.util.spec_from_file_location("migrate_all_course_databases", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_discovery_is_bounded_and_ignores_symlinks(tmp_path: Path) -> None:
    module = _module()
    (tmp_path / "user").mkdir()
    (tmp_path / "users" / "alice" / "user").mkdir(parents=True)
    (tmp_path / "users" / "nested" / "ignored" / "user").mkdir(parents=True)
    admin = tmp_path / "user" / "courses.db"
    alice = tmp_path / "users" / "alice" / "user" / "courses.db"
    admin.touch()
    alice.touch()
    outside = tmp_path / "outside.db"
    outside.touch()
    (tmp_path / "users" / "bob").symlink_to(outside.parent, target_is_directory=True)
    assert module.discover_course_databases(tmp_path) == (admin, alice)


def test_verify_then_apply_covers_all_discovered_databases(tmp_path: Path) -> None:
    module = _module()
    (tmp_path / "user").mkdir()
    (tmp_path / "users" / "alice" / "user").mkdir(parents=True)
    paths = (tmp_path / "user" / "courses.db", tmp_path / "users" / "alice" / "user" / "courses.db")
    for path in paths:
        ensure_course_schema(path)
        with open_course_connection(path) as conn:
            conn.execute("DELETE FROM schema_migrations WHERE version = 17")
            conn.execute("DROP TABLE blueway_workspace_assertion_replays")
    artifacts = discover_migrations()
    results = [module.check_database(path, apply=False, artifacts=artifacts) for path in paths]
    assert [result.status for result in results] == ["pending", "pending"]
    assert all("pending migrations" in result.detail or "replay fence" in result.detail for result in results)
    for path in paths:
        result = module.check_database(path, apply=True, artifacts=artifacts)
        assert result.status == "migrated"
        assert result.applied == (17,)
        assert module.check_database(path, apply=False, artifacts=artifacts).status == "ready"
