#!/usr/bin/env python3
"""Verify or migrate every explicitly discovered private Course database.

The command is intentionally dry-run by default. An operator must provide
``--apply`` and an explicit data root before any database is opened for write.
Only the admin database and one database per immediate user directory are in
scope; symlinks and nested/ambiguous paths are ignored.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import sys

from deeptutor.courses.database_lock import course_database_lock
from deeptutor.courses.migrations.runner import (
    MigrationArtifact,
    discover_migrations,
    ensure_course_schema,
)


@dataclass(frozen=True)
class DatabaseCheck:
    path: Path
    status: str
    applied: tuple[int, ...] = ()
    detail: str = ""


def discover_course_databases(data_root: Path) -> tuple[Path, ...]:
    """Return only the supported, non-symlink Course database locations."""
    if data_root.is_symlink() or not data_root.is_dir():
        raise ValueError(f"Data root is not a real directory: {data_root}")
    root = data_root.resolve()
    candidates: list[Path] = []
    admin = root / "user" / "courses.db"
    if admin.is_file() and not admin.is_symlink():
        candidates.append(admin)
    users = root / "users"
    if users.is_dir() and not users.is_symlink():
        for user_dir in sorted(users.iterdir()):
            if not user_dir.is_dir() or user_dir.is_symlink():
                continue
            candidate = user_dir / "user" / "courses.db"
            if candidate.is_file() and not candidate.is_symlink():
                candidates.append(candidate)
    return tuple(candidates)


def _receipt_state(path: Path, artifacts: tuple[MigrationArtifact, ...]) -> tuple[int, str]:
    uri = f"file:{path.resolve()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise ValueError(f"cannot open read-only: {exc}") from exc
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA foreign_keys=ON")
        has_ledger = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        if not has_ledger:
            return 0, "migration ledger is missing"
        rows = conn.execute(
            "SELECT version, name, checksum_sha256 FROM schema_migrations ORDER BY version"
        ).fetchall()
        if len(rows) > len(artifacts):
            return len(rows), "database records an unknown migration"
        for index, row in enumerate(rows):
            expected = artifacts[index]
            if tuple(row) != (expected.version, expected.name, expected.checksum_sha256):
                return index, f"receipt mismatch at {expected.filename}"
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'blueway_workspace_assertion_replays'"
        ).fetchone():
            return len(rows), "workspace assertion replay fence is missing"
        return len(rows), "ready" if len(rows) == len(artifacts) else "pending migrations"
    finally:
        conn.close()


def check_database(
    path: Path, *, apply: bool, artifacts: tuple[MigrationArtifact, ...]
) -> DatabaseCheck:
    if apply:
        applied = ensure_course_schema(path, write_lock=course_database_lock(path))
        status = "ready" if not applied else "migrated"
        return DatabaseCheck(path, status, tuple(applied), "")
    count, detail = _receipt_state(path, artifacts)
    return DatabaseCheck(
        path,
        "ready" if detail == "ready" else "pending",
        tuple(item.version for item in artifacts[:count]),
        detail,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="Explicit TEEECHR data directory containing user/ and users/",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply pending migrations; omitted means read-only verification",
    )
    args = parser.parse_args(argv)
    try:
        artifacts = discover_migrations()
        databases = discover_course_databases(args.data_root)
        print(f"discovered={len(databases)} mode={'apply' if args.apply else 'verify'}")
        if not databases:
            print("error: no existing Course databases were discovered", file=sys.stderr)
            return 2
        for path in databases:
            result = check_database(path, apply=args.apply, artifacts=artifacts)
            suffix = (
                f" applied={','.join(str(version) for version in result.applied)}"
                if result.applied
                else ""
            )
            detail = f" detail={result.detail}" if result.detail else ""
            print(f"{result.status} {path}{suffix}{detail}")
            if result.status == "pending" and not args.apply:
                return 2
        return 0
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
