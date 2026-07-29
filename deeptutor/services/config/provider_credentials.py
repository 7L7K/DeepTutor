"""Server-only credential storage for configured model providers.

The public model catalog may describe provider profiles, but raw credentials
are stored separately under a strict private-file authority.  The opaque
credential reference is safe to persist in the catalog; it is never returned
to browser clients.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import stat


class ProviderCredentialError(RuntimeError):
    """Provider credential material is missing, malformed, or unsafe."""


_REFERENCE_PATTERN = re.compile(r"^pcr_[A-Za-z0-9_-]{32}$")


class ProviderCredentialAuthority:
    """Strict POSIX private-file authority for provider API credentials."""

    _SCHEMA_VERSION = 1

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

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
        return self.root / f"{reference}.json"

    def _validate_root(self, *, create: bool) -> None:
        if self.root.exists() and self.root.is_symlink():
            raise ProviderCredentialError(
                "Provider credential directory cannot be a symbolic link"
            )
        if create:
            try:
                self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
                self.root.chmod(0o700)
            except OSError as exc:
                raise ProviderCredentialError(
                    "Could not create provider credential directory"
                ) from exc
        try:
            info = self.root.lstat()
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

    def _read_payload(self, credential_ref: str) -> dict[str, object]:
        self._validate_root(create=False)
        path = self._credential_path(credential_ref)
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
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except ProviderCredentialError:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise ProviderCredentialError(
                "Provider credential is malformed"
            ) from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema_version", "credential_ref", "secret"}
            or payload.get("schema_version") != self._SCHEMA_VERSION
            or payload.get("credential_ref") != credential_ref
            or not isinstance(payload.get("secret"), str)
            or not payload["secret"]
        ):
            raise ProviderCredentialError("Provider credential is malformed")
        return payload

    def exists(self, credential_ref: str) -> bool:
        try:
            self._read_payload(credential_ref)
        except ProviderCredentialError:
            return False
        return True

    def read(self, credential_ref: str) -> str:
        return str(self._read_payload(credential_ref)["secret"])

    def write(self, secret: str, *, credential_ref: str | None = None) -> str:
        normalized_secret = secret.strip()
        if not normalized_secret or len(normalized_secret) > 16384:
            raise ProviderCredentialError("Provider credential value is invalid")
        reference = credential_ref or f"pcr_{secrets.token_urlsafe(24)}"
        self._validate_reference(reference)
        self._validate_root(create=True)
        target = self._credential_path(reference)
        if target.exists():
            # Refuse to replace an unsafe existing object.
            self._read_payload(reference)
        elif target.is_symlink():
            raise ProviderCredentialError(
                "Provider credential target cannot be a symbolic link"
            )
        payload = json.dumps(
            {
                "schema_version": self._SCHEMA_VERSION,
                "credential_ref": reference,
                "secret": normalized_secret,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        temporary = self.root / f".{reference}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(temporary, flags, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            target.chmod(0o600)
            directory_descriptor = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
            if self.read(reference) != normalized_secret:
                raise ProviderCredentialError(
                    "Provider credential verification failed"
                )
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return reference


__all__ = ["ProviderCredentialAuthority", "ProviderCredentialError"]
