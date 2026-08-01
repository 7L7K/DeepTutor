"""Approval-bound preflight for immutable text-generation live qualification.

This module validates authority and provenance only.  It intentionally imports
no provider client and exposes no execution method.  A separately reviewed
runner may proceed only with the returned immutable contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .text_generation_qualification import (
    FrozenQualificationPack,
    TextGenerationQualificationError,
)
from .text_generation_registry import TextGenerationRegistry

MAX_INITIAL_LIVE_SPEND_MICROUSD = 250_000
MAX_APPROVAL_LIFETIME = timedelta(hours=24)


class TextGenerationLivePreflightError(RuntimeError):
    """Live qualification authority is absent, expired, drifted, or unsafe."""


@dataclass(frozen=True)
class AuthorizedLiveQualificationRun:
    run_id: str
    approval_reference: str
    approval_sha256: str
    approved_spend_cap_microusd: int
    approved_at: datetime
    expires_at: datetime
    reasoning_effort: str
    authorized_pairs: tuple[tuple[str, str], ...]


_LUNA_GENERATION_CASE_IDS = (
    "q_course_flashcards_01",
    "q_conversation_flashcards_01",
    "q_course_practice_01",
    "q_general_study_practice_01",
)


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise TextGenerationLivePreflightError(
            "Live qualification authority artifact is unavailable"
        ) from exc


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TextGenerationLivePreflightError(
            f"Live qualification field {key!r} is required"
        )
    return value.strip()


def _sha256_string(payload: dict[str, Any], key: str) -> str:
    value = _required_string(payload, key)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise TextGenerationLivePreflightError(
            f"Live qualification field {key!r} must be a lowercase SHA-256"
        )
    return value


def _timestamp(payload: dict[str, Any], key: str) -> datetime:
    raw = _required_string(payload, key)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TextGenerationLivePreflightError(
            f"Live qualification field {key!r} is invalid"
        ) from exc
    if parsed.tzinfo is None:
        raise TextGenerationLivePreflightError(
            f"Live qualification field {key!r} must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


def load_authorized_live_qualification_run(
    manifest_path: Path,
    *,
    pack_path: Path,
    compatibility_matrix_path: Path,
    registry: TextGenerationRegistry,
    now: datetime | None = None,
) -> AuthorizedLiveQualificationRun:
    """Validate a human-approved, short-lived run manifest without network work."""

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TextGenerationLivePreflightError(
            "Live qualification manifest is unavailable or invalid"
        ) from exc
    expected_keys = {
        "version",
        "run_id",
        "pack_id",
        "pack_sha256",
        "compatibility_matrix_id",
        "compatibility_matrix_sha256",
        "provider_calls_authorized",
        "approval_reference",
        "approval_sha256",
        "approved_at",
        "expires_at",
        "approved_spend_cap_microusd",
        "max_calls_per_model_case",
        "max_retries",
        "store",
        "reasoning_effort",
        "models",
        "cases",
        "authorized_pairs",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise TextGenerationLivePreflightError("Live qualification manifest shape is invalid")
    version = manifest["version"]
    if version not in {1, 2}:
        raise TextGenerationLivePreflightError("Live qualification version is unsupported")
    if manifest["provider_calls_authorized"] is not True:
        raise TextGenerationLivePreflightError("Paid provider calls are not authorized")
    reasoning_effort = manifest["reasoning_effort"]
    if (
        manifest["max_calls_per_model_case"] != 1
        or manifest["max_retries"] != 0
        or manifest["store"] is not False
        or reasoning_effort not in {"low", "medium"}
    ):
        raise TextGenerationLivePreflightError(
            "Live qualification must use an approved reasoning level, store=false, "
            "one call, and no retries"
        )
    if (version == 1 and reasoning_effort != "low") or (
        version == 2 and reasoning_effort != "medium"
    ):
        raise TextGenerationLivePreflightError(
            "Live qualification reasoning does not match its manifest version"
        )

    cap = manifest["approved_spend_cap_microusd"]
    if (
        isinstance(cap, bool)
        or not isinstance(cap, int)
        or cap < 1
        or cap > MAX_INITIAL_LIVE_SPEND_MICROUSD
    ):
        raise TextGenerationLivePreflightError(
            "Live qualification spend cap is missing or exceeds the initial hard limit"
        )

    approved_at = _timestamp(manifest, "approved_at")
    expires_at = _timestamp(manifest, "expires_at")
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if (
        expires_at <= approved_at
        or expires_at - approved_at > MAX_APPROVAL_LIFETIME
        or checked_at < approved_at
        or checked_at >= expires_at
    ):
        raise TextGenerationLivePreflightError(
            "Live qualification approval is not currently valid"
        )

    try:
        pack = FrozenQualificationPack.load(pack_path)
    except TextGenerationQualificationError as exc:
        raise TextGenerationLivePreflightError(
            "Frozen qualification pack failed validation"
        ) from exc
    if manifest["pack_id"] != pack.pack_id or manifest["pack_sha256"] != _file_sha256(
        pack_path
    ):
        raise TextGenerationLivePreflightError("Frozen qualification pack identity drifted")

    try:
        matrix = json.loads(compatibility_matrix_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TextGenerationLivePreflightError(
            "Provider-free compatibility matrix is unavailable or invalid"
        ) from exc
    if (
        not isinstance(matrix, dict)
        or matrix.get("provider_calls_allowed") is not False
        or manifest["compatibility_matrix_id"] != matrix.get("matrix_id")
        or manifest["compatibility_matrix_sha256"]
        != _file_sha256(compatibility_matrix_path)
    ):
        raise TextGenerationLivePreflightError(
            "Provider-free compatibility matrix identity drifted"
        )

    selected_models = pack.models if version == 1 else ("gpt-5.6-luna",)
    raw_models = manifest["models"]
    expected_models = []
    for model_id in selected_models:
        definition = registry.require_model(model_id)
        definition.require_reasoning_effort(reasoning_effort)
        expected_models.append(
            {
                "model_id": model_id,
                "api_model": definition.api_model,
                "pricing_version": definition.pricing.version,
            }
        )
    if raw_models != expected_models:
        raise TextGenerationLivePreflightError(
            "Live qualification model or pricing authority drifted"
        )

    selected_cases = tuple(
        case
        for case in pack.cases
        if version == 1 or case.case_id in _LUNA_GENERATION_CASE_IDS
    )
    if version == 2 and tuple(case.case_id for case in selected_cases) != _LUNA_GENERATION_CASE_IDS:
        raise TextGenerationLivePreflightError(
            "Luna generation qualification case authority is incomplete"
        )
    expected_cases = [
        {"case_id": case.case_id, "input_sha256": case.input_sha256}
        for case in selected_cases
    ]
    if manifest["cases"] != expected_cases:
        raise TextGenerationLivePreflightError(
            "Live qualification case scope or frozen input drifted"
        )

    expected_pairs = [
        {"case_id": case.case_id, "requested_model": model_id}
        for case in selected_cases
        for model_id in selected_models
    ]
    if manifest["authorized_pairs"] != expected_pairs:
        raise TextGenerationLivePreflightError(
            "Live qualification must explicitly authorize the complete pair matrix"
        )

    return AuthorizedLiveQualificationRun(
        run_id=_required_string(manifest, "run_id"),
        approval_reference=_required_string(manifest, "approval_reference"),
        approval_sha256=_sha256_string(manifest, "approval_sha256"),
        approved_spend_cap_microusd=cap,
        approved_at=approved_at,
        expires_at=expires_at,
        reasoning_effort=reasoning_effort,
        authorized_pairs=tuple(
            (pair["case_id"], pair["requested_model"]) for pair in expected_pairs
        ),
    )


__all__ = [
    "AuthorizedLiveQualificationRun",
    "MAX_APPROVAL_LIFETIME",
    "MAX_INITIAL_LIVE_SPEND_MICROUSD",
    "TextGenerationLivePreflightError",
    "load_authorized_live_qualification_run",
]
