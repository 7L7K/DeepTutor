"""Dedicated provider binding for Course-owned Flashcard generation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from deeptutor.multi_user.paths import get_admin_path_service
from deeptutor.services.file_io import atomic_write_json

from .provider_credentials import (
    ProviderCredentialAuthority,
    ProviderCredentialError,
)


class FlashcardProviderConfigError(RuntimeError):
    """The dedicated Flashcard provider configuration is invalid."""


@dataclass(frozen=True)
class FlashcardProviderConfig:
    enabled: bool = False
    provider: str = "openai"
    model: str = "gpt-5-mini"
    base_url: str = "https://api.openai.com/v1"
    credential_ref: str | None = None
    api_key: str = ""


class FlashcardProviderConfigService:
    """Admin-only configuration that cannot alter the Chat model catalog."""

    _VERSION = 1
    _PROVIDER = "openai"
    _MODEL = "gpt-5-mini"
    _BASE_URL = "https://api.openai.com/v1"

    def __init__(
        self,
        path: Path,
        *,
        credential_authority: ProviderCredentialAuthority | None = None,
    ) -> None:
        self.path = Path(path)
        self.credential_authority = credential_authority or ProviderCredentialAuthority(
            self.path.parent / "provider_credentials"
        )

    @classmethod
    def default(cls) -> FlashcardProviderConfig:
        return FlashcardProviderConfig()

    def _read_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FlashcardProviderConfigError(
                "Flashcard provider configuration is malformed"
            ) from exc
        if not isinstance(payload, dict):
            raise FlashcardProviderConfigError(
                "Flashcard provider configuration is malformed"
            )
        return payload

    def load(self) -> FlashcardProviderConfig:
        payload = self._read_payload()
        if not payload:
            return self.default()
        if (
            set(payload)
            != {
                "version",
                "enabled",
                "provider",
                "model",
                "base_url",
                "credential_ref",
            }
            or payload.get("version") != self._VERSION
            or payload.get("provider") != self._PROVIDER
            or payload.get("model") != self._MODEL
            or payload.get("base_url") != self._BASE_URL
            or not isinstance(payload.get("enabled"), bool)
            or (
                payload.get("credential_ref") is not None
                and not isinstance(payload.get("credential_ref"), str)
            )
        ):
            raise FlashcardProviderConfigError(
                "Flashcard provider configuration is malformed"
            )
        reference = payload.get("credential_ref")
        api_key = ""
        if reference:
            try:
                api_key = self.credential_authority.read(str(reference))
            except ProviderCredentialError as exc:
                raise FlashcardProviderConfigError(
                    "Flashcard provider credential is unavailable"
                ) from exc
        if payload["enabled"] and not api_key:
            raise FlashcardProviderConfigError(
                "Flashcard provider credential is required"
            )
        return FlashcardProviderConfig(
            enabled=bool(payload["enabled"]),
            provider=self._PROVIDER,
            model=self._MODEL,
            base_url=self._BASE_URL,
            credential_ref=str(reference) if reference else None,
            api_key=api_key,
        )

    def configure(
        self, *, enabled: bool, api_key: str | None = None
    ) -> FlashcardProviderConfig:
        current = self.load()
        reference = current.credential_ref
        provided = (api_key or "").strip()
        if provided:
            try:
                reference = self.credential_authority.write(
                    provided,
                    credential_ref=reference,
                )
            except ProviderCredentialError as exc:
                raise FlashcardProviderConfigError(
                    "Flashcard provider credential could not be stored"
                ) from exc
        if enabled and not reference:
            raise FlashcardProviderConfigError(
                "Flashcard provider credential is required"
            )
        payload = {
            "version": self._VERSION,
            "enabled": bool(enabled),
            "provider": self._PROVIDER,
            "model": self._MODEL,
            "base_url": self._BASE_URL,
            "credential_ref": reference,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        atomic_write_json(self.path, payload)
        return self.load()

    def load_public(self) -> dict[str, Any]:
        config = self.load()
        public = asdict(config)
        public.pop("credential_ref", None)
        public.pop("api_key", None)
        public["credential_configured"] = bool(config.api_key)
        return public


def get_flashcard_provider_config_service() -> FlashcardProviderConfigService:
    settings = get_admin_path_service().get_settings_dir()
    return FlashcardProviderConfigService(settings / "flashcard_provider.json")


__all__ = [
    "FlashcardProviderConfig",
    "FlashcardProviderConfigError",
    "FlashcardProviderConfigService",
    "get_flashcard_provider_config_service",
]
