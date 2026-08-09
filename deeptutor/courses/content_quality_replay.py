"""Deterministic, provider-free replay for archived C3 generation artifacts."""

from __future__ import annotations

from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .content_quality import (
    C3_BIOLOGY_PROFILE,
    ContentQualityError,
    _answer_supported_by_quote,
    _explanation_supported_by_quote,
    _normalized,
    _OPAQUE_ID,
    validate_c3_output,
)
from .generation_models import (
    GeneratedPracticeOutput,
    GenerationSourceText,
    PracticeGenerationInput,
    PracticeObjectiveEvidenceBinding,
)
from .practice_models import PracticeSourceReceipt

REPLAY_SCHEMA_VERSION = "c3-artifact-failure-ledger-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_material(
    reference_root: Path,
    *,
    source_packet_revision: str,
    filenames: list[str],
) -> list[GenerationSourceText]:
    material: list[GenerationSourceText] = []
    for filename in filenames:
        path = reference_root / "sources" / filename
        text = path.read_text(encoding="utf-8")
        source_id = "src_" + hashlib.sha256(
            f"{source_packet_revision}:{filename}".encode("utf-8")
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


def _request(
    case: dict[str, Any],
    *,
    material: list[GenerationSourceText],
    approved_objective_ids: list[str],
    objective_evidence: list[PracticeObjectiveEvidenceBinding],
) -> PracticeGenerationInput:
    digest = hashlib.sha256(case["case_id"].encode("utf-8")).hexdigest()
    return PracticeGenerationInput(
        operation_id="opg_" + digest[:32],
        owner_user_id="u_c3_replay",
        course_id="crs_" + digest[:32],
        practice_set_id="prc_" + digest[:32],
        practice_set_revision_id="prv_" + digest[:32],
        source_material=material,
        objective_ids=approved_objective_ids,
        requested_objective_ids=case["requested_objective_ids"],
        objective_evidence_bindings=objective_evidence,
        generation_purpose=case["generation_purpose"],
        item_limit=case["item_limit"],
        context_char_limit=24_000,
        focus=case["focus"],
        difficulty="mixed",
        timing_mode="untimed",
        quality_profile=C3_BIOLOGY_PROFILE,
    )


def _status(passed: bool) -> str:
    return "pass" if passed else "fail"


def _question_stage_ledgers(
    request: PracticeGenerationInput,
    output: GeneratedPracticeOutput,
    material: list[GenerationSourceText],
    current_findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    material_by_receipt = {
        (
            item.receipt.source_id,
            item.receipt.source_revision,
            item.receipt.content_sha256,
        ): item.text
        for item in material
    }
    approved = set(request.objective_ids)
    requested = set(request.effective_requested_objective_ids())
    normalized_prompts = [_normalized(item.prompt) for item in output.questions]
    rows: list[dict[str, Any]] = []
    stage_order = [
        "schema_validation",
        "objective_allowlist",
        "request_objective_fidelity",
        "citation_source_allowlist",
        "quote_offset_reachability",
        "answer_support",
        "explanation_support",
        "answer_variants",
        "duplicate_near_duplicate",
        "answer_leakage",
        "opaque_id_leakage",
    ]
    for index, question in enumerate(output.questions, start=1):
        objective_allowlist = bool(question.objective_ids) and all(
            objective in approved for objective in question.objective_ids
        )
        request_fidelity = bool(question.objective_ids) and all(
            objective in requested for objective in question.objective_ids
        )
        source_allowlist = True
        reachable = True
        reachable_quotes: list[str] = []
        if not question.citations:
            source_allowlist = False
            reachable = False
        for citation in question.citations:
            key = (
                citation.source_id,
                citation.source_revision,
                citation.content_sha256,
            )
            source_text = material_by_receipt.get(key)
            if source_text is None:
                source_allowlist = False
                reachable = False
                continue
            quote = citation.locator.get("evidence_quote")
            if not isinstance(quote, str) or not quote or quote not in source_text:
                reachable = False
                continue
            reachable_quotes.append(quote)
        combined_quote = "\n".join(reachable_quotes)
        answers = [
            question.answer_contract.answer,
            *question.answer_contract.accepted_answers,
        ]
        answer_support = bool(combined_quote) and all(
            _answer_supported_by_quote(answer, combined_quote)
            for answer in answers
        )
        explanation_support = bool(combined_quote) and (
            _explanation_supported_by_quote(question.explanation, combined_quote)
        )
        normalized_answers = [_normalized(answer) for answer in answers]
        answer_variants = bool(normalized_answers[0]) and all(
            normalized_answers.count(answer) == 1
            for answer in normalized_answers
            if answer
        )
        duplicate = normalized_prompts.count(normalized_prompts[index - 1]) > 1
        near_duplicate = any(
            other_index != index - 1
            and SequenceMatcher(
                None, normalized_prompts[index - 1], other_prompt
            ).ratio()
            >= 0.92
            for other_index, other_prompt in enumerate(normalized_prompts)
        )
        canonical_answer = _normalized(question.answer_contract.answer)
        answer_leak = bool(canonical_answer) and len(canonical_answer) > 12 and (
            canonical_answer in normalized_prompts[index - 1]
        )
        opaque_id = bool(
            _OPAQUE_ID.search(question.prompt)
            or _OPAQUE_ID.search(question.explanation)
        )
        stages = {
            "schema_validation": "pass",
            "objective_allowlist": _status(objective_allowlist),
            "request_objective_fidelity": _status(request_fidelity),
            "citation_source_allowlist": _status(source_allowlist),
            "quote_offset_reachability": _status(reachable),
            "answer_support": _status(answer_support),
            "explanation_support": _status(explanation_support),
            "answer_variants": _status(answer_variants),
            "duplicate_near_duplicate": _status(not duplicate and not near_duplicate),
            "answer_leakage": _status(not answer_leak),
            "opaque_id_leakage": _status(not opaque_id),
        }
        failures = [name for name in stage_order if stages[name] == "fail"]
        validator_findings = [
            finding
            for finding in current_findings
            if finding["question_index"] in {None, index}
        ]
        rows.append(
            {
                "item_index": index,
                "stages": stages,
                "first_failing_stage": failures[0] if failures else None,
                "all_secondary_failures": failures[1:],
                "current_validator_findings": validator_findings,
                "publication": "fail" if validator_findings else "pass",
            }
        )
    return rows


def replay_manifest(manifest_path: Path) -> dict[str, Any]:
    """Replay every normalized artifact without making a provider request."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reference_root = manifest_path.parent.parent
    material = _source_material(
        reference_root,
        source_packet_revision=manifest["source_packet_revision"],
        filenames=manifest["source_files"],
    )
    evidence_fixture = json.loads(
        (reference_root / "objective_evidence_roles_v2.json").read_text(
            encoding="utf-8"
        )
    )
    objective_evidence = [
        PracticeObjectiveEvidenceBinding.model_validate(binding)
        for binding in evidence_fixture["bindings"]
    ]
    cases: list[dict[str, Any]] = []
    for case in manifest["artifacts"]:
        artifact_path = reference_root / case["path"]
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        request = _request(
            case,
            material=material,
            approved_objective_ids=manifest["approved_objective_ids"],
            objective_evidence=objective_evidence,
        )
        raw_response_present = "raw_provider_response" in artifact
        normalized_payload = artifact.get("output")
        record: dict[str, Any] = {
            "case_id": case["case_id"],
            "archived_artifact": str(case["path"]),
            "archived_artifact_sha256": _sha256(artifact_path),
            "raw_provider_response": (
                artifact["raw_provider_response"]
                if raw_response_present
                else None
            ),
            "raw_response_provenance": (
                "preserved" if raw_response_present else "not_preserved"
            ),
            "normalized_response": normalized_payload,
            "previous_validator_result": case["previous_validator_result"],
            "stages": {
                "provider_response_parsing": (
                    "pass" if raw_response_present else "unavailable"
                ),
                "provider_schema_validation": (
                    "unavailable" if not raw_response_present else "not_replayed"
                ),
                "adapter_normalization": (
                    "pass_inferred_from_archived_normalized_output"
                    if normalized_payload is not None
                    else "unavailable"
                ),
            },
        }
        if normalized_payload is None:
            record.update(
                {
                    "first_failing_stage": "RAW_RESPONSE_NOT_PRESERVED",
                    "all_secondary_failures": [
                        "NORMALIZED_RESPONSE_NOT_PRESERVED"
                    ],
                    "current_validator_result": {
                        "status": "UNAVAILABLE",
                        "findings": [],
                    },
                    "items": [],
                }
            )
            cases.append(record)
            continue
        try:
            output = GeneratedPracticeOutput.model_validate(normalized_payload)
        except ValidationError as exc:
            record.update(
                {
                    "first_failing_stage": "NORMALIZED_SCHEMA_VALIDATION",
                    "all_secondary_failures": [],
                    "normalized_schema_errors": exc.errors(
                        include_url=False, include_input=False
                    ),
                    "current_validator_result": {
                        "status": "UNAVAILABLE",
                        "findings": [],
                    },
                    "items": [],
                }
            )
            cases.append(record)
            continue
        current_findings: list[dict[str, Any]] = []
        try:
            validate_c3_output(request=request, output=output, material=material)
            current_status = "PASS"
        except ContentQualityError as exc:
            current_status = "REJECT"
            current_findings = [
                {
                    "code": finding.code,
                    "question_index": finding.question_index,
                    "detail": finding.detail,
                }
                for finding in exc.findings
            ]
        request_contract_stage = (
            "pass" if output.request_contract is not None else "fail"
        )
        record["stages"].update(
            {
                "normalized_schema_validation": "pass",
                "request_contract": request_contract_stage,
            }
        )
        record.update(
            {
                "first_failing_stage": (
                    "REQUEST_CONTRACT_MISSING"
                    if request_contract_stage == "fail"
                    else None
                ),
                "all_secondary_failures": [
                    f"{finding['code']}"
                    + (
                        f"[{finding['question_index']}]"
                        if finding["question_index"] is not None
                        else ""
                    )
                    for finding in current_findings
                    if finding["code"] != "REQUEST_CONTRACT_MISSING"
                ],
                "current_validator_result": {
                    "status": current_status,
                    "findings": current_findings,
                },
                "items": _question_stage_ledgers(
                    request, output, material, current_findings
                ),
            }
        )
        cases.append(record)
    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "provider_requests_made": 0,
        "source_packet_revision": manifest["source_packet_revision"],
        "replay_contract_manifest": str(manifest_path.name),
        "cases": cases,
    }


__all__ = ["REPLAY_SCHEMA_VERSION", "replay_manifest"]
