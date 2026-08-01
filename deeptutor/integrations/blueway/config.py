"""Fail-closed runtime configuration for the BlueWay integration."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import os
from urllib.parse import urlparse

from deeptutor.services import auth as auth_service
from deeptutor.services.pocketbase_client import is_pocketbase_enabled

from .credential_authority import (
    CredentialAuthorityError,
    resolve_persistent_blueway_secrets,
)


class IntegrationConfigurationError(RuntimeError):
    """The optional integration was requested without a safe local setup."""


class IntegrationSecretUnavailableError(IntegrationConfigurationError):
    """BlueWay is safely degraded while the rest of TEEECHR remains usable."""


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class BlueWaySettings:
    enabled: bool
    base_url: str = ""
    client_id: str = ""
    api_secret: str = ""
    approval_url: str = ""
    master_key: bytes = b""
    secret_key_id: str = ""

    @classmethod
    def from_environment(cls) -> "BlueWaySettings":
        enabled = _enabled(os.environ.get("TEEECHR_BLUEWAY_INTEGRATION_ENABLED"))
        if not enabled:
            return cls(enabled=False)
        base_url = str(os.environ.get("TEEECHR_BLUEWAY_BASE_URL") or "").strip().rstrip("/")
        client_id = str(os.environ.get("TEEECHR_BLUEWAY_CLIENT_ID") or "").strip()
        api_secret = str(os.environ.get("TEEECHR_BLUEWAY_API_SECRET") or "").strip()
        approval_url = str(os.environ.get("TEEECHR_BLUEWAY_APPROVAL_URL") or "").strip().rstrip("/")
        raw_key = str(os.environ.get("TEEECHR_INTEGRATION_MASTER_KEY") or "").strip()
        if not auth_service.AUTH_ENABLED:
            raise IntegrationConfigurationError("BlueWay integration requires TEEECHR authentication")
        if is_pocketbase_enabled():
            raise IntegrationConfigurationError(
                "BlueWay integration requires the supported local JSON/SQLite multi-user backend"
            )
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise IntegrationConfigurationError("BlueWay base URL must be a pinned HTTPS origin")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise IntegrationConfigurationError("BlueWay base URL must be an origin without a path")
        if not client_id or len(client_id) > 160:
            raise IntegrationConfigurationError("BlueWay client ID is required")
        approval = urlparse(approval_url)
        if approval.scheme != "https" or not approval.netloc or approval.username or approval.password or not approval.path or approval.query or approval.fragment:
            raise IntegrationConfigurationError("BlueWay approval URL must be a pinned HTTPS path")
        key: bytes | None = None
        if raw_key:
            try:
                key = base64.b64decode(raw_key, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise IntegrationConfigurationError(
                    "Integration master key must be base64 AES-256 material"
                ) from exc
            if len(key) != 32:
                raise IntegrationConfigurationError(
                    "Integration master key must be exactly 32 bytes"
                )
        candidate_api_secret = api_secret or None
        if candidate_api_secret is not None and not (
            32 <= len(candidate_api_secret) <= 1024
        ):
            raise IntegrationConfigurationError(
                "BlueWay server API secret is invalid"
            )
        from deeptutor.multi_user.paths import SYSTEM_ROOT

        try:
            material = resolve_persistent_blueway_secrets(
                authority_path=(
                    SYSTEM_ROOT
                    / "integrations"
                    / "blueway-secret-authority.json"
                ),
                data_root=SYSTEM_ROOT.parent,
                candidate_master_key=key,
                candidate_api_secret=candidate_api_secret,
                allow_bootstrap=_enabled(
                    os.environ.get(
                        "TEEECHR_INTEGRATION_SECRET_BOOTSTRAP"
                    )
                ),
                allow_recovery_bootstrap=_enabled(
                    os.environ.get(
                        "TEEECHR_INTEGRATION_SECRET_RECOVERY_BOOTSTRAP"
                    )
                ),
            )
        except CredentialAuthorityError as exc:
            raise IntegrationSecretUnavailableError(
                "BlueWay persistent secret authority is unavailable"
            ) from exc
        return cls(
            enabled=True,
            base_url=base_url,
            client_id=client_id,
            api_secret=material.api_secret,
            approval_url=approval_url,
            master_key=material.master_key,
            secret_key_id=material.key_id,
        )
