"""Persistent deployment authority for BlueWay integration secrets.

The single-host beta keeps one server-side AES key and one local copy of the
BlueWay pairing secret.  They are never browser data and are not colocated
with an owner's Course database.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
from typing import Iterable


class CredentialAuthorityError(RuntimeError):
    """Persistent integration secret material is unavailable or unsafe."""


@dataclass(frozen=True)
class PersistentBlueWaySecrets:
    key_id: str
    master_key: bytes
    api_secret: str

    def __post_init__(self) -> None:
        if (
            not self.key_id.startswith("bwa_")
            or len(self.key_id) > 80
            or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                   for character in self.key_id)
        ):
            raise CredentialAuthorityError("BlueWay secret key id is invalid")
        if len(self.master_key) != 32:
            raise CredentialAuthorityError("BlueWay credential key must be 32 bytes")
        if not 32 <= len(self.api_secret) <= 1024:
            raise CredentialAuthorityError("BlueWay pairing secret is invalid")

    @classmethod
    def fresh(cls, *, api_secret: str) -> "PersistentBlueWaySecrets":
        return cls(
            key_id=f"bwa_{secrets.token_hex(16)}",
            master_key=secrets.token_bytes(32),
            api_secret=api_secret,
        )


class PrivateFileCredentialAuthority:
    """Strict POSIX private-file authority with exclusive atomic creation."""

    _SCHEMA_VERSION = 1
    _FIELDS = {
        "schema_version",
        "key_id",
        "master_key_b64",
        "api_secret",
    }

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @staticmethod
    def _expected_uid() -> int | None:
        return os.geteuid() if hasattr(os, "geteuid") else None

    def _validate_parent(self, *, create: bool) -> None:
        parent = self.path.parent
        if parent.exists() and parent.is_symlink():
            raise CredentialAuthorityError(
                "BlueWay secret directory cannot be a symbolic link"
            )
        if create:
            try:
                parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                parent.chmod(0o700)
            except OSError as exc:
                raise CredentialAuthorityError(
                    "Could not create BlueWay secret directory"
                ) from exc
        try:
            info = parent.lstat()
        except OSError as exc:
            raise CredentialAuthorityError(
                "BlueWay secret directory is unavailable"
            ) from exc
        expected_uid = self._expected_uid()
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or (expected_uid is not None and info.st_uid != expected_uid)
            or info.st_mode & 0o077
        ):
            raise CredentialAuthorityError(
                "BlueWay secret directory fails private-directory checks"
            )

    def _read_bytes(self) -> bytes:
        self._validate_parent(create=False)
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.path, flags)
        except OSError as exc:
            raise CredentialAuthorityError(
                "BlueWay secret authority is unavailable"
            ) from exc
        try:
            info = os.fstat(fd)
            expected_uid = self._expected_uid()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (expected_uid is not None and info.st_uid != expected_uid)
                or info.st_mode & 0o077
            ):
                raise CredentialAuthorityError(
                    "BlueWay secret authority fails private-file checks"
                )
            with os.fdopen(fd, "rb") as handle:
                return handle.read()
        except Exception:
            os.close(fd)
            raise

    def exists(self) -> bool:
        return self.path.exists() and not self.path.is_symlink()

    def load(self) -> PersistentBlueWaySecrets:
        raw = self._read_bytes()
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CredentialAuthorityError(
                "BlueWay secret authority is malformed"
            ) from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != self._FIELDS
            or payload.get("schema_version") != self._SCHEMA_VERSION
        ):
            raise CredentialAuthorityError(
                "BlueWay secret authority is malformed"
            )
        try:
            master_key = base64.b64decode(
                str(payload["master_key_b64"]), validate=True
            )
        except (binascii.Error, ValueError) as exc:
            raise CredentialAuthorityError(
                "BlueWay secret authority is malformed"
            ) from exc
        try:
            return PersistentBlueWaySecrets(
                key_id=str(payload["key_id"]),
                master_key=master_key,
                api_secret=str(payload["api_secret"]),
            )
        except (KeyError, CredentialAuthorityError) as exc:
            raise CredentialAuthorityError(
                "BlueWay secret authority is malformed"
            ) from exc

    def create(self, material: PersistentBlueWaySecrets) -> None:
        self._validate_parent(create=True)
        if self.path.exists() or self.path.is_symlink():
            raise CredentialAuthorityError(
                "BlueWay secret authority already exists"
            )
        payload = json.dumps(
            {
                "schema_version": self._SCHEMA_VERSION,
                "key_id": material.key_id,
                "master_key_b64": base64.b64encode(
                    material.master_key
                ).decode("ascii"),
                "api_secret": material.api_secret,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        temporary = self.path.parent / (
            f".{self.path.name}.{secrets.token_hex(8)}.tmp"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(temporary, flags, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, self.path)
            except FileExistsError as exc:
                raise CredentialAuthorityError(
                    "BlueWay secret authority already exists"
                ) from exc
            temporary.unlink()
            self.path.chmod(0o600)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            # Read through the same strict path before accepting authority.
            if self.load() != material:
                raise CredentialAuthorityError(
                    "BlueWay secret authority verification failed"
                )
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


def _workspace_user_roots(data_root: Path) -> Iterable[Path]:
    legacy_admin = data_root / "user"
    if legacy_admin.is_dir() and not legacy_admin.is_symlink():
        yield legacy_admin
    users = data_root / "users"
    if not users.is_dir() or users.is_symlink():
        return
    for owner in users.iterdir():
        user_root = owner / "user"
        if (
            owner.is_dir()
            and not owner.is_symlink()
            and user_root.is_dir()
            and not user_root.is_symlink()
        ):
            yield user_root


def _preflight_existing_envelopes(
    *, data_root: Path, candidate_master_key: bytes,
) -> None:
    """Prove a legacy key against every referenced envelope before persisting it."""
    # Import lazily to keep the strict authority primitive dependency-light.
    from .credentials import CredentialError, CredentialStore

    observed_files: set[Path] = set()
    referenced_files: set[Path] = set()
    for user_root in _workspace_user_roots(data_root):
        credentials_root = user_root / "integration_credentials"
        if credentials_root.exists():
            observed_files.update(
                path
                for path in credentials_root.glob("*.enc")
                if not path.name.startswith(".")
            )
        database = user_root / "courses.db"
        if not database.is_file() or database.is_symlink():
            continue
        try:
            connection = sqlite3.connect(
                f"file:{database}?mode=ro", uri=True
            )
            connection.row_factory = sqlite3.Row
            tables = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if "blueway_connections" not in tables:
                connection.close()
                continue
            rows = connection.execute(
                """SELECT id, owner_user_id, scope_version,
                          rotation_request_id
                   FROM blueway_connections
                   WHERE state IN ('active', 'revocation_pending')
                     AND credential_ref IS NOT NULL"""
            ).fetchall()
            connection.close()
        except sqlite3.Error as exc:
            raise CredentialAuthorityError(
                "Could not verify existing BlueWay credentials"
            ) from exc
        store = CredentialStore(credentials_root, candidate_master_key)
        for row in rows:
            connection_id = str(row["id"])
            primary = credentials_root / f"{connection_id}.enc"
            referenced_files.add(primary)
            try:
                store.preflight(
                    owner_user_id=str(row["owner_user_id"]),
                    connection_id=connection_id,
                    scope_version=str(row["scope_version"]),
                )
                rotation_id = row["rotation_request_id"]
                if rotation_id:
                    rotation = (
                        credentials_root
                        / f"{connection_id}.rotation.enc"
                    )
                    referenced_files.add(rotation)
                    if store.read_rotation_envelope(
                        owner_user_id=str(row["owner_user_id"]),
                        connection_id=connection_id,
                        scope_version=str(row["scope_version"]),
                        expected_rotation_request_id=str(rotation_id),
                    ) is None:
                        raise CredentialError(
                            "Rotation envelope is unavailable"
                        )
            except CredentialError as exc:
                raise CredentialAuthorityError(
                    "Existing BlueWay credentials require owner recovery"
                ) from exc
    if observed_files - referenced_files:
        raise CredentialAuthorityError(
            "Unreferenced BlueWay credentials require operator review"
        )


def resolve_persistent_blueway_secrets(
    *, authority_path: Path, data_root: Path,
    candidate_master_key: bytes | None, candidate_api_secret: str | None,
    allow_bootstrap: bool, allow_recovery_bootstrap: bool,
) -> PersistentBlueWaySecrets:
    """Load stable authority or perform one explicit, non-overwriting bootstrap."""
    if allow_bootstrap and allow_recovery_bootstrap:
        raise CredentialAuthorityError(
            "BlueWay normal and recovery bootstrap modes are mutually exclusive"
        )
    authority = PrivateFileCredentialAuthority(authority_path)
    if authority.exists():
        material = authority.load()
        if (
            candidate_master_key is not None
            and candidate_master_key != material.master_key
        ) or (
            candidate_api_secret is not None
            and candidate_api_secret != material.api_secret
        ):
            raise CredentialAuthorityError(
                "BlueWay secret authority does not match supplied material"
            )
        return material
    if not (allow_bootstrap or allow_recovery_bootstrap):
        raise CredentialAuthorityError(
            "BlueWay secret authority requires explicit bootstrap"
        )
    if candidate_api_secret is None:
        raise CredentialAuthorityError(
            "BlueWay pairing secret is required for bootstrap"
        )
    if candidate_master_key is None:
        if not allow_recovery_bootstrap:
            raise CredentialAuthorityError(
                "BlueWay credential key is required for legacy bootstrap"
            )
        candidate_master_key = secrets.token_bytes(32)
    if not allow_recovery_bootstrap:
        _preflight_existing_envelopes(
            data_root=data_root,
            candidate_master_key=candidate_master_key,
        )
    material = PersistentBlueWaySecrets(
        key_id=f"bwa_{secrets.token_hex(16)}",
        master_key=candidate_master_key,
        api_secret=candidate_api_secret,
    )
    authority.create(material)
    return material
