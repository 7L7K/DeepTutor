from __future__ import annotations

import json

import pytest

from deeptutor.services.config.flashcard_provider import (
    FlashcardProviderConfigError,
    FlashcardProviderConfigService,
)


def test_flashcard_provider_is_disabled_and_separate_by_default(tmp_path) -> None:
    service = FlashcardProviderConfigService(tmp_path / "settings" / "flashcard_provider.json")

    assert service.load_public() == {
        "enabled": False,
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "credential_configured": False,
    }


def test_flashcard_provider_requires_a_dedicated_credential(tmp_path) -> None:
    service = FlashcardProviderConfigService(tmp_path / "settings" / "flashcard_provider.json")

    with pytest.raises(
        FlashcardProviderConfigError,
        match="credential is required",
    ):
        service.configure(enabled=True)


def test_flashcard_provider_persists_only_opaque_reference(tmp_path) -> None:
    path = tmp_path / "settings" / "flashcard_provider.json"
    service = FlashcardProviderConfigService(path)

    configured = service.configure(enabled=True, api_key="sk-test-private")
    persisted = json.loads(path.read_text(encoding="utf-8"))
    public = service.load_public()

    assert configured.api_key == "sk-test-private"
    assert persisted["credential_ref"].startswith("pcr_")
    assert "sk-test-private" not in path.read_text(encoding="utf-8")
    assert public["enabled"] is True
    assert public["credential_configured"] is True
    assert "api_key" not in public
    assert "credential_ref" not in public


def test_flashcard_provider_reads_legacy_model_field_without_using_it_as_authority(
    tmp_path,
) -> None:
    path = tmp_path / "settings" / "flashcard_provider.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "enabled": False,
                "provider": "openai",
                "model": "gpt-5-mini",
                "base_url": "https://api.openai.com/v1",
                "credential_ref": None,
            }
        ),
        encoding="utf-8",
    )

    config = FlashcardProviderConfigService(path).load()

    assert config.provider == "openai"
    assert not hasattr(config, "model")


def test_flashcard_provider_disable_preserves_credential_for_reenable(
    tmp_path,
) -> None:
    path = tmp_path / "settings" / "flashcard_provider.json"
    service = FlashcardProviderConfigService(path)
    service.configure(enabled=True, api_key="sk-test-private")

    disabled = service.configure(enabled=False)
    reenabled = service.configure(enabled=True)

    assert disabled.enabled is False
    assert reenabled.enabled is True
    assert reenabled.api_key == "sk-test-private"
