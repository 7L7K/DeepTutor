#!/usr/bin/env python3
"""Create and restore a verified TEEECHR runtime-data backup.

The school beta stores all durable application state below one explicit
``data/`` directory.  This command provides the missing operator primitive for
that boundary.  It is deliberately conservative:

* the application must be stopped (the private Course lock is checked when it
  exists); callers must still stop other writers before invoking the command;
* source and archive trees may not contain symbolic links, hard links, or
  special files;
* the archive carries a content manifest and restore validates every member
  before replacing anything;
* replacing an existing target requires ``--replace`` and moves the old tree
  aside instead of deleting it;
* the ephemeral application lock is excluded so a restore cannot revive a
  stale process lock.

This utility never talks to a provider, PocketBase, BlueWay, or a hosted
deployment.  Keep generated archives in operator-controlled private storage.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile
import tempfile
from typing import Iterator
import uuid

from deeptutor.courses.deployment import SingleProcessCourseLock

MANIFEST_NAME = "__teeechr_backup_manifest__.json"
MANIFEST_VERSION = 1
LOCK_RELATIVE_PATH = Path("system") / "course-single-process.lock"


class BackupError(RuntimeError):
    """Raised when a backup or restore cannot be proven safe."""


@dataclass(frozen=True)
class TreeEntry:
    path: str
    kind: str
    mode: int
    size: int = 0
    sha256: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "path": self.path,
            "kind": self.kind,
            "mode": self.mode,
            "size": self.size,
        }
        if self.sha256 is not None:
            payload["sha256"] = self.sha256
        return payload


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _validate_root(path: Path, *, label: str) -> Path:
    path = Path(path).expanduser()
    if path.exists() and path.is_symlink():
        raise BackupError(f"{label} must not be a symbolic link: {path}")
    if not path.exists() or not path.is_dir():
        raise BackupError(f"{label} is not a real directory: {path}")
    return path.resolve()


def _relative_path(path: Path) -> str:
    # ``Path.as_posix`` is stable across the supported host platforms.  The
    # manifest is intentionally a relative POSIX path so an archive cannot
    # smuggle a host-specific separator into restore validation.
    return path.as_posix() if str(path) != "." else "."


def _is_excluded(relative: Path) -> bool:
    return relative == LOCK_RELATIVE_PATH


def _iter_entries(data_root: Path) -> Iterator[TreeEntry]:
    """Walk *data_root* without following links and return a sorted manifest."""
    root_stat = data_root.lstat()
    if stat.S_ISLNK(root_stat.st_mode):
        raise BackupError(f"data root is a symbolic link: {data_root}")
    if not stat.S_ISDIR(root_stat.st_mode):
        raise BackupError(f"data root is not a directory: {data_root}")

    entries: list[TreeEntry] = [
        TreeEntry(path=".", kind="dir", mode=stat.S_IMODE(root_stat.st_mode))
    ]
    for current, dirnames, filenames in os.walk(data_root, topdown=True, followlinks=False):
        current_path = Path(current)
        safe_dirs: list[str] = []
        for name in sorted(dirnames):
            child = current_path / name
            relative = child.relative_to(data_root)
            if _is_excluded(relative):
                dirnames.remove(name)
                continue
            if relative.as_posix() == MANIFEST_NAME:
                raise BackupError(f"reserved backup manifest path is present in data: {child}")
            child_stat = child.lstat()
            if stat.S_ISLNK(child_stat.st_mode):
                raise BackupError(f"symbolic link is not allowed: {child}")
            if not stat.S_ISDIR(child_stat.st_mode):
                raise BackupError(f"unsupported directory entry: {child}")
            entries.append(
                TreeEntry(
                    path=_relative_path(relative), kind="dir", mode=stat.S_IMODE(child_stat.st_mode)
                )
            )
            safe_dirs.append(name)
        dirnames[:] = safe_dirs

        for name in sorted(filenames):
            child = current_path / name
            relative = child.relative_to(data_root)
            if _is_excluded(relative):
                continue
            if relative.as_posix() == MANIFEST_NAME:
                raise BackupError(f"reserved backup manifest path is present in data: {child}")
            child_stat = child.lstat()
            if stat.S_ISLNK(child_stat.st_mode):
                raise BackupError(f"symbolic link is not allowed: {child}")
            if not stat.S_ISREG(child_stat.st_mode):
                raise BackupError(f"special file is not allowed: {child}")
            if child_stat.st_nlink != 1:
                raise BackupError(f"hard-linked file is not allowed: {child}")
            size, digest = _sha256_file(child)
            entries.append(
                TreeEntry(
                    path=_relative_path(relative),
                    kind="file",
                    mode=stat.S_IMODE(child_stat.st_mode),
                    size=size,
                    sha256=digest,
                )
            )

    entries.sort(key=lambda item: (item.path != ".", item.path))
    return iter(entries)


def _tree_digest(entries: tuple[TreeEntry, ...] | list[TreeEntry]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(json.dumps(entry.as_dict(), sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _manifest(entries: tuple[TreeEntry, ...], *, created_at: str) -> dict[str, object]:
    return {
        "schema_version": MANIFEST_VERSION,
        "kind": "teeechr-runtime-data-backup",
        "created_at_utc": created_at,
        "excluded_paths": [LOCK_RELATIVE_PATH.as_posix()],
        "tree_digest": _tree_digest(entries),
        "entries": [entry.as_dict() for entry in entries],
    }


def _manifest_entries(payload: object) -> tuple[TreeEntry, ...]:
    if not isinstance(payload, dict):
        raise BackupError("backup manifest is not an object")
    if payload.get("schema_version") != MANIFEST_VERSION:
        raise BackupError("unsupported backup manifest version")
    if payload.get("kind") != "teeechr-runtime-data-backup":
        raise BackupError("not a TEEECHR runtime-data backup")
    if payload.get("excluded_paths") != [LOCK_RELATIVE_PATH.as_posix()]:
        raise BackupError("backup lock exclusion is invalid")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise BackupError("backup manifest has no entries")
    entries: list[TreeEntry] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise BackupError("backup manifest entry is not an object")
        path = raw.get("path")
        kind = raw.get("kind")
        mode = raw.get("mode")
        size = raw.get("size", 0)
        sha256 = raw.get("sha256")
        if not isinstance(path, str) or not isinstance(kind, str) or kind not in {"dir", "file"}:
            raise BackupError("backup manifest entry has invalid path or kind")
        pure = PurePosixPath(path)
        if path == "" or pure.is_absolute() or ".." in pure.parts or "\\" in path:
            raise BackupError(f"backup manifest path is unsafe: {path!r}")
        if path in seen or path == MANIFEST_NAME or path == LOCK_RELATIVE_PATH.as_posix():
            raise BackupError(f"backup manifest path is duplicated or reserved: {path!r}")
        if path == "." and kind != "dir":
            raise BackupError("backup manifest root entry must be a directory")
        if not isinstance(mode, int) or mode < 0 or mode > 0o7777:
            raise BackupError(f"backup manifest mode is invalid: {path!r}")
        if not isinstance(size, int) or size < 0:
            raise BackupError(f"backup manifest size is invalid: {path!r}")
        if kind == "file":
            if not isinstance(sha256, str) or len(sha256) != 64:
                raise BackupError(f"backup manifest file digest is invalid: {path!r}")
        elif sha256 is not None or size != 0:
            raise BackupError(f"backup manifest directory metadata is invalid: {path!r}")
        seen.add(path)
        entries.append(TreeEntry(path=path, kind=kind, mode=mode, size=size, sha256=sha256))
    entries.sort(key=lambda item: (item.path != ".", item.path))
    expected_digest = payload.get("tree_digest")
    if expected_digest != _tree_digest(entries):
        raise BackupError("backup manifest tree digest is invalid")
    return tuple(entries)


@contextmanager
def _require_stopped(data_root: Path) -> Iterator[None]:
    """Fail if the app owns the Course lock, without creating a new lock file."""
    lock_path = data_root / LOCK_RELATIVE_PATH
    if not lock_path.exists():
        yield
        return
    if lock_path.is_symlink() or not lock_path.is_file():
        raise BackupError(f"Course lock path is not a regular file: {lock_path}")
    lock = SingleProcessCourseLock(lock_path)
    try:
        # The utility is itself not a Course worker; ignore inherited worker
        # settings while probing whether an application currently holds this
        # lock.
        lock.acquire(env={"WEB_CONCURRENCY": "1", "UVICORN_WORKERS": "1", "GUNICORN_CMD_ARGS": ""})
    except RuntimeError as exc:
        raise BackupError(str(exc)) from exc
    try:
        yield
    finally:
        lock.release()


def _archive_sha256(path: Path) -> str:
    return _sha256_file(path)[1]


def _write_tar_member(
    tar: tarfile.TarFile,
    name: str,
    *,
    kind: str,
    mode: int,
    source: Path | None = None,
) -> None:
    info = tarfile.TarInfo(name=name)
    info.mode = mode
    info.mtime = 0
    if kind == "dir":
        info.type = tarfile.DIRTYPE
        info.size = 0
        tar.addfile(info)
        return
    if source is None:
        raise BackupError(f"missing source for archive member: {name}")
    info.type = tarfile.REGTYPE
    info.size = source.stat().st_size
    with source.open("rb") as handle:
        tar.addfile(info, handle)


def create_backup(data_root: Path, output: Path, *, overwrite: bool = False) -> dict[str, object]:
    data_root = _validate_root(data_root, label="data root")
    output = Path(output).expanduser()
    if output.is_symlink():
        raise BackupError(f"backup output must not be a symbolic link: {output}")
    output = output.resolve()
    if output.exists() and not overwrite:
        raise BackupError(f"backup output already exists; pass --overwrite to replace it: {output}")
    output_parent = output.parent.resolve()
    output_parent.mkdir(parents=True, exist_ok=True)
    try:
        output.relative_to(data_root)
    except ValueError:
        pass
    else:
        raise BackupError("backup output must be outside the data root")

    temp_path: Path | None = None
    try:
        with _require_stopped(data_root):
            entries = tuple(_iter_entries(data_root))
            created_at = datetime.now(timezone.utc).isoformat()
            manifest = _manifest(entries, created_at=created_at)
            manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
            fd, raw_temp = tempfile.mkstemp(
                prefix=f".{output.name}.", suffix=".tmp", dir=output_parent
            )
            os.close(fd)
            temp_path = Path(raw_temp)
            os.chmod(temp_path, 0o600)
            with tarfile.open(temp_path, mode="w:gz") as tar:
                for entry in entries:
                    if entry.path == ".":
                        continue
                    source = data_root / Path(entry.path)
                    _write_tar_member(
                        tar,
                        entry.path,
                        kind=entry.kind,
                        mode=entry.mode,
                        source=source if entry.kind == "file" else None,
                    )
                info = tarfile.TarInfo(MANIFEST_NAME)
                info.mode = 0o600
                info.mtime = 0
                info.size = len(manifest_bytes)
                tar.addfile(info, fileobj=_BytesReader(manifest_bytes))
            os.replace(temp_path, output)
            temp_path = None
            os.chmod(output, 0o600)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    return {
        "status": "created",
        "backup": str(output.resolve()),
        "archive_sha256": _archive_sha256(output),
        "tree_digest": manifest["tree_digest"],
        "entry_count": len(entries),
        "created_at_utc": created_at,
    }


class _BytesReader:
    """Minimal file-like wrapper accepted by ``TarFile.addfile``."""

    def __init__(self, data: bytes) -> None:
        from io import BytesIO

        self._handle = BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._handle.read(size)


def _read_manifest(archive: Path) -> tuple[dict[str, object], tuple[TreeEntry, ...]]:
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            members = tar.getmembers()
            manifest_members = [item for item in members if item.name == MANIFEST_NAME]
            if len(manifest_members) != 1:
                raise BackupError("backup must contain exactly one manifest")
            if any(item.name == MANIFEST_NAME and not item.isfile() for item in members):
                raise BackupError("backup manifest is not a regular file")
            handle = tar.extractfile(manifest_members[0])
            if handle is None:
                raise BackupError("backup manifest cannot be read")
            try:
                payload = json.loads(handle.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BackupError("backup manifest is not valid JSON") from exc
            entries = _manifest_entries(payload)
            entry_by_path = {entry.path: entry for entry in entries if entry.path != "."}
            seen: set[str] = set()
            for member in members:
                if member.name == MANIFEST_NAME:
                    continue
                entry = entry_by_path.get(member.name)
                if entry is None or member.name in seen:
                    raise BackupError(
                        f"archive member is not declared exactly once: {member.name!r}"
                    )
                seen.add(member.name)
                _safe_member_path(Path("/tmp/teeechr-backup-verify"), member.name)
                if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                    raise BackupError(f"archive member type is not allowed: {member.name!r}")
                if member.isdir() != (entry.kind == "dir") or member.isfile() != (
                    entry.kind == "file"
                ):
                    raise BackupError(
                        f"archive member kind disagrees with manifest: {member.name!r}"
                    )
                if stat.S_IMODE(member.mode) != entry.mode:
                    raise BackupError(
                        f"archive member mode disagrees with manifest: {member.name!r}"
                    )
                if entry.kind == "file":
                    if member.size != entry.size:
                        raise BackupError(
                            f"archive member size disagrees with manifest: {member.name!r}"
                        )
                    handle = tar.extractfile(member)
                    if handle is None:
                        raise BackupError(f"archive member cannot be read: {member.name!r}")
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                    if digest.hexdigest() != entry.sha256:
                        raise BackupError(
                            f"archive member digest disagrees with manifest: {member.name!r}"
                        )
            if seen != set(entry_by_path):
                missing = sorted(set(entry_by_path) - seen)
                raise BackupError(f"backup archive is missing declared members: {missing[:3]}")
            return payload, entries
    except tarfile.TarError as exc:
        raise BackupError(f"could not read backup archive: {archive}") from exc


def verify_backup(archive: Path) -> dict[str, object]:
    archive = Path(archive).expanduser().resolve()
    if not archive.is_file() or archive.is_symlink():
        raise BackupError(f"backup archive is not a regular file: {archive}")
    payload, entries = _read_manifest(archive)
    return {
        "status": "verified",
        "backup": str(archive),
        "archive_sha256": _archive_sha256(archive),
        "tree_digest": payload["tree_digest"],
        "entry_count": len(entries),
        "created_at_utc": payload.get("created_at_utc", ""),
    }


def _safe_member_path(root: Path, name: str) -> Path:
    pure = PurePosixPath(name)
    if name in {"", "."} or pure.is_absolute() or ".." in pure.parts or "\\" in name:
        raise BackupError(f"archive member path is unsafe: {name!r}")
    candidate = root.joinpath(*pure.parts)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise BackupError(f"archive member escapes restore root: {name!r}") from exc
    return candidate


def _extract_verified(archive: Path, staging: Path, entries: tuple[TreeEntry, ...]) -> None:
    entry_by_path = {entry.path: entry for entry in entries if entry.path != "."}
    seen: set[str] = set()
    root_entry = next(entry for entry in entries if entry.path == ".")
    staging.mkdir(parents=True, exist_ok=False)
    staging.chmod(root_entry.mode)
    with tarfile.open(archive, mode="r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            if member.name == MANIFEST_NAME:
                continue
            entry = entry_by_path.get(member.name)
            if entry is None or member.name in seen:
                raise BackupError(f"archive member is not declared exactly once: {member.name!r}")
            seen.add(member.name)
            target = _safe_member_path(staging, member.name)
            if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                raise BackupError(f"archive member type is not allowed: {member.name!r}")
            if member.isdir() != (entry.kind == "dir") or member.isfile() != (entry.kind == "file"):
                raise BackupError(f"archive member kind disagrees with manifest: {member.name!r}")
            if stat.S_IMODE(member.mode) != entry.mode:
                raise BackupError(f"archive member mode disagrees with manifest: {member.name!r}")
            if entry.kind == "dir":
                target.mkdir(parents=False, exist_ok=False)
                target.chmod(entry.mode)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            handle = tar.extractfile(member)
            if handle is None:
                raise BackupError(f"archive member cannot be read: {member.name!r}")
            digest = hashlib.sha256()
            size = 0
            with target.open("xb") as output:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            target.chmod(entry.mode)
            if size != entry.size or digest.hexdigest() != entry.sha256:
                raise BackupError(
                    f"archive member content disagrees with manifest: {member.name!r}"
                )
    if seen != set(entry_by_path):
        missing = sorted(set(entry_by_path) - seen)
        raise BackupError(f"backup archive is missing declared members: {missing[:3]}")
    extracted_entries = tuple(_iter_entries(staging))
    if _tree_digest(extracted_entries) != _tree_digest(entries):
        raise BackupError("restored staging tree digest does not match backup manifest")


def restore_backup(archive: Path, data_root: Path, *, replace: bool = False) -> dict[str, object]:
    archive = Path(archive).expanduser().resolve()
    if not archive.is_file() or archive.is_symlink():
        raise BackupError(f"backup archive is not a regular file: {archive}")
    payload, entries = _read_manifest(archive)
    target = Path(data_root).expanduser()
    if target.exists() and target.is_symlink():
        raise BackupError(f"restore target must not be a symbolic link: {target}")
    target_parent = target.parent.resolve()
    target_parent.mkdir(parents=True, exist_ok=True)
    staging = target_parent / f".{target.name}.restore-{uuid.uuid4().hex}"
    previous: Path | None = None
    try:
        with _require_stopped(target.resolve() if target.exists() else target):
            if target.exists() and not target.is_dir():
                raise BackupError(f"restore target is not a directory: {target}")
            if target.exists() and any(target.iterdir()) and not replace:
                raise BackupError(
                    "restore target is non-empty; pass --replace to preserve and replace it"
                )
            _extract_verified(archive, staging, entries)
            if target.exists():
                previous = target_parent / (
                    f"{target.name}.before-restore-"
                    f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
                )
                if previous.exists():
                    raise BackupError(f"refusing to overwrite previous restore backup: {previous}")
                target.rename(previous)
            staging.rename(target)
    except Exception:
        if staging.exists():
            import shutil

            shutil.rmtree(staging)
        if previous is not None and not target.exists() and previous.exists():
            previous.rename(target)
        raise

    restored_entries = tuple(_iter_entries(target))
    return {
        "status": "restored",
        "backup": str(archive),
        "target": str(target.resolve()),
        "archive_sha256": _archive_sha256(archive),
        "tree_digest": payload["tree_digest"],
        "restored_tree_digest": _tree_digest(restored_entries),
        "previous_data_root": str(previous.resolve()) if previous is not None else None,
        "entry_count": len(restored_entries),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="create a verified archive of one stopped data tree")
    create.add_argument("--data-root", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--overwrite", action="store_true")

    verify = sub.add_parser("verify", help="verify an archive manifest and archive digest")
    verify.add_argument("--backup", type=Path, required=True)

    restore = sub.add_parser("restore", help="verify and restore an archive")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--data-root", type=Path, required=True)
    restore.add_argument("--replace", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            result = create_backup(args.data_root, args.output, overwrite=args.overwrite)
        elif args.command == "verify":
            result = verify_backup(args.backup)
        else:
            result = restore_backup(args.backup, args.data_root, replace=args.replace)
    except (BackupError, OSError, ValueError, tarfile.TarError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
