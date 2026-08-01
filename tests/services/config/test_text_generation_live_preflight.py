from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from deeptutor.services.config.text_generation_live_preflight import (
    MAX_INITIAL_LIVE_SPEND_MICROUSD,
    TextGenerationLivePreflightError,
    load_authorized_live_qualification_run,
)
from deeptutor.services.config.text_generation_qualification import (
    FrozenQualificationPack,
)
from deeptutor.services.config.text_generation_registry import (
    TextGenerationRegistry,
    default_text_generation_catalog,
)

_PACK_PATH = Path("qualification/text_generation_core_v1.json")
_MATRIX_PATH = Path("qualification/provider_free_compatibility_v1.json")
_NOW = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registry() -> TextGenerationRegistry:
    return TextGenerationRegistry.from_catalog(
        {"text_generation": default_text_generation_catalog()}
    )


def _manifest() -> dict[str, object]:
    pack = FrozenQualificationPack.load(_PACK_PATH)
    registry = _registry()
    matrix = json.loads(_MATRIX_PATH.read_text(encoding="utf-8"))
    return {
        "version": 1,
        "run_id": "qrun_20260801_core_01",
        "pack_id": pack.pack_id,
        "pack_sha256": _sha256(_PACK_PATH),
        "compatibility_matrix_id": matrix["matrix_id"],
        "compatibility_matrix_sha256": _sha256(_MATRIX_PATH),
        "provider_calls_authorized": True,
        "approval_reference": "thread-user-message-2026-08-01",
        "approval_sha256": hashlib.sha256(b"synthetic approval").hexdigest(),
        "approved_at": "2026-08-01T17:55:00Z",
        "expires_at": "2026-08-02T17:55:00Z",
        "approved_spend_cap_microusd": 250_000,
        "max_calls_per_model_case": 1,
        "max_retries": 0,
        "store": False,
        "reasoning_effort": "low",
        "models": [
            {
                "model_id": model_id,
                "api_model": registry.require_model(model_id).api_model,
                "pricing_version": registry.require_model(model_id).pricing.version,
            }
            for model_id in pack.models
        ],
        "cases": [
            {"case_id": case.case_id, "input_sha256": case.input_sha256}
            for case in pack.cases
        ],
        "authorized_pairs": [
            {"case_id": case.case_id, "requested_model": model_id}
            for case in pack.cases
            for model_id in pack.models
        ],
    }


def _luna_medium_manifest() -> dict[str, object]:
    payload = _manifest()
    pack = FrozenQualificationPack.load(_PACK_PATH)
    registry = _registry()
    selected = [
        case
        for case in pack.cases
        if case.case_id
        in {
            "q_course_flashcards_01",
            "q_conversation_flashcards_01",
            "q_course_practice_01",
            "q_general_study_practice_01",
        }
    ]
    luna = registry.require_model("gpt-5.6-luna")
    payload.update(
        version=2,
        run_id="qrun_20260801_luna_generation_medium_01",
        approval_reference="thread-user-message-2026-08-01-luna-medium-015usd",
        approved_spend_cap_microusd=150_000,
        reasoning_effort="medium",
        models=[
            {
                "model_id": "gpt-5.6-luna",
                "api_model": luna.api_model,
                "pricing_version": luna.pricing.version,
            }
        ],
        cases=[
            {"case_id": case.case_id, "input_sha256": case.input_sha256}
            for case in selected
        ],
        authorized_pairs=[
            {"case_id": case.case_id, "requested_model": "gpt-5.6-luna"}
            for case in selected
        ],
    )
    return payload


def _write_manifest(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "authorized-run.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_exact_short_lived_approval_manifest_passes_without_provider_work(
    tmp_path: Path,
) -> None:
    run = load_authorized_live_qualification_run(
        _write_manifest(tmp_path, _manifest()),
        pack_path=_PACK_PATH,
        compatibility_matrix_path=_MATRIX_PATH,
        registry=_registry(),
        now=_NOW,
    )

    assert run.approved_spend_cap_microusd == MAX_INITIAL_LIVE_SPEND_MICROUSD
    assert len(run.authorized_pairs) == 16
    assert run.authorized_pairs[0] == ("q_general_chat_01", "gpt-5-mini")


def test_luna_medium_manifest_authorizes_only_four_generation_calls(
    tmp_path: Path,
) -> None:
    run = load_authorized_live_qualification_run(
        _write_manifest(tmp_path, _luna_medium_manifest()),
        pack_path=_PACK_PATH,
        compatibility_matrix_path=_MATRIX_PATH,
        registry=_registry(),
        now=_NOW,
    )

    assert run.approved_spend_cap_microusd == 150_000
    assert run.reasoning_effort == "medium"
    assert len(run.authorized_pairs) == 4
    assert {model for _, model in run.authorized_pairs} == {"gpt-5.6-luna"}


def test_luna_medium_manifest_rejects_mini_or_extra_case(tmp_path: Path) -> None:
    payload = _luna_medium_manifest()
    payload["authorized_pairs"].append(
        {"case_id": "q_general_chat_01", "requested_model": "gpt-5-mini"}
    )

    with pytest.raises(TextGenerationLivePreflightError, match="complete pair matrix"):
        load_authorized_live_qualification_run(
            _write_manifest(tmp_path, payload),
            pack_path=_PACK_PATH,
            compatibility_matrix_path=_MATRIX_PATH,
            registry=_registry(),
            now=_NOW,
        )


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda payload: payload.update(provider_calls_authorized=False),
            "not authorized",
        ),
        (
            lambda payload: payload.update(approved_spend_cap_microusd=250_001),
            "hard limit",
        ),
        (
            lambda payload: payload.update(expires_at="2026-08-01T17:59:00Z"),
            "not currently valid",
        ),
        (
            lambda payload: payload.update(pack_sha256="0" * 64),
            "pack identity drifted",
        ),
        (
            lambda payload: payload["models"][0].update(pricing_version="stale"),
            "pricing authority drifted",
        ),
        (
            lambda payload: payload["cases"][0].update(input_sha256="0" * 64),
            "frozen input drifted",
        ),
        (
            lambda payload: payload["authorized_pairs"].pop(),
            "complete pair matrix",
        ),
    ],
)
def test_live_preflight_fails_closed_on_authority_or_provenance_drift(
    tmp_path: Path,
    mutate,
    match: str,
) -> None:
    payload = _manifest()
    mutate(payload)

    with pytest.raises(TextGenerationLivePreflightError, match=match):
        load_authorized_live_qualification_run(
            _write_manifest(tmp_path, payload),
            pack_path=_PACK_PATH,
            compatibility_matrix_path=_MATRIX_PATH,
            registry=_registry(),
            now=_NOW,
        )
