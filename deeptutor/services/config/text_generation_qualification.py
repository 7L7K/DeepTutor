"""Provider-free contract for Mini-versus-Luna qualification.

This module deliberately cannot invoke a provider.  It freezes comparison
inputs and validates completed observation receipts so a live runner must use
the same prompt/source surface for both models, make one call without retries,
and retain exact model, pricing, usage, cost, and grader provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from .text_generation_registry import (
    TextGenerationRegistry,
    TextGenerationRegistryError,
)


class TextGenerationQualificationError(RuntimeError):
    """The frozen pack or an observation receipt violates the live-call gate."""


_EXPECTED_MODELS = ("gpt-5-mini", "gpt-5.6-luna")
_EXPECTED_PATHWAY_FEATURES = {
    "general_chat": "general_chat",
    "course_chat": "course_chat",
    "course_flashcards": "flashcard_generation",
    "conversation_flashcards": "flashcard_generation",
    "course_practice": "practice_generation",
    "general_study_practice": "practice_generation",
    "make_flashcards_handoff": "general_chat",
    "quiz_me_handoff": "course_chat",
}
_RESULTS = {"pass", "fail", "not_applicable"}


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TextGenerationQualificationError(f"Qualification field {key!r} is required")
    return value.strip()


def _non_negative_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TextGenerationQualificationError(
            f"Qualification field {key!r} must be a non-negative integer"
        )
    return value


@dataclass(frozen=True)
class FrozenQualificationCase:
    case_id: str
    feature: str
    pathway: str
    input_sha256: str
    required_graders: tuple[str, ...]
    payload: dict[str, Any]


@dataclass(frozen=True)
class FrozenQualificationPack:
    pack_id: str
    reasoning_effort: str
    models: tuple[str, ...]
    max_calls_per_model_case: int
    max_retries: int
    paid_gate: str
    approved_spend_cap_microusd: int | None
    cases: tuple[FrozenQualificationCase, ...]

    @classmethod
    def load(cls, path: Path) -> "FrozenQualificationPack":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TextGenerationQualificationError(
                "Qualification pack is unavailable or invalid"
            ) from exc
        if not isinstance(raw, dict) or set(raw) != {
            "version",
            "pack_id",
            "models",
            "reasoning_effort",
            "max_calls_per_model_case",
            "max_retries",
            "paid_gate",
            "approved_spend_cap_microusd",
            "cases",
        }:
            raise TextGenerationQualificationError("Qualification pack shape is invalid")
        if raw["version"] != 1:
            raise TextGenerationQualificationError("Qualification pack version is unsupported")
        models = raw["models"]
        if not isinstance(models, list) or tuple(models) != _EXPECTED_MODELS:
            raise TextGenerationQualificationError(
                "Qualification pack must compare Mini and Luna in fixed order"
            )
        if raw["reasoning_effort"] != "low":
            raise TextGenerationQualificationError(
                "Initial Mini-versus-Luna qualification must use low reasoning"
            )
        if raw["max_calls_per_model_case"] != 1 or raw["max_retries"] != 0:
            raise TextGenerationQualificationError(
                "Qualification must remain single-call with no automatic retries"
            )
        if raw["paid_gate"] != "not_authorized" or raw["approved_spend_cap_microusd"] is not None:
            raise TextGenerationQualificationError(
                "Frozen provider-free pack must not contain paid-call authority"
            )
        raw_cases = raw["cases"]
        if not isinstance(raw_cases, list) or not raw_cases:
            raise TextGenerationQualificationError("Qualification cases are missing")
        cases: list[FrozenQualificationCase] = []
        case_ids: set[str] = set()
        pathways: set[str] = set()
        for raw_case in raw_cases:
            cases.append(cls._parse_case(raw_case, case_ids, pathways))
        if pathways != set(_EXPECTED_PATHWAY_FEATURES):
            raise TextGenerationQualificationError(
                "Qualification pack does not cover every required core pathway"
            )
        return cls(
            pack_id=_required_string(raw, "pack_id"),
            reasoning_effort="low",
            models=_EXPECTED_MODELS,
            max_calls_per_model_case=1,
            max_retries=0,
            paid_gate="not_authorized",
            approved_spend_cap_microusd=None,
            cases=tuple(cases),
        )

    @classmethod
    def _parse_case(
        cls,
        raw_case: object,
        case_ids: set[str],
        pathways: set[str],
    ) -> FrozenQualificationCase:
        if not isinstance(raw_case, dict) or set(raw_case) != {
            "case_id",
            "feature",
            "pathway",
            "required_graders",
            "input_sha256",
            "input",
        }:
            raise TextGenerationQualificationError("Qualification case shape is invalid")
        case_id = _required_string(raw_case, "case_id")
        feature = _required_string(raw_case, "feature")
        pathway = _required_string(raw_case, "pathway")
        if _EXPECTED_PATHWAY_FEATURES.get(pathway) != feature:
            raise TextGenerationQualificationError(
                "Qualification pathway is bound to the wrong feature"
            )
        if case_id in case_ids or pathway in pathways:
            raise TextGenerationQualificationError(
                "Qualification case IDs and pathways must be unique"
            )
        case_ids.add(case_id)
        pathways.add(pathway)
        required_graders = raw_case["required_graders"]
        if (
            not isinstance(required_graders, list)
            or not required_graders
            or any(not isinstance(item, str) or not item for item in required_graders)
            or len(required_graders) != len(set(required_graders))
        ):
            raise TextGenerationQualificationError("Qualification graders are invalid")
        input_payload = raw_case["input"]
        if not isinstance(input_payload, dict):
            raise TextGenerationQualificationError("Qualification input must be an object")
        cls._validate_sources(input_payload)
        expected_hash = _canonical_sha256(input_payload)
        if raw_case["input_sha256"] != expected_hash:
            raise TextGenerationQualificationError(
                f"Frozen input hash mismatch for case {case_id!r}"
            )
        return FrozenQualificationCase(
            case_id=case_id,
            feature=feature,
            pathway=pathway,
            input_sha256=expected_hash,
            required_graders=tuple(required_graders),
            payload=input_payload,
        )

    @staticmethod
    def _validate_sources(input_payload: dict[str, Any]) -> None:
        sources = input_payload.get("sources", [])
        if not isinstance(sources, list):
            raise TextGenerationQualificationError("Qualification sources must be a list")
        for source in sources:
            if not isinstance(source, dict) or set(source) != {
                "source_id",
                "source_revision",
                "content_sha256",
                "text",
            }:
                raise TextGenerationQualificationError(
                    "Qualification source shape is invalid"
                )
            _required_string(source, "source_id")
            text = _required_string(source, "text")
            if source["content_sha256"] != hashlib.sha256(text.encode("utf-8")).hexdigest():
                raise TextGenerationQualificationError(
                    "Qualification source content hash is invalid"
                )
            revision = source["source_revision"]
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise TextGenerationQualificationError(
                    "Qualification source revision is invalid"
                )

    def case(self, case_id: str) -> FrozenQualificationCase:
        for item in self.cases:
            if item.case_id == case_id:
                return item
        raise TextGenerationQualificationError(f"Unknown qualification case {case_id!r}")


def validate_qualification_observations(
    *,
    pack: FrozenQualificationPack,
    registry: TextGenerationRegistry,
    observations: list[dict[str, Any]],
    require_passing: bool = False,
) -> None:
    """Validate a complete two-model receipt set without invoking a provider."""

    expected_pairs = {
        (case.case_id, model) for case in pack.cases for model in pack.models
    }
    if len(observations) != len(expected_pairs):
        raise TextGenerationQualificationError(
            "Qualification requires exactly one observation per model and case"
        )
    seen: set[tuple[str, str]] = set()
    for observation in observations:
        if not isinstance(observation, dict):
            raise TextGenerationQualificationError("Qualification observation is invalid")
        case = pack.case(_required_string(observation, "case_id"))
        requested_model = _required_string(observation, "requested_model")
        pair = (case.case_id, requested_model)
        if pair not in expected_pairs or pair in seen:
            raise TextGenerationQualificationError(
                "Qualification observation pair is unexpected or duplicated"
            )
        seen.add(pair)
        if observation.get("feature") != case.feature:
            raise TextGenerationQualificationError("Qualification feature does not match its case")
        if observation.get("input_sha256") != case.input_sha256:
            raise TextGenerationQualificationError(
                "Mini and Luna must use the exact frozen input"
            )
        model = registry.require_model(requested_model)
        try:
            model.require_actual_model(_required_string(observation, "actual_model"))
        except TextGenerationRegistryError as exc:
            raise TextGenerationQualificationError(
                "Qualification actual model is invalid"
            ) from exc
        if observation.get("pricing_version") != model.pricing.version:
            raise TextGenerationQualificationError(
                "Qualification pricing version does not match the registry"
            )
        if observation.get("reasoning_effort") != pack.reasoning_effort:
            raise TextGenerationQualificationError(
                "Qualification reasoning settings are not identical"
            )
        if observation.get("store") is not False:
            raise TextGenerationQualificationError("Qualification calls must use store=false")
        if observation.get("response_status") != "completed":
            raise TextGenerationQualificationError(
                "Qualification response did not complete"
            )
        if observation.get("call_count") != 1 or observation.get("retry_count") != 0:
            raise TextGenerationQualificationError(
                "Qualification receipts must prove one call and zero retries"
            )
        input_tokens = _non_negative_int(observation, "input_tokens")
        cached_tokens = _non_negative_int(observation, "cached_input_tokens")
        output_tokens = _non_negative_int(observation, "output_tokens")
        _non_negative_int(observation, "latency_ms")
        estimated_cost = _non_negative_int(observation, "estimated_cost_microusd")
        settled_cost = _non_negative_int(observation, "settled_cost_microusd")
        expected_cost = model.pricing.cost_microusd(
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
        )
        if estimated_cost != expected_cost or settled_cost != expected_cost:
            raise TextGenerationQualificationError(
                "Qualification costs do not match versioned registry pricing"
            )
        for key in (
            "artifact_id",
            "artifact_sha256",
            "prompt_version",
            "schema_version",
            "observed_at",
        ):
            _required_string(observation, key)
        graders = observation.get("grader_results")
        if not isinstance(graders, dict) or set(graders) != set(case.required_graders):
            raise TextGenerationQualificationError(
                "Qualification grader results are incomplete"
            )
        if any(result not in _RESULTS for result in graders.values()):
            raise TextGenerationQualificationError(
                "Qualification grader result is invalid"
            )
        security = observation.get("security_result")
        validation = observation.get("validation_result")
        if security not in {"pass", "fail"} or validation not in {"pass", "fail"}:
            raise TextGenerationQualificationError(
                "Qualification security and validation results are required"
            )
        if require_passing and (
            security != "pass"
            or validation != "pass"
            or any(result != "pass" for result in graders.values())
        ):
            raise TextGenerationQualificationError(
                "A qualification observation failed an acceptance gate"
            )
    if seen != expected_pairs:
        raise TextGenerationQualificationError(
            "Qualification observation matrix is incomplete"
        )


__all__ = [
    "FrozenQualificationCase",
    "FrozenQualificationPack",
    "TextGenerationQualificationError",
    "validate_qualification_observations",
]
