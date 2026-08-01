"""Encrypted server-only credential storage for configured model providers.

The public model catalog may describe provider profiles, but raw credentials
are stored separately as AES-256-GCM envelopes.  The opaque credential
reference is safe to persist in settings; it is never returned to browsers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import stat

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ProviderCredentialError(RuntimeError):
    """Provider credential material is missing, malformed, or unsafe."""


_REFERENCE_PATTERN = re.compile(r"^pcr_[A-Za-z0-9_-]{32}$")


class ProviderCredentialAuthority:
    """Strict private-file authority for encrypted provider credentials."""

    _ENVELOPE_VERSION = b"PCR2"
    _KEY_VERSION = 1
    _LEGACY_SCHEMA_VERSION = 1

    def __init__(self, root: Path, *, key_path: Path | None = None) -> None:
        self.root = Path(root)
        self.key_path = Path(key_path or (self.root.parent / "provider_credentials.key"))

    @staticmethod
    def _expected_uid() -> int | None:
        return os.geteuid() if hasattr(os, "geteuid") else None

    @staticmethod
    def _validate_reference(credential_ref: str) -> str:
        if not _REFERENCE_PATTERN.fullmatch(credential_ref):
            raise ProviderCredentialError("Provider credential reference is invalid")
        return credential_ref

    def _credential_path(self, credential_ref: str) -> Path:
        reference = self._validate_reference(credential_ref)
        return self.root / f"{reference}.enc"

    def _legacy_path(self, credential_ref: str) -> Path:
        reference = self._validate_reference(credential_ref)
        return self.root / f"{reference}.json"

    def _validate_directory(self, path: Path, *, create: bool) -> None:
        if path.exists() and path.is_symlink():
            raise ProviderCredentialError(
                "Provider credential directory cannot be a symbolic link"
            )
        if create:
            try:
                path.mkdir(parents=True, exist_ok=True, mode=0o700)
                path.chmod(0o700)
            except OSError as exc:
                raise ProviderCredentialError(
                    "Could not create provider credential directory"
                ) from exc
        try:
            info = path.lstat()
        except OSError as exc:
            raise ProviderCredentialError(
                "Provider credential directory is unavailable"
            ) from exc
        expected_uid = self._expected_uid()
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or (expected_uid is not None and info.st_uid != expected_uid)
            or info.st_mode & 0o077
        ):
            raise ProviderCredentialError(
                "Provider credential directory fails private-directory checks"
            )

    def _validate_root(self, *, create: bool) -> None:
        self._validate_directory(self.root, create=create)

    def _read_private_bytes(self, path: Path) -> bytes:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ProviderCredentialError(
                "Provider credential is unavailable"
            ) from exc
        try:
            info = os.fstat(descriptor)
            expected_uid = self._expected_uid()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (expected_uid is not None and info.st_uid != expected_uid)
                or info.st_mode & 0o077
            ):
                raise ProviderCredentialError(
                    "Provider credential fails private-file checks"
                )
            with os.fdopen(descriptor, "rb") as handle:
                return handle.read()
        except ProviderCredentialError:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        except OSError as exc:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise ProviderCredentialError(
                "Provider credential is unavailable"
            ) from exc

    def _write_private_bytes(
        self, target: Path, payload: bytes, *, replace: bool
    ) -> None:
        parent = target.parent
        self._validate_directory(parent, create=True)
        if target.exists() and not replace:
            raise ProviderCredentialError(
                "Provider credential key already exists"
            )
        if target.is_symlink():
            raise ProviderCredentialError(
                "Provider credential target cannot be a symbolic link"
            )
        temporary = parent / f".{target.name}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(temporary, flags, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if replace:
                os.replace(temporary, target)
            else:
                try:
                    os.link(temporary, target)
                except FileExistsError as exc:
                    raise ProviderCredentialError(
                        "Provider credential key already exists"
                    ) from exc
                temporary.unlink()
            target.chmod(0o600)
            directory_descriptor = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _load_key(self, *, create: bool) -> bytes:
        key_parent = self.key_path.parent
        self._validate_directory(key_parent, create=create)
        if not self.key_path.exists():
            if not create:
                raise ProviderCredentialError(
                    "Provider credential key is unavailable"
                )
            candidate = secrets.token_bytes(32)
            try:
                self._write_private_bytes(
                    self.key_path, candidate, replace=False
                )
                key = candidate
            except ProviderCredentialError as exc:
                if "already exists" not in str(exc):
                    raise
                key = self._read_private_bytes(self.key_path)
        else:
            key = self._read_private_bytes(self.key_path)
        if len(key) != 32:
            raise ProviderCredentialError(
                "Provider credential key is malformed"
            )
        return key

    @classmethod
    def _aad(cls, credential_ref: str) -> bytes:
        return f"deeptutor|provider|{credential_ref}|v2".encode("utf-8")

    def _read_encrypted(self, credential_ref: str) -> str:
        self._validate_root(create=False)
        payload = self._read_private_bytes(self._credential_path(credential_ref))
        minimum = len(self._ENVELOPE_VERSION) + 1 + 12 + 16
        if (
            len(payload) < minimum
            or not payload.startswith(self._ENVELOPE_VERSION)
            or payload[len(self._ENVELOPE_VERSION)] != self._KEY_VERSION
        ):
            raise ProviderCredentialError("Provider credential is malformed")
        offset = len(self._ENVELOPE_VERSION) + 1
        try:
            plaintext = AESGCM(self._load_key(create=False)).decrypt(
                payload[offset : offset + 12],
                payload[offset + 12 :],
                self._aad(credential_ref),
            )
            secret = plaintext.decode("utf-8")
        except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
            raise ProviderCredentialError(
                "Provider credential cannot be decrypted"
            ) from exc
        if not secret:
            raise ProviderCredentialError("Provider credential is malformed")
        return secret

    def _read_legacy(self, credential_ref: str) -> str:
        self._validate_root(create=False)
        raw = self._read_private_bytes(self._legacy_path(credential_ref))
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderCredentialError(
                "Provider credential is malformed"
            ) from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema_version", "credential_ref", "secret"}
            or payload.get("schema_version") != self._LEGACY_SCHEMA_VERSION
            or payload.get("credential_ref") != credential_ref
            or not isinstance(payload.get("secret"), str)
            or not payload["secret"]
        ):
            raise ProviderCredentialError("Provider credential is malformed")
        return str(payload["secret"])

    def exists(self, credential_ref: str) -> bool:
        try:
            self.read(credential_ref)
        except ProviderCredentialError:
            return False
        return True

    def read(self, credential_ref: str) -> str:
        reference = self._validate_reference(credential_ref)
        encrypted = self._credential_path(reference)
        if encrypted.exists():
            secret = self._read_encrypted(reference)
            legacy = self._legacy_path(reference)
            if legacy.exists():
                legacy_secret = self._read_legacy(reference)
                if not secrets.compare_digest(secret, legacy_secret):
                    raise ProviderCredentialError(
                        "Provider credential migration is inconsistent"
                    )
                try:
                    legacy.unlink()
                    directory_descriptor = os.open(self.root, os.O_RDONLY)
                    try:
                        os.fsync(directory_descriptor)
                    finally:
                        os.close(directory_descriptor)
                except OSError as exc:
                    raise ProviderCredentialError(
                        "Provider credential migration could not finish"
                    ) from exc
            elif legacy.is_symlink():
                raise ProviderCredentialError(
                    "Provider credential target cannot be a symbolic link"
                )
            return secret
        legacy = self._legacy_path(reference)
        if not legacy.exists():
            raise ProviderCredentialError("Provider credential is unavailable")
        secret = self._read_legacy(reference)
        self.write(secret, credential_ref=reference)
        return self._read_encrypted(reference)

    def write(self, secret: str, *, credential_ref: str | None = None) -> str:
        normalized_secret = secret.strip()
        if not normalized_secret or len(normalized_secret) > 16384:
            raise ProviderCredentialError("Provider credential value is invalid")
        reference = credential_ref or f"pcr_{secrets.token_urlsafe(24)}"
        self._validate_reference(reference)
        self._validate_root(create=True)
        target = self._credential_path(reference)
        legacy = self._legacy_path(reference)
        if target.exists():
            # Refuse to replace an unsafe existing object.
            self._read_encrypted(reference)
        elif target.is_symlink():
            raise ProviderCredentialError(
                "Provider credential target cannot be a symbolic link"
            )
        if legacy.exists():
            self._read_legacy(reference)
        elif legacy.is_symlink():
            raise ProviderCredentialError(
                "Provider credential target cannot be a symbolic link"
            )
        key = self._load_key(create=True)
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(key).encrypt(
            nonce,
            normalized_secret.encode("utf-8"),
            self._aad(reference),
        )
        payload = (
            self._ENVELOPE_VERSION
            + bytes((self._KEY_VERSION,))
            + nonce
            + ciphertext
        )
        self._write_private_bytes(target, payload, replace=True)
        if self._read_encrypted(reference) != normalized_secret:
            raise ProviderCredentialError(
                "Provider credential verification failed"
            )
        if legacy.exists():
            legacy.unlink()
            directory_descriptor = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        return reference


__all__ = ["ProviderCredentialAuthority", "ProviderCredentialError"]
