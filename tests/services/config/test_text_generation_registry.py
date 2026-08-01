from __future__ import annotations

from copy import deepcopy

import pytest

from deeptutor.services.config.text_generation_registry import (
    TextGenerationRegistry,
    TextGenerationRegistryError,
    default_text_generation_catalog,
)


def _catalog() -> dict[str, object]:
    return {"text_generation": default_text_generation_catalog()}


def test_registry_resolves_luna_only_active_policy_with_dormant_rollback() -> None:
    registry = TextGenerationRegistry.from_catalog(_catalog())

    chat = registry.resolve("general_chat", required_capabilities={"streaming"})
    flashcards = registry.resolve(
        "flashcard_generation",
        required_capabilities={"responses", "structured_outputs"},
    )

    assert registry.default_model == "gpt-5.6-luna"
    assert registry.rollback_model == "gpt-5-mini"
    assert chat.model.model_id == "gpt-5.6-luna"
    assert chat.mode == "qualified"
    assert chat.reasoning_effort == "low"
    assert flashcards.model.api_model == "gpt-5.6-luna"
    assert flashcards.mode == "qualified"
    assert flashcards.reasoning_effort == "medium"
    assert (
        flashcards.model.pricing.cost_microusd(
            input_tokens=120,
            cached_input_tokens=20,
            output_tokens=75,
        )
        == 111
    )


def test_registry_allows_explicit_luna_feature_override() -> None:
    catalog = _catalog()
    section = catalog["text_generation"]
    assert isinstance(section, dict)
    features = section["features"]
    assert isinstance(features, dict)
    features["practice_generation"] = {
        "model": "gpt-5.6-luna",
        "mode": "not_yet_evaluated",
        "reasoning_effort": "low",
    }

    registry = TextGenerationRegistry.from_catalog(catalog)
    resolved = registry.resolve(
        "practice_generation",
        required_capabilities={"responses", "structured_outputs"},
    )

    assert registry.default_model == "gpt-5.6-luna"
    assert resolved.model.api_model == "gpt-5.6-luna"
    assert resolved.mode == "not_yet_evaluated"
    assert (
        resolved.model.pricing.cost_microusd(
            input_tokens=272_001,
            output_tokens=100,
        )
        == 108_981
    )


@pytest.mark.parametrize(
    "mutate,match",
    [
        (
            lambda section: section.update(default_model="unknown-model"),
            "known definitions",
        ),
        (
            lambda section: section["models"]["gpt-5-mini"]["pricing"].pop("version"),
            "Pricing.*incomplete",
        ),
        (
            lambda section: section["models"]["gpt-5-mini"].update(
                capabilities=["made_up_capability"]
            ),
            "invalid capabilities",
        ),
        (
            lambda section: section["features"]["practice_generation"].update(
                reasoning_effort="unsupported"
            ),
            "does not support reasoning effort",
        ),
        (
            lambda section: section["models"]["gpt-5.6-luna"]["pricing"].update(
                long_context_output_multiplier_millis=None
            ),
            "invalid long-context rules",
        ),
    ],
)
def test_registry_rejects_incomplete_or_invalid_authority(mutate, match: str) -> None:
    catalog = deepcopy(_catalog())
    section = catalog["text_generation"]
    assert isinstance(section, dict)
    mutate(section)

    with pytest.raises(TextGenerationRegistryError, match=match):
        TextGenerationRegistry.from_catalog(catalog)


def test_registry_rejects_missing_feature_policy() -> None:
    catalog = _catalog()
    section = catalog["text_generation"]
    assert isinstance(section, dict)
    features = section["features"]
    assert isinstance(features, dict)
    features.pop("course_chat")

    with pytest.raises(TextGenerationRegistryError, match="policy is incomplete"):
        TextGenerationRegistry.from_catalog(catalog)


def test_actual_model_preserves_valid_snapshot_and_rejects_other_models() -> None:
    model = TextGenerationRegistry.from_catalog(_catalog()).require_model("gpt-5-mini")

    assert model.require_actual_model("gpt-5-mini-2025-08-07") == "gpt-5-mini-2025-08-07"
    with pytest.raises(TextGenerationRegistryError, match="unexpected model"):
        model.require_actual_model("gpt-5.6-luna")
    with pytest.raises(TextGenerationRegistryError, match="unexpected model"):
        model.require_actual_model("gpt-5-mini-untrusted-alias")
