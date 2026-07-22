"""AES-GCM credential storage outside the Course database."""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import stat

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialError(RuntimeError):
    pass


class CredentialStore:
    _VERSION = b"BW2"
    _KEY_VERSION = 1

    def __init__(self, root: Path, master_key: bytes) -> None:
        if len(master_key) != 32:
            raise CredentialError("AES-256-GCM requires a 32-byte master key")
        self.root = Path(root)
        self._key = master_key

    @staticmethod
    def _aad(owner_user_id: str, connection_id: str, scope_version: str) -> bytes:
        return "|".join((owner_user_id, connection_id, "blueway", scope_version)).encode("utf-8")

    def _path(self, connection_id: str) -> Path:
        if not connection_id or "/" in connection_id or "\\" in connection_id:
            raise CredentialError("Invalid integration connection id")
        return self.root / f"{connection_id}.enc"

    def _rotation_path(self, connection_id: str) -> Path:
        if not connection_id or "/" in connection_id or "\\" in connection_id:
            raise CredentialError("Invalid integration connection id")
        return self.root / f"{connection_id}.rotation.enc"

    def _secure_root(self) -> None:
        if self.root.exists() and self.root.is_symlink():
            raise CredentialError("Credential directory cannot be a symbolic link")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            info = self.root.lstat()
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise CredentialError("Credential path must be a real directory")
            expected_uid = os.geteuid() if hasattr(os, "geteuid") else None
            if expected_uid is not None and info.st_uid != expected_uid:
                raise CredentialError("Credential directory belongs to another OS account")
            self.root.chmod(0o700)
        except OSError as exc:
            raise CredentialError("Could not enforce credential directory permissions") from exc

    def _read_target(self, target: Path) -> bytes:
        self._secure_root()
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(target, flags)
        except OSError as exc:
            raise CredentialError("Credential cannot be decrypted") from exc
        try:
            info = os.fstat(fd)
            expected_uid = os.geteuid() if hasattr(os, "geteuid") else None
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (expected_uid is not None and info.st_uid != expected_uid)
                or info.st_mode & 0o077
            ):
                raise CredentialError("Credential file fails private-file checks")
            with os.fdopen(fd, "rb") as handle:
                return handle.read()
        except Exception:
            os.close(fd)
            raise

    def _payload(self, nonce: bytes, ciphertext: bytes) -> bytes:
        return self._VERSION + bytes((self._KEY_VERSION,)) + nonce + ciphertext

    def _decrypt(self, data: bytes, *, owner_user_id: str, connection_id: str, scope_version: str) -> bytes:
        minimum = len(self._VERSION) + 1 + 12 + 16
        if len(data) < minimum or not data.startswith(self._VERSION) or data[len(self._VERSION)] != self._KEY_VERSION:
            raise CredentialError("Credential payload is invalid")
        offset = len(self._VERSION) + 1
        return AESGCM(self._key).decrypt(data[offset:offset + 12], data[offset + 12:], self._aad(owner_user_id, connection_id, scope_version))

    def _fsync_root(self) -> None:
        try:
            fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError as exc:
            raise CredentialError("Could not durably replace credential") from exc

    def write(self, *, owner_user_id: str, connection_id: str, scope_version: str, refresh_token: str) -> None:
        if not refresh_token:
            raise CredentialError("Refresh credential is required")
        self._secure_root()
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._key).encrypt(
            nonce, refresh_token.encode("utf-8"), self._aad(owner_user_id, connection_id, scope_version)
        )
        target = self._path(connection_id)
        temporary = self.root / f".{connection_id}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(self._payload(nonce, ciphertext))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            self._fsync_root()
            target.chmod(0o600)
            info = target.lstat()
            expected_uid = os.geteuid() if hasattr(os, "geteuid") else None
            if (
                stat.S_ISLNK(info.st_mode)
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (expected_uid is not None and info.st_uid != expected_uid)
                or info.st_mode & 0o077
            ):
                raise CredentialError("Credential file fails private-file checks")
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def read(self, *, owner_user_id: str, connection_id: str, scope_version: str) -> str:
        path = self._path(connection_id)
        try:
            data = self._read_target(path)
            plaintext = self._decrypt(data, owner_user_id=owner_user_id, connection_id=connection_id, scope_version=scope_version)
        except (OSError, InvalidTag, ValueError) as exc:
            raise CredentialError("Credential cannot be decrypted") from exc
        return plaintext.decode("utf-8")

    def write_rotation_envelope(
        self, *, owner_user_id: str, connection_id: str, scope_version: str,
        refresh_token: str, rotation_request_id: str,
    ) -> None:
        """Retain the pre-rotation token until the durable receipt is cleared.

        A crash after writing the successor credential must retry the same
        request with the predecessor token, never with a successor paired to
        the predecessor receipt.  This encrypted sidecar contains no browser
        reachable data and is removed only after the repository clears the
        matching rotation receipt.
        """
        self._write_path(
            self._rotation_path(connection_id),
            owner_user_id=owner_user_id,
            connection_id=connection_id,
            scope_version=f"{scope_version}:rotation",
            refresh_token=json.dumps(
                {"refresh_token": refresh_token, "rotation_request_id": rotation_request_id},
                separators=(",", ":"), sort_keys=True,
            ),
        )

    def read_rotation_envelope(
        self, *, owner_user_id: str, connection_id: str, scope_version: str,
        expected_rotation_request_id: str,
    ) -> str | None:
        path = self._rotation_path(connection_id)
        if not path.exists():
            return None
        try:
            data = self._read_target(path)
            plaintext = self._decrypt(data, owner_user_id=owner_user_id, connection_id=connection_id, scope_version=f"{scope_version}:rotation")
        except (OSError, InvalidTag, ValueError) as exc:
            raise CredentialError("Credential cannot be decrypted") from exc
        try:
            payload = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CredentialError("Rotation envelope is invalid") from exc
        if not isinstance(payload, dict) or set(payload) != {"refresh_token", "rotation_request_id"}:
            raise CredentialError("Rotation envelope is invalid")
        token, request_id = payload["refresh_token"], payload["rotation_request_id"]
        if not isinstance(token, str) or not token or not isinstance(request_id, str) or not request_id:
            raise CredentialError("Rotation envelope is invalid")
        if request_id != expected_rotation_request_id:
            # The database receipt was already cleared before a crash.  The
            # primary credential is the successor now; never pair the old
            # predecessor with a newly minted request id.
            self.clear_rotation_envelope(connection_id)
            return None
        return token

    def _write_path(
        self, target: Path, *, owner_user_id: str, connection_id: str,
        scope_version: str, refresh_token: str,
    ) -> None:
        if not refresh_token:
            raise CredentialError("Refresh credential is required")
        self._secure_root()
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._key).encrypt(
            nonce, refresh_token.encode("utf-8"), self._aad(owner_user_id, connection_id, scope_version)
        )
        temporary = self.root / f".{target.name}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(self._payload(nonce, ciphertext))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            self._fsync_root()
            target.chmod(0o600)
            info = target.lstat()
            expected_uid = os.geteuid() if hasattr(os, "geteuid") else None
            if (
                stat.S_ISLNK(info.st_mode)
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (expected_uid is not None and info.st_uid != expected_uid)
                or info.st_mode & 0o077
            ):
                raise CredentialError("Credential file fails private-file checks")
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def remove(self, connection_id: str) -> None:
        targets = (self._path(connection_id), self._rotation_path(connection_id))
        if any(path.exists() for path in targets):
            for path in targets:
                path.unlink(missing_ok=True)
            self._fsync_root()

    def clear_rotation_envelope(self, connection_id: str) -> None:
        path = self._rotation_path(connection_id)
        if path.exists():
            path.unlink()
            self._fsync_root()

    def connection_ids(self) -> set[str]:
        """List only safely shaped primary credential files for reconciliation."""
        self._secure_root()
        ids: set[str] = set()
        for path in self.root.glob("*.enc"):
            if path.name.endswith(".rotation.enc"):
                continue
            connection_id = path.name.removesuffix(".enc")
            if self._path(connection_id) != path or path.is_symlink():
                continue
            try:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
                    continue
            except OSError:
                continue
            ids.add(connection_id)
        return ids
