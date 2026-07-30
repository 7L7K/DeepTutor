from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from deeptutor.services.path_service import get_path_service

from .embedding_endpoint import normalize_embedding_endpoint_for_display
from .provider_credentials import (
    ProviderCredentialAuthority,
    ProviderCredentialError,
)

# Legacy fallback only — frozen at admin scope at import time. Production code
# enters through ``get_model_catalog_service()``, which resolves the explicit
# deployment-owned admin path on every call.
CATALOG_PATH = get_path_service().get_settings_file("model_catalog")


def _service_shell() -> dict[str, Any]:
    return {
        "active_profile_id": None,
        "active_model_id": None,
        "profiles": [],
    }


def _search_shell() -> dict[str, Any]:
    return {
        "active_profile_id": None,
        "profiles": [],
    }


def _default_catalog() -> dict[str, Any]:
    return {
        "version": 1,
        "services": {
            "llm": _service_shell(),
            "embedding": _service_shell(),
            "search": _search_shell(),
            "tts": _service_shell(),
            "stt": _service_shell(),
            "imagegen": _service_shell(),
            "videogen": _service_shell(),
        },
    }


class ModelCatalogService:
    _instances: dict[str, "ModelCatalogService"] = {}

    def __init__(
        self,
        path: Path | None = None,
        credential_authority: ProviderCredentialAuthority | None = None,
    ):
        self.path = path or CATALOG_PATH
        self.credential_authority = credential_authority or ProviderCredentialAuthority(
            self.path.parent / "provider_credentials"
        )

    @classmethod
    def get_instance(cls, path: Path | None = None) -> "ModelCatalogService":
        resolved = (path or get_path_service().get_settings_file("model_catalog")).resolve()
        key = str(resolved)
        if key not in cls._instances:
            cls._instances[key] = cls(resolved)
        return cls._instances[key]

    def load(self) -> dict[str, Any]:
        loaded = self._read_existing_catalog()
        if loaded:
            catalog = _default_catalog()
            catalog.update({k: v for k, v in loaded.items() if k != "services"})
            catalog["services"].update(loaded.get("services", {}))
            merged_defaults = catalog != loaded
            before = deepcopy(catalog)
            self._normalize(catalog)
            has_legacy_credentials = self._contains_raw_credentials(catalog)
            if merged_defaults or catalog != before or has_legacy_credentials:
                return self.save(catalog)
            return self._hydrate_credentials(catalog)

        catalog = _default_catalog()
        self._normalize(catalog)
        self.save(catalog)
        return self._hydrate_credentials(catalog)

    def load_public(self) -> dict[str, Any]:
        """Return browser-safe catalog metadata with no secret references."""
        catalog = self.load()
        for service in catalog.get("services", {}).values():
            for profile in service.get("profiles", []):
                profile.pop("credential_ref", None)
                profile["api_key_set"] = bool(profile.get("api_key"))
                profile["api_key"] = ""
        return catalog

    def _read_existing_catalog(self) -> dict[str, Any]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def save(self, catalog: dict[str, Any]) -> dict[str, Any]:
        normalized = deepcopy(catalog)
        self._normalize(normalized)
        existing = self._read_existing_catalog()
        existing_references = self._credential_references_by_profile(existing)
        self._externalize_credentials(normalized, existing_references)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.parent / f".{self.path.name}.{uuid4().hex}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(normalized, handle, indent=2, ensure_ascii=False)
                handle.flush()
                try:
                    import os

                    os.fsync(handle.fileno())
                except OSError:
                    pass
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return self._hydrate_credentials(normalized)

    def apply(self, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self.save(catalog or self.load())
        return {"catalog_path": str(self.path), "services": list(current.get("services", {}))}

    @staticmethod
    def _contains_raw_credentials(catalog: dict[str, Any]) -> bool:
        return any(
            bool(str(profile.get("api_key") or "").strip())
            for service in catalog.get("services", {}).values()
            for profile in service.get("profiles", [])
        )

    @staticmethod
    def _credential_references_by_profile(
        catalog: dict[str, Any],
    ) -> dict[tuple[str, str], str]:
        references: dict[tuple[str, str], str] = {}
        for service_name, service in catalog.get("services", {}).items():
            for profile in service.get("profiles", []):
                profile_id = str(profile.get("id") or "")
                reference = str(profile.get("credential_ref") or "")
                if profile_id and reference:
                    references[(service_name, profile_id)] = reference
        return references

    def _externalize_credentials(
        self,
        catalog: dict[str, Any],
        existing_references: dict[tuple[str, str], str],
    ) -> None:
        for service_name, service in catalog.get("services", {}).items():
            for profile in service.get("profiles", []):
                profile_id = str(profile.get("id") or "")
                provided = str(profile.pop("api_key", "") or "").strip()
                # Credential references are server authority. Never honor a
                # reference supplied through a browser catalog payload; only
                # the already-persisted reference for this exact profile may
                # be reused or replaced.
                reference = (
                    existing_references.get((service_name, profile_id), "")
                    if profile_id
                    else ""
                )
                if provided:
                    reference = self.credential_authority.write(
                        provided,
                        credential_ref=reference or None,
                    )
                configured = False
                if reference:
                    configured = self.credential_authority.exists(reference)
                    if not configured:
                        raise ProviderCredentialError(
                            "Configured provider credential is unavailable"
                        )
                    profile["credential_ref"] = reference
                else:
                    profile.pop("credential_ref", None)
                profile["api_key_set"] = configured

    def _hydrate_credentials(self, catalog: dict[str, Any]) -> dict[str, Any]:
        hydrated = deepcopy(catalog)
        for service in hydrated.get("services", {}).values():
            for profile in service.get("profiles", []):
                reference = str(profile.get("credential_ref") or "")
                if reference:
                    profile["api_key"] = self.credential_authority.read(reference)
                    profile["api_key_set"] = True
                else:
                    profile["api_key"] = ""
                    profile["api_key_set"] = False
        return hydrated

    def _normalize(self, catalog: dict[str, Any]) -> bool:
        services = catalog.setdefault("services", {})
        changed = False
        services.setdefault("llm", _service_shell())
        services.setdefault("embedding", _service_shell())
        services.setdefault("search", _search_shell())
        services.setdefault("tts", _service_shell())
        services.setdefault("stt", _service_shell())
        services.setdefault("imagegen", _service_shell())
        services.setdefault("videogen", _service_shell())
        for service_name in ("llm", "embedding", "search", "tts", "stt", "imagegen", "videogen"):
            service = services[service_name]
            profiles = service.setdefault("profiles", [])
            for profile in profiles:
                profile.setdefault("id", f"{service_name}-profile-{uuid4().hex[:8]}")
                profile.setdefault("name", "Untitled Profile")
                profile.setdefault("api_version", "")
                profile.setdefault("base_url", "")
                profile.setdefault("api_key_set", False)
                if service_name == "search":
                    profile.setdefault("provider", "brave")
                    profile.setdefault("proxy", "")
                    profile["models"] = []
                else:
                    profile.setdefault("binding", "openai")
                    profile.setdefault("extra_headers", {})
                    if service_name == "embedding":
                        before = str(profile.get("base_url") or "")
                        after = normalize_embedding_endpoint_for_display(
                            profile.get("binding"),
                            before,
                        )
                        if after != before:
                            profile["base_url"] = after
                            changed = True
                    models = profile.setdefault("models", [])
                    for model in models:
                        model.setdefault("id", f"{service_name}-model-{uuid4().hex[:8]}")
                        model.setdefault("name", model.get("model") or "Untitled Model")
                        model.setdefault("model", "")
                        if service_name == "embedding":
                            # Empty default → test_runner auto-fills from the
                            # actual API response on first connection test.
                            model.setdefault("dimension", "")
                            # CSV of supported dims discovered during the last
                            # successful "Test connection" — drives the UI
                            # dropdown. Empty when the model is not in any
                            # adapter's MODELS_INFO map.
                            model.setdefault("supported_dimensions", "")
                        elif service_name == "tts":
                            # Provider/model-specific free-form voice string
                            # (e.g. "alloy", "autumn", "model:voice").
                            model.setdefault("voice", "")
                            model.setdefault("response_format", "mp3")
                        elif service_name == "imagegen":
                            # Generation knobs; empty → provider default.
                            model.setdefault("size", "")
                            model.setdefault("quality", "")
                            model.setdefault("style", "")
                            model.setdefault("response_format", "")
                        elif service_name == "videogen":
                            model.setdefault("aspect_ratio", "")
                            model.setdefault("duration", "")
                            model.setdefault("resolution", "")
            profile_ids = {profile.get("id") for profile in profiles}
            if profiles and service.get("active_profile_id") not in profile_ids:
                service["active_profile_id"] = profiles[0]["id"]
                changed = True
            if service_name in {"llm", "embedding", "tts", "stt", "imagegen", "videogen"}:
                active_profile = self.get_active_profile(catalog, service_name)
                models = (active_profile or {}).get("models") or []
                model_ids = {model.get("id") for model in models}
                if models and service.get("active_model_id") not in model_ids:
                    service["active_model_id"] = models[0]["id"]
                    changed = True
        return changed

    def get_active_profile(
        self, catalog: dict[str, Any], service_name: str
    ) -> dict[str, Any] | None:
        service = catalog.get("services", {}).get(service_name, {})
        active_id = service.get("active_profile_id")
        for profile in service.get("profiles", []):
            if profile.get("id") == active_id:
                return profile
        profiles = service.get("profiles", [])
        return profiles[0] if profiles else None

    def get_active_model(self, catalog: dict[str, Any], service_name: str) -> dict[str, Any] | None:
        if service_name == "search":
            return None
        service = catalog.get("services", {}).get(service_name, {})
        active_model_id = service.get("active_model_id")
        profile = self.get_active_profile(catalog, service_name)
        if not profile:
            return None
        for model in profile.get("models", []):
            if model.get("id") == active_model_id:
                return model
        models = profile.get("models", [])
        return models[0] if models else None


def get_model_catalog_service() -> ModelCatalogService:
    """Return the deployment-owned provider catalog.

    Course operations temporarily route the ambient ``PathService`` to the
    authenticated learner's private workspace, including for administrators.
    Provider credentials and model authority are deployment settings, not
    learner-owned Course data, so they must never follow that personal scope.
    """
    from deeptutor.multi_user.paths import get_admin_path_service

    return ModelCatalogService.get_instance(
        get_admin_path_service().get_settings_file("model_catalog")
    )


__all__ = ["CATALOG_PATH", "ModelCatalogService", "get_model_catalog_service"]
