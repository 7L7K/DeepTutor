"""Encrypted, owner-scoped persistence for short-lived BlueWay pairing attempts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class PairingStoreError(RuntimeError):
    """The pairing record could not be safely read or written."""


class PairingAttemptStore:
    """Keep pairing metadata and provider secrets encrypted at rest.

    The Course database never receives the device code or PKCE verifier. Each
    attempt is independently authenticated to the owner and attempt id, and
    writes use a private directory plus an atomic replace.
    """

    _VERSION = b"BWP1"
    _KEY_VERSION = 1
    _ATTEMPT_ID = re.compile(r"^bwa_[a-f0-9]{32}$")

    def __init__(self, root: Path, master_key: bytes) -> None:
        if len(master_key) != 32:
            raise PairingStoreError("Pairing encryption requires a 32-byte master key")
        self.root = Path(root)
        self._key = master_key

    @staticmethod
    def _aad(owner_user_id: str, attempt_id: str) -> bytes:
        return f"{owner_user_id}|blueway-pairing|{attempt_id}".encode("utf-8")

    def _path(self, attempt_id: str) -> Path:
        if not self._ATTEMPT_ID.fullmatch(attempt_id):
            raise PairingStoreError("Invalid pairing attempt id")
        return self.root / f"{attempt_id}.enc"

    def _secure_root(self) -> None:
        if self.root.exists() and self.root.is_symlink():
            raise PairingStoreError("Pairing directory cannot be a symbolic link")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.root.lstat()
        expected_uid = os.geteuid() if hasattr(os, "geteuid") else None
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or (expected_uid is not None and info.st_uid != expected_uid)
            or info.st_mode & 0o077
        ):
            raise PairingStoreError("Pairing directory fails private-directory checks")
        self.root.chmod(0o700)

    def _read_bytes(self, path: Path) -> bytes:
        self._secure_root()
        flags = os.O_RDONLY | (os.O_NOFOLLOW if hasattr(os, "O_NOFOLLOW") else 0)
        try:
            fd = os.open(path, flags)
        except OSError as exc:
            raise PairingStoreError("Pairing record cannot be read") from exc
        try:
            info = os.fstat(fd)
            expected_uid = os.geteuid() if hasattr(os, "geteuid") else None
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (expected_uid is not None and info.st_uid != expected_uid)
                or info.st_mode & 0o077
            ):
                raise PairingStoreError("Pairing record fails private-file checks")
            with os.fdopen(fd, "rb") as handle:
                fd = -1
                return handle.read()
        except Exception:
            if fd >= 0:
                os.close(fd)
            raise

    def _encode(self, *, owner_user_id: str, attempt_id: str, record: dict[str, Any]) -> bytes:
        plaintext = json.dumps(record, separators=(",", ":"), sort_keys=True).encode("utf-8")
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._key).encrypt(nonce, plaintext, self._aad(owner_user_id, attempt_id))
        return self._VERSION + bytes((self._KEY_VERSION,)) + nonce + ciphertext

    def _decode(self, *, owner_user_id: str, attempt_id: str, data: bytes) -> dict[str, Any]:
        minimum = len(self._VERSION) + 1 + 12 + 16
        if (
            len(data) < minimum
            or not data.startswith(self._VERSION)
            or data[len(self._VERSION)] != self._KEY_VERSION
        ):
            raise PairingStoreError("Pairing record payload is invalid")
        offset = len(self._VERSION) + 1
        try:
            plaintext = AESGCM(self._key).decrypt(
                data[offset : offset + 12],
                data[offset + 12 :],
                self._aad(owner_user_id, attempt_id),
            )
            value = json.loads(plaintext)
        except (InvalidTag, ValueError, json.JSONDecodeError) as exc:
            raise PairingStoreError("Pairing record cannot be decrypted") from exc
        if not isinstance(value, dict):
            raise PairingStoreError("Pairing record shape is invalid")
        return value

    def write(self, *, owner_user_id: str, attempt_id: str, record: dict[str, Any]) -> None:
        self._secure_root()
        target = self._path(attempt_id)
        temporary = self.root / f".{attempt_id}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(self._encode(owner_user_id=owner_user_id, attempt_id=attempt_id, record=record))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            target.chmod(0o600)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            if fd >= 0:
                os.close(fd)
            temporary.unlink(missing_ok=True)
            raise

    def read(self, *, owner_user_id: str, attempt_id: str) -> dict[str, Any]:
        return self._decode(
            owner_user_id=owner_user_id,
            attempt_id=attempt_id,
            data=self._read_bytes(self._path(attempt_id)),
        )

    def list(self, *, owner_user_id: str) -> list[tuple[str, dict[str, Any]]]:
        self._secure_root()
        records: list[tuple[str, dict[str, Any]]] = []
        for path in self.root.glob("bwa_*.enc"):
            attempt_id = path.stem
            if not self._ATTEMPT_ID.fullmatch(attempt_id):
                continue
            records.append((attempt_id, self.read(owner_user_id=owner_user_id, attempt_id=attempt_id)))
        return records

    def remove(self, attempt_id: str) -> None:
        path = self._path(attempt_id)
        self._secure_root()
        try:
            path.unlink()
        except FileNotFoundError:
            return
        directory_fd = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def clear(self) -> None:
        """Remove only this owner's short-lived pairing artifacts.

        Recovery uses this barrier when its master key has changed and the old
        encrypted pairing records cannot be decrypted. Those records cannot be
        resumed or cancelled locally; the provider expiry remains authoritative.
        """
        self._secure_root()
        removed = False
        for path in self.root.glob("bwa_*.enc"):
            if self._ATTEMPT_ID.fullmatch(path.stem):
                path.unlink()
                removed = True
        if removed:
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
