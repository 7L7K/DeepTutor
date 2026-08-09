#!/usr/bin/env python3
"""Run one bounded, first-attempt-only C3 Luna probe and archive its receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from deeptutor.courses.content_quality import ContentQualityError, validate_c3_output
from deeptutor.courses.generation_models import (
    GenerationSourceText,
    PracticeGenerationInput,
    PracticeObjectiveEvidenceBinding,
    build_practice_generation_request_contract,
)
from deeptutor.courses.generation_provider import (
    C3_PROMPT_VERSION,
    C3_PUBLICATION_MODEL,
    C3_SCHEMA_VERSION,
    OpenAIPracticeGenerationProvider,
)
from deeptutor.courses.practice_models import PracticeSourceReceipt
from deeptutor.courses.provider_usage import (
    ProviderUsageLedger,
    ProviderUsagePolicy,
)
from deeptutor.services.config.text_generation_registry import (
    TextGenerationRegistry,
    default_text_generation_catalog,
)

SOURCE_PACKET_REVISION = "reference-course-c3-v1"
APPROVED_OBJECTIVE_IDS = ["OBJ-RESP-01", "OBJ-RESP-02", "OBJ-RESP-03"]
SOURCE_FILENAMES = ["lecture_06_transcript.md", "lecture_06_slides.md"]
OBJECTIVE_EVIDENCE_FILENAME = "objective_evidence.json"


class _RecordingResponses:
    def __init__(self, inner: object, record: dict[str, Any]) -> None:
        self._inner = inner
        self._record = record

    def create(self, **kwargs: Any) -> object:
        self._record["provider_request_attempted"] = True
        try:
            response = self._inner.create(**kwargs)  # type: ignore[attr-defined]
        except Exception as exc:
            body = getattr(exc, "body", None)
            safe_body = body if isinstance(body, dict) else {}
            self._record["provider_error"] = {
                "error_class": type(exc).__name__,
                "status_code": getattr(exc, "status_code", None),
                "request_id": getattr(exc, "request_id", None),
                "type": safe_body.get("type"),
                "code": safe_body.get("code"),
                "param": safe_body.get("param"),
            }
            raise
        output_text = str(getattr(response, "output_text", "") or "")
        self._record.update(
            {
                "response_id": str(getattr(response, "id", "") or "") or None,
                "response_model": str(getattr(response, "model", "") or "") or None,
                "response_status": str(getattr(response, "status", "") or "") or None,
                "raw_provider_output_text": output_text,
                "raw_provider_output_sha256": hashlib.sha256(
                    output_text.encode("utf-8")
                ).hexdigest(),
            }
        )
        return response


def _material(reference_root: Path) -> list[GenerationSourceText]:
    material: list[GenerationSourceText] = []
    for filename in SOURCE_FILENAMES:
        text = (reference_root / "sources" / filename).read_text(encoding="utf-8")
        source_id = "src_" + hashlib.sha256(
            f"{SOURCE_PACKET_REVISION}:{filename}".encode("utf-8")
        ).hexdigest()[:32]
        material.append(
            GenerationSourceText(
                receipt=PracticeSourceReceipt(
                    source_id=source_id,
                    source_revision=1,
                    content_sha256=hashlib.sha256(
                        text.encode("utf-8")
                    ).hexdigest(),
                ),
                text=text,
            )
        )
    return material


def _objective_evidence(
    reference_root: Path,
) -> list[PracticeObjectiveEvidenceBinding]:
    payload = json.loads(
        (reference_root / OBJECTIVE_EVIDENCE_FILENAME).read_text(encoding="utf-8")
    )
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "c3-objective-evidence-v1"
        or payload.get("source_packet_revision") != SOURCE_PACKET_REVISION
        or not isinstance(payload.get("bindings"), list)
    ):
        raise ValueError("C3 objective evidence fixture is invalid")
    return [
        PracticeObjectiveEvidenceBinding.model_validate(binding)
        for binding in payload["bindings"]
    ]


def _probe_contract(mode: str) -> dict[str, Any]:
    contracts = {
        "unsupported": {
            "requested_objective_ids": [
                "OBJ-PHOTO-01",
                "OBJ-MITO-INHERIT-01",
            ],
            "item_limit": 1,
            "focus": "photosynthesis and mitochondrial inheritance",
            "generation_purpose": "practice",
        },
        "supported-one": {
            "requested_objective_ids": ["OBJ-RESP-02"],
            "item_limit": 1,
            "focus": "oxygen as the terminal electron acceptor in aerobic respiration",
            "generation_purpose": "practice",
        },
        "primary": {
            "requested_objective_ids": APPROVED_OBJECTIVE_IDS,
            "item_limit": 5,
            "focus": "cellular respiration",
            "generation_purpose": "practice",
        },
        "repeat": {
            "requested_objective_ids": APPROVED_OBJECTIVE_IDS,
            "item_limit": 5,
            "focus": "cellular respiration",
            "generation_purpose": "practice",
        },
        "remediation": {
            "requested_objective_ids": ["OBJ-RESP-02", "OBJ-RESP-03"],
            "item_limit": 2,
            "focus": (
                "remediate confusion about oxygen as terminal electron acceptor "
                "and fermentation versus aerobic respiration"
            ),
            "generation_purpose": "remediation",
        },
    }
    return contracts[mode]


def _request(
    mode: str,
    material: list[GenerationSourceText],
    objective_evidence: list[PracticeObjectiveEvidenceBinding],
) -> PracticeGenerationInput:
    contract = _probe_contract(mode)
    digest = hashlib.sha256(
        f"c3-luna-objective-evidence-v1:{mode}".encode("utf-8")
    ).hexdigest()
    return PracticeGenerationInput(
        operation_id="opg_" + digest[:32],
        owner_user_id="u_c3_luna_probe",
        course_id="crs_" + digest[:32],
        practice_set_id="prc_" + digest[:32],
        practice_set_revision_id="prv_" + digest[:32],
        source_material=material,
        objective_ids=APPROVED_OBJECTIVE_IDS,
        requested_objective_ids=contract["requested_objective_ids"],
        objective_evidence_bindings=objective_evidence,
        generation_purpose=contract["generation_purpose"],
        item_limit=contract["item_limit"],
        context_char_limit=24_000,
        focus=contract["focus"],
        difficulty="mixed",
        timing_mode="untimed",
        quality_profile="c3-biology-v1",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=["unsupported", "supported-one", "primary", "repeat", "remediation"],
    )
    parser.add_argument("--reference-root", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    args = parser.parse_args()
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not configured")
    material = _material(args.reference_root.resolve())
    objective_evidence = _objective_evidence(args.reference_root.resolve())
    request = _request(args.mode, material, objective_evidence)
    registry = TextGenerationRegistry.from_catalog(
        {"text_generation": default_text_generation_catalog()}
    )
    resolved = registry.resolve(
        "practice_generation",
        required_capabilities={"responses", "structured_outputs"},
    )
    if resolved.model.api_model != C3_PUBLICATION_MODEL:
        raise SystemExit("C3 Luna policy is not active")
    ledger = ProviderUsageLedger(args.state_dir.resolve() / "provider_usage.db")
    ledger.configure(
        ProviderUsagePolicy(
            enabled=True,
            max_lifetime_cost_microusd=50_000,
            pricing_version=resolved.model.pricing.version,
        )
    )
    recorder: dict[str, Any] = {"provider_request_attempted": False}

    def client_factory(**kwargs: Any) -> object:
        from openai import OpenAI

        client = OpenAI(**kwargs)
        return SimpleNamespace(
            responses=_RecordingResponses(client.responses, recorder)
        )

    provider = OpenAIPracticeGenerationProvider(
        api_key=api_key,
        model=C3_PUBLICATION_MODEL,
        ledger=ledger,
        resolved_generation=resolved,
        client_factory=client_factory,
    )
    artifact: dict[str, Any] = {
        "schema_version": "c3-luna-probe-receipt-v2",
        "case": args.mode,
        "fixture": "Biology 101 / fall-2026",
        "source_packet_revision": SOURCE_PACKET_REVISION,
        "requested_model": C3_PUBLICATION_MODEL,
        "reasoning_effort": resolved.reasoning_effort,
        "prompt_version": C3_PROMPT_VERSION,
        "provider_schema_version": C3_SCHEMA_VERSION,
        "store": False,
        "automatic_retries": 0,
        "first_attempt": True,
        "request_contract": build_practice_generation_request_contract(
            request
        ).model_dump(mode="json"),
        "objective_evidence_contract": [
            binding.model_dump(mode="json")
            for binding in request.effective_objective_evidence_bindings()
        ],
    }
    exit_code = 1
    try:
        output = provider.generate(request)
        artifact["output"] = output.model_dump(mode="json")
        if output.outcome == "abstain":
            artifact["publication_status"] = "ABSTAIN"
            artifact["validation_status"] = "NOT_APPLICABLE"
            exit_code = 0
        else:
            try:
                validated = validate_c3_output(
                    request=request,
                    output=output,
                    material=material,
                )
                artifact["validated_output"] = validated.model_dump(mode="json")
                artifact["publication_status"] = "PASS"
                artifact["validation_status"] = "PASS"
                exit_code = 0
            except ContentQualityError as exc:
                artifact["publication_status"] = "REJECT"
                artifact["validation_status"] = "REJECT"
                artifact["quality_findings"] = [
                    {
                        "code": finding.code,
                        "question_index": finding.question_index,
                        "detail": finding.detail,
                    }
                    for finding in exc.findings
                ]
    except Exception as exc:
        artifact["publication_status"] = "ERROR"
        artifact["validation_status"] = "NOT_RUN"
        artifact["error_class"] = type(exc).__name__
    artifact["provider_runtime"] = recorder
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "artifact": str(args.artifact),
                "case": args.mode,
                "provider_request_attempted": recorder[
                    "provider_request_attempted"
                ],
                "publication_status": artifact["publication_status"],
                "validation_status": artifact["validation_status"],
            },
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
