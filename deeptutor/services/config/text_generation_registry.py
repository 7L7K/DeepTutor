"""Fail-closed model and feature policy for TEEECHR text generation.

The deployment-owned ``model_catalog.json`` remains the persisted authority.
This module gives its ``text_generation`` section a typed runtime contract so
domain providers do not carry their own model allowlists or price tables.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

TEXT_GENERATION_FEATURES = (
    "general_chat",
    "course_chat",
    "flashcard_generation",
    "practice_generation",
)

_KNOWN_CAPABILITIES = frozenset(
    {
        "batch",
        "chat_completions",
        "function_calling",
        "image_input",
        "responses",
        "streaming",
        "structured_outputs",
    }
)
_KNOWN_MODES = frozenset({"qualified", "not_yet_evaluated", "blocked", "rollback"})


class TextGenerationRegistryError(RuntimeError):
    """The deployment-owned text-generation policy is incomplete or invalid."""


@dataclass(frozen=True)
class ModelPricing:
    version: str
    input_microusd_per_million: int
    cached_input_microusd_per_million: int
    output_microusd_per_million: int
    long_context_threshold_tokens: int | None = None
    long_context_input_multiplier_millis: int | None = None
    long_context_output_multiplier_millis: int | None = None

    def cost_microusd(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
    ) -> int:
        values = (input_tokens, output_tokens, cached_input_tokens)
        if any(isinstance(value, bool) or value < 0 for value in values):
            raise TextGenerationRegistryError("Token counts must be non-negative integers")
        if cached_input_tokens > input_tokens:
            raise TextGenerationRegistryError("Cached input tokens cannot exceed input tokens")
        input_multiplier = 1000
        output_multiplier = 1000
        if (
            self.long_context_threshold_tokens is not None
            and input_tokens > self.long_context_threshold_tokens
        ):
            input_multiplier = self.long_context_input_multiplier_millis or 1000
            output_multiplier = self.long_context_output_multiplier_millis or 1000
        uncached_input_tokens = input_tokens - cached_input_tokens
        numerator = (
            uncached_input_tokens * self.input_microusd_per_million * input_multiplier
            + cached_input_tokens * self.cached_input_microusd_per_million * input_multiplier
            + output_tokens * self.output_microusd_per_million * output_multiplier
        )
        # Rates are per million tokens and multipliers are represented in
        # thousandths. Paid operations reserve at least one micro-dollar.
        return max(1, (numerator + 999_999_999) // 1_000_000_000)


@dataclass(frozen=True)
class TextModelDefinition:
    model_id: str
    provider: str
    api_model: str
    capabilities: frozenset[str]
    context_window_tokens: int
    max_output_tokens: int
    reasoning_efforts: tuple[str, ...]
    pricing: ModelPricing

    def require_capabilities(self, required: Iterable[str]) -> None:
        missing = sorted(set(required) - self.capabilities)
        if missing:
            raise TextGenerationRegistryError(
                f"Model {self.model_id!r} lacks required capabilities: {', '.join(missing)}"
            )

    def require_reasoning_effort(self, reasoning_effort: str) -> None:
        if reasoning_effort not in self.reasoning_efforts:
            raise TextGenerationRegistryError(
                f"Model {self.model_id!r} does not support reasoning effort {reasoning_effort!r}"
            )

    def require_actual_model(self, actual_model: str) -> str:
        normalized = actual_model.strip()
        if not normalized or not (
            normalized == self.api_model
            or re.fullmatch(
                rf"{re.escape(self.api_model)}-\d{{4}}-\d{{2}}-\d{{2}}",
                normalized,
            )
        ):
            raise TextGenerationRegistryError(f"Provider returned unexpected model {normalized!r}")
        return normalized


@dataclass(frozen=True)
class ResolvedTextGeneration:
    feature: str
    mode: str
    model: TextModelDefinition
    reasoning_effort: str


def default_text_generation_catalog() -> dict[str, Any]:
    """Return the versioned behavior-preserving registry seed.

    Luna is the sole active model. Mini remains defined only as the emergency
    rollback authority and is not selected by any feature policy.
    """

    shared_capabilities = [
        "batch",
        "chat_completions",
        "function_calling",
        "image_input",
        "responses",
        "streaming",
        "structured_outputs",
    ]
    return {
        "version": 1,
        "default_model": "gpt-5.6-luna",
        "rollback_model": "gpt-5-mini",
        "models": {
            "gpt-5-mini": {
                "provider": "openai",
                "api_model": "gpt-5-mini",
                "capabilities": shared_capabilities,
                "context_window_tokens": 400_000,
                "max_output_tokens": 128_000,
                "reasoning_efforts": ["minimal", "low", "medium", "high"],
                "pricing": {
                    "version": "openai-gpt-5-mini-pricing-2026-07-29",
                    "input_microusd_per_million": 250_000,
                    "cached_input_microusd_per_million": 25_000,
                    "output_microusd_per_million": 2_000_000,
                    "long_context_threshold_tokens": None,
                    "long_context_input_multiplier_millis": None,
                    "long_context_output_multiplier_millis": None,
                },
            },
            "gpt-5.6-luna": {
                "provider": "openai",
                "api_model": "gpt-5.6-luna",
                "capabilities": shared_capabilities,
                "context_window_tokens": 1_050_000,
                "max_output_tokens": 128_000,
                "reasoning_efforts": ["low", "medium", "high"],
                "pricing": {
                    "version": "openai-gpt-5.6-luna-2026-08-01",
                    "input_microusd_per_million": 200_000,
                    "cached_input_microusd_per_million": 20_000,
                    "output_microusd_per_million": 1_200_000,
                    "long_context_threshold_tokens": 272_000,
                    "long_context_input_multiplier_millis": 2_000,
                    "long_context_output_multiplier_millis": 1_500,
                },
            },
        },
        "features": {
            "general_chat": {
                "model": "default",
                "mode": "qualified",
                "reasoning_effort": "low",
            },
            "course_chat": {
                "model": "default",
                "mode": "qualified",
                "reasoning_effort": "low",
            },
            # Preserve the existing Responses request behavior during Phase 1.
            "flashcard_generation": {
                "model": "default",
                "mode": "qualified",
                "reasoning_effort": "medium",
            },
            "practice_generation": {
                "model": "default",
                "mode": "qualified",
                "reasoning_effort": "medium",
            },
        },
    }


class TextGenerationRegistry:
    def __init__(
        self,
        *,
        models: dict[str, TextModelDefinition],
        default_model: str,
        rollback_model: str,
        features: dict[str, dict[str, str]],
    ) -> None:
        self.models = models
        self.default_model = default_model
        self.rollback_model = rollback_model
        self.features = features

    @classmethod
    def from_catalog(cls, catalog: dict[str, Any]) -> "TextGenerationRegistry":
        section = catalog.get("text_generation")
        if not isinstance(section, dict) or section.get("version") != 1:
            raise TextGenerationRegistryError(
                "Text-generation registry version is missing or unsupported"
            )
        raw_models = section.get("models")
        if not isinstance(raw_models, dict) or not raw_models:
            raise TextGenerationRegistryError("Text-generation models are missing")
        models = {
            str(model_id): cls._parse_model(str(model_id), payload)
            for model_id, payload in raw_models.items()
        }
        default_model = cls._required_string(section, "default_model")
        rollback_model = cls._required_string(section, "rollback_model")
        if default_model not in models or rollback_model not in models:
            raise TextGenerationRegistryError(
                "Default and rollback models must reference known definitions"
            )
        raw_features = section.get("features")
        if not isinstance(raw_features, dict) or set(raw_features) != set(TEXT_GENERATION_FEATURES):
            raise TextGenerationRegistryError("Text-generation feature policy is incomplete")
        features: dict[str, dict[str, str]] = {}
        for feature in TEXT_GENERATION_FEATURES:
            payload = raw_features[feature]
            if not isinstance(payload, dict) or set(payload) != {
                "model",
                "mode",
                "reasoning_effort",
            }:
                raise TextGenerationRegistryError(f"Feature policy {feature!r} is malformed")
            model_reference = cls._required_string(payload, "model")
            mode = cls._required_string(payload, "mode")
            reasoning_effort = cls._required_string(payload, "reasoning_effort")
            if mode not in _KNOWN_MODES:
                raise TextGenerationRegistryError(f"Feature policy {feature!r} has an invalid mode")
            if model_reference not in {"default", "rollback"} and model_reference not in models:
                raise TextGenerationRegistryError(
                    f"Feature policy {feature!r} references an unknown model"
                )
            features[feature] = {
                "model": model_reference,
                "mode": mode,
                "reasoning_effort": reasoning_effort,
            }
        registry = cls(
            models=models,
            default_model=default_model,
            rollback_model=rollback_model,
            features=features,
        )
        # Resolve every feature during construction so invalid reasoning/model
        # combinations fail before any provider client can be created.
        for feature in TEXT_GENERATION_FEATURES:
            registry.resolve(feature)
        return registry

    @staticmethod
    def _required_string(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise TextGenerationRegistryError(f"Registry field {key!r} is required")
        return value.strip()

    @classmethod
    def _parse_model(cls, model_id: str, payload: object) -> TextModelDefinition:
        if not model_id or not isinstance(payload, dict):
            raise TextGenerationRegistryError("Model definition is malformed")
        expected = {
            "provider",
            "api_model",
            "capabilities",
            "context_window_tokens",
            "max_output_tokens",
            "reasoning_efforts",
            "pricing",
        }
        if set(payload) != expected:
            raise TextGenerationRegistryError(f"Model definition {model_id!r} is incomplete")
        provider = cls._required_string(payload, "provider")
        api_model = cls._required_string(payload, "api_model")
        capabilities = payload["capabilities"]
        reasoning_efforts = payload["reasoning_efforts"]
        if (
            provider != "openai"
            or not isinstance(capabilities, list)
            or not capabilities
            or any(item not in _KNOWN_CAPABILITIES for item in capabilities)
            or len(set(capabilities)) != len(capabilities)
            or not isinstance(reasoning_efforts, list)
            or not reasoning_efforts
            or any(not isinstance(item, str) or not item.strip() for item in reasoning_efforts)
            or len(set(reasoning_efforts)) != len(reasoning_efforts)
        ):
            raise TextGenerationRegistryError(
                f"Model definition {model_id!r} has invalid capabilities or reasoning settings"
            )
        context_window = payload["context_window_tokens"]
        max_output = payload["max_output_tokens"]
        if (
            any(
                isinstance(value, bool) or not isinstance(value, int) or value < 1
                for value in (context_window, max_output)
            )
            or max_output > context_window
        ):
            raise TextGenerationRegistryError(
                f"Model definition {model_id!r} has invalid token limits"
            )
        pricing = cls._parse_pricing(model_id, payload["pricing"])
        return TextModelDefinition(
            model_id=model_id,
            provider=provider,
            api_model=api_model,
            capabilities=frozenset(capabilities),
            context_window_tokens=context_window,
            max_output_tokens=max_output,
            reasoning_efforts=tuple(reasoning_efforts),
            pricing=pricing,
        )

    @classmethod
    def _parse_pricing(cls, model_id: str, payload: object) -> ModelPricing:
        expected = {
            "version",
            "input_microusd_per_million",
            "cached_input_microusd_per_million",
            "output_microusd_per_million",
            "long_context_threshold_tokens",
            "long_context_input_multiplier_millis",
            "long_context_output_multiplier_millis",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise TextGenerationRegistryError(f"Pricing for {model_id!r} is incomplete")
        version = cls._required_string(payload, "version")
        rates = (
            payload["input_microusd_per_million"],
            payload["cached_input_microusd_per_million"],
            payload["output_microusd_per_million"],
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in rates
        ):
            raise TextGenerationRegistryError(f"Pricing for {model_id!r} has invalid rates")
        threshold = payload["long_context_threshold_tokens"]
        multipliers = (
            payload["long_context_input_multiplier_millis"],
            payload["long_context_output_multiplier_millis"],
        )
        if threshold is None:
            if any(value is not None for value in multipliers):
                raise TextGenerationRegistryError(
                    f"Pricing for {model_id!r} has invalid long-context rules"
                )
        elif (
            isinstance(threshold, bool)
            or not isinstance(threshold, int)
            or threshold < 1
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 1_000
                for value in multipliers
            )
        ):
            raise TextGenerationRegistryError(
                f"Pricing for {model_id!r} has invalid long-context rules"
            )
        return ModelPricing(
            version=version,
            input_microusd_per_million=rates[0],
            cached_input_microusd_per_million=rates[1],
            output_microusd_per_million=rates[2],
            long_context_threshold_tokens=threshold,
            long_context_input_multiplier_millis=multipliers[0],
            long_context_output_multiplier_millis=multipliers[1],
        )

    def require_model(self, model_id: str) -> TextModelDefinition:
        try:
            return self.models[model_id]
        except KeyError as exc:
            raise TextGenerationRegistryError(
                f"Unknown text-generation model {model_id!r}"
            ) from exc

    def require_api_model(self, api_model: str) -> TextModelDefinition:
        for model in self.models.values():
            try:
                model.require_actual_model(api_model)
            except TextGenerationRegistryError:
                continue
            return model
        raise TextGenerationRegistryError(
            f"Unknown text-generation API model {api_model!r}"
        )

    def resolve(
        self,
        feature: str,
        *,
        required_capabilities: Iterable[str] = (),
    ) -> ResolvedTextGeneration:
        if feature not in self.features:
            raise TextGenerationRegistryError(f"Unknown text-generation feature {feature!r}")
        policy = self.features[feature]
        model_reference = policy["model"]
        if model_reference == "default":
            model_id = self.default_model
        elif model_reference == "rollback":
            model_id = self.rollback_model
        else:
            model_id = model_reference
        model = self.require_model(model_id)
        model.require_reasoning_effort(policy["reasoning_effort"])
        model.require_capabilities(required_capabilities)
        return ResolvedTextGeneration(
            feature=feature,
            mode=policy["mode"],
            model=model,
            reasoning_effort=policy["reasoning_effort"],
        )


def get_text_generation_registry() -> TextGenerationRegistry:
    from .model_catalog import get_model_catalog_service

    return TextGenerationRegistry.from_catalog(get_model_catalog_service().load())


__all__ = [
    "ModelPricing",
    "ResolvedTextGeneration",
    "TEXT_GENERATION_FEATURES",
    "TextGenerationRegistry",
    "TextGenerationRegistryError",
    "TextModelDefinition",
    "default_text_generation_catalog",
    "get_text_generation_registry",
]
