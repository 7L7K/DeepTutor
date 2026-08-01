from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from deeptutor.services.config.text_generation_qualification import (
    FrozenQualificationPack,
    TextGenerationQualificationError,
    validate_qualification_observations,
)
from deeptutor.services.config.text_generation_registry import (
    TextGenerationRegistry,
    default_text_generation_catalog,
)

_PACK_PATH = Path("qualification/text_generation_core_v1.json")


def _registry() -> TextGenerationRegistry:
    return TextGenerationRegistry.from_catalog(
        {"text_generation": default_text_generation_catalog()}
    )


def _observations() -> list[dict[str, object]]:
    pack = FrozenQualificationPack.load(_PACK_PATH)
    registry = _registry()
    observations: list[dict[str, object]] = []
    for case in pack.cases:
        for model_id in pack.models:
            model = registry.require_model(model_id)
            input_tokens = 120
            cached_tokens = 20
            output_tokens = 60
            cost = model.pricing.cost_microusd(
                input_tokens=input_tokens,
                cached_input_tokens=cached_tokens,
                output_tokens=output_tokens,
            )
            observations.append(
                {
                    "case_id": case.case_id,
                    "feature": case.feature,
                    "input_sha256": case.input_sha256,
                    "artifact_id": f"artifact-{case.case_id}-{model_id}",
                    "artifact_sha256": "a" * 64,
                    "requested_model": model_id,
                    "actual_model": model.api_model,
                    "pricing_version": model.pricing.version,
                    "prompt_version": "qualification-prompt-v1",
                    "schema_version": "qualification-schema-v1",
                    "reasoning_effort": "low",
                    "store": False,
                    "response_status": "completed",
                    "call_count": 1,
                    "retry_count": 0,
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_tokens,
                    "output_tokens": output_tokens,
                    "latency_ms": 100,
                    "estimated_cost_microusd": cost,
                    "settled_cost_microusd": cost,
                    "observed_at": "2026-08-01T00:00:00Z",
                    "grader_results": {
                        grader: "pass" for grader in case.required_graders
                    },
                    "security_result": "pass",
                    "validation_result": "pass",
                }
            )
    return observations


def test_frozen_pack_covers_all_core_pathways_without_paid_authority() -> None:
    pack = FrozenQualificationPack.load(_PACK_PATH)

    assert pack.models == ("gpt-5-mini", "gpt-5.6-luna")
    assert pack.reasoning_effort == "low"
    assert pack.max_calls_per_model_case == 1
    assert pack.max_retries == 0
    assert pack.paid_gate == "not_authorized"
    assert pack.approved_spend_cap_microusd is None
    assert len(pack.cases) == 8


def test_complete_passing_observation_matrix_validates() -> None:
    validate_qualification_observations(
        pack=FrozenQualificationPack.load(_PACK_PATH),
        registry=_registry(),
        observations=_observations(),
        require_passing=True,
    )


@pytest.mark.parametrize(
    "mutate,match",
    [
        (
            lambda rows: rows[0].update(input_sha256="0" * 64),
            "exact frozen input",
        ),
        (
            lambda rows: rows[0].update(actual_model="gpt-5.6-luna"),
            "actual model",
        ),
        (
            lambda rows: rows[0].update(retry_count=1),
            "one call and zero retries",
        ),
        (
            lambda rows: rows[0].update(settled_cost_microusd=0),
            "versioned registry pricing",
        ),
        (
            lambda rows: rows[0]["grader_results"].pop(
                next(iter(rows[0]["grader_results"]))
            ),
            "grader results are incomplete",
        ),
    ],
)
def test_observation_contract_fails_closed(mutate, match: str) -> None:
    observations = _observations()
    mutate(observations)

    with pytest.raises(TextGenerationQualificationError, match=match):
        validate_qualification_observations(
            pack=FrozenQualificationPack.load(_PACK_PATH),
            registry=_registry(),
            observations=observations,
        )


def test_security_failure_blocks_passing_qualification() -> None:
    observations = _observations()
    observations[0]["security_result"] = "fail"

    with pytest.raises(TextGenerationQualificationError, match="acceptance gate"):
        validate_qualification_observations(
            pack=FrozenQualificationPack.load(_PACK_PATH),
            registry=_registry(),
            observations=observations,
            require_passing=True,
        )


def test_unreviewed_required_grader_blocks_passing_qualification() -> None:
    observations = _observations()
    grader = next(iter(observations[0]["grader_results"]))
    observations[0]["grader_results"][grader] = "not_applicable"

    with pytest.raises(TextGenerationQualificationError, match="acceptance gate"):
        validate_qualification_observations(
            pack=FrozenQualificationPack.load(_PACK_PATH),
            registry=_registry(),
            observations=observations,
            require_passing=True,
        )


def test_provider_free_pack_rejects_embedded_spend_authority(tmp_path: Path) -> None:
    payload = json.loads(_PACK_PATH.read_text(encoding="utf-8"))
    payload["paid_gate"] = "authorized"
    payload["approved_spend_cap_microusd"] = 10_000
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TextGenerationQualificationError, match="paid-call authority"):
        FrozenQualificationPack.load(path)


def test_pack_rejects_pathway_feature_rebinding(tmp_path: Path) -> None:
    payload = json.loads(_PACK_PATH.read_text(encoding="utf-8"))
    payload["cases"][0]["feature"] = "course_chat"
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TextGenerationQualificationError, match="wrong feature"):
        FrozenQualificationPack.load(path)


def test_duplicate_or_missing_model_case_receipts_fail_closed() -> None:
    observations = _observations()
    observations[-1] = deepcopy(observations[0])

    with pytest.raises(TextGenerationQualificationError, match="duplicated"):
        validate_qualification_observations(
            pack=FrozenQualificationPack.load(_PACK_PATH),
            registry=_registry(),
            observations=observations,
        )
