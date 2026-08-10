#!/usr/bin/env python3
"""Run the final bounded C3 five-question and remediation campaign.

This file is a campaign harness only. It reuses the frozen H3B2 individual
contracts and provider ledger, but does not alter learner-facing generation or
assessment behavior.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import difflib
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from deeptutor.courses.generation_models import (
    GenerationSourceText,
    PracticeGenerationInput,
    build_practice_generation_request_contract,
)
from deeptutor.courses.practice_models import normalize_bounded_short_answer
from scripts.run_c3_h3_model_qualification import (
    CAMPAIGN_ID as H3_CAMPAIGN_ID,
    CampaignClient,
    CampaignStop,
    GENERATION_OUTPUT_LIMIT,
    MAX_PROVIDER_SPEND_MICROUSD,
    MODEL,
    REASONING,
    STORE,
    _call_with_transport_retries,
    _judge_result,
    _load_generation_contracts,
    _material,
    _objective_evidence,
    _qualified_candidate,
    _write_json,
)
from scripts.run_c3_luna_probe import APPROVED_OBJECTIVE_IDS


FINAL_CAMPAIGN_ID = "2026-08-09-teeechr-c3-final-learning-loop-v1"
FINAL_CONTRACT_ID = "c3-final-learning-loop-v1"
MAX_SET_CANDIDATES = 3
OPTION_KEYS = ("A", "B", "C", "D")
LEAKED_IDENTIFIER = re.compile(
    r"(?:src|ev|qst|grd|prv|prc|ati|OBJ-RESP)[_-][A-Za-z0-9_-]+"
)
SET_HARD_FAILURES = {
    "missing_approved_objective",
    "material_duplicate",
    "repeated_answer_cue",
    "cross_question_leakage",
    "objective_imbalance",
    "paraphrase_set",
    "wrong_course_scope",
}


class FinalCampaignStop(RuntimeError):
    """Fail-closed final campaign stop."""


@dataclass(frozen=True)
class ObjectiveContract:
    objective_id: str
    contract_id: str
    question_type: str
    cognitive_target: str
    required_claim_ids: tuple[str, ...]
    required_evidence_ids: tuple[str, ...]
    accepted_answers: tuple[str, ...]
    maximum_word_count_delta: int


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _objective_contracts(reference_root: Path) -> dict[str, ObjectiveContract]:
    v4 = _load_generation_contracts(reference_root)
    amendment = json.loads(
        (reference_root / "reviewer_amendments/obj-resp-01-bounded-short-answer-v2.json").read_text(
            encoding="utf-8"
        )
    )
    answer_contract = amendment["candidate_answer_contract"]
    contracts = {
        "OBJ-RESP-01": ObjectiveContract(
            objective_id="OBJ-RESP-01",
            contract_id="ac_resp_01_transition_v1",
            question_type="bounded_short_answer_v1",
            cognitive_target="Explain the role of pyruvate oxidation as the transition between glycolysis and the citric acid cycle.",
            required_claim_ids=("pyruvate_to_acetyl_coa",),
            required_evidence_ids=("ev_resp01_conversion",),
            accepted_answers=tuple(answer_contract["accepted_normalized_answers"]),
            maximum_word_count_delta=0,
        ),
        "OBJ-RESP-02": ObjectiveContract(
            objective_id="OBJ-RESP-02",
            contract_id=v4["OBJ-RESP-02"]["contract_id"],
            question_type="single_choice_v1",
            cognitive_target=v4["OBJ-RESP-02"]["cognitive_target"],
            required_claim_ids=tuple(v4["OBJ-RESP-02"]["required_claim_ids"]),
            required_evidence_ids=tuple(v4["OBJ-RESP-02"]["required_evidence_ids"]),
            accepted_answers=(),
            maximum_word_count_delta=3,
        ),
        "OBJ-RESP-03": ObjectiveContract(
            objective_id="OBJ-RESP-03",
            contract_id=v4["OBJ-RESP-03"]["contract_id"],
            question_type="single_choice_v1",
            cognitive_target=v4["OBJ-RESP-03"]["cognitive_target"],
            required_claim_ids=tuple(v4["OBJ-RESP-03"]["required_claim_ids"]),
            required_evidence_ids=tuple(v4["OBJ-RESP-03"]["required_evidence_ids"]),
            accepted_answers=(),
            maximum_word_count_delta=3,
        ),
    }
    if set(contracts) != set(APPROVED_OBJECTIVE_IDS):
        raise FinalCampaignStop("FINAL_CONTRACT_OBJECTIVE_SET_INVALID")
    return contracts


def _request(
    *,
    campaign_id: str,
    phase: str,
    candidate_number: int,
    material: list[GenerationSourceText],
    evidence: list[Any],
    purpose: str,
    objective_ids: list[str],
    required_claims: dict[str, list[str]],
    accepted_answers: dict[str, list[str]],
    item_limit: int,
    focus: str,
) -> PracticeGenerationInput:
    operation_digest = _digest(
        {
            "campaign_id": campaign_id,
            "phase": phase,
            "candidate_number": candidate_number,
        }
    )
    return PracticeGenerationInput(
        operation_id="opg_" + operation_digest[:32],
        owner_user_id="u_c3_h3_final_quality",
        course_id="crs_" + operation_digest[:32],
        practice_set_id="prc_" + operation_digest[:32],
        practice_set_revision_id="prv_" + operation_digest[:32],
        source_material=material,
        objective_ids=APPROVED_OBJECTIVE_IDS,
        requested_objective_ids=objective_ids,
        objective_evidence_bindings=evidence,
        required_claim_ids_by_objective=required_claims,
        required_accepted_answers_by_objective=accepted_answers,
        generation_purpose=purpose,
        item_limit=item_limit,
        context_char_limit=24_000,
        focus=focus,
        difficulty="mixed",
        timing_mode="untimed",
        quality_profile="c3-biology-v1",
    )


def _question_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "question_type",
            "prompt",
            "answer_text",
            "accepted_answers",
            "options",
            "correct_option_key",
            "explanation",
            "objective_ids",
            "citation_evidence_ids",
            "remediation_purpose",
        ],
        "properties": {
            "question_type": {
                "type": "string",
                "enum": ["bounded_short_answer_v1", "single_choice_v1"],
            },
            "prompt": {"type": "string", "minLength": 1, "maxLength": 12000},
            "answer_text": {"type": "string", "maxLength": 4000},
            "accepted_answers": {
                "type": "array",
                "maxItems": 8,
                "items": {"type": "string", "maxLength": 4000},
            },
            "options": {
                "type": "array",
                "minItems": 0,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["option_key", "text"],
                    "properties": {
                        "option_key": {"type": "string", "enum": list(OPTION_KEYS)},
                        "text": {"type": "string", "minLength": 1, "maxLength": 4000},
                    },
                },
            },
            "correct_option_key": {"type": "string", "enum": ["", *OPTION_KEYS]},
            "explanation": {"type": "string", "minLength": 1, "maxLength": 12000},
            "objective_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {"type": "string", "enum": list(APPROVED_OBJECTIVE_IDS)},
            },
            "citation_evidence_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": {"type": "string"},
            },
            "remediation_purpose": {
                "type": "string",
                "enum": [
                    "none",
                    "direct_correction",
                    "contrast",
                    "prerequisite_refresh",
                    "delayed_verification",
                ],
            },
        },
    }


def _generation_schema(request_contract: dict[str, Any], item_limit: int, contract_ids: list[str]) -> dict[str, Any]:
    question = _question_schema()
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["campaign_contract_id", "assessment_contract_ids", "request_contract", "outcome", "abstain_reason", "questions"],
        "properties": {
            "campaign_contract_id": {"type": "string", "enum": [FINAL_CONTRACT_ID]},
            "assessment_contract_ids": {"type": "array", "minItems": len(contract_ids), "maxItems": len(contract_ids), "items": {"type": "string", "enum": contract_ids}},
            "request_contract": {
                "type": "object",
                "additionalProperties": False,
                "required": ["request_contract_id", "requested_objective_ids", "source_scope_hash", "generation_purpose"],
                "properties": {
                    "request_contract_id": {"type": "string", "enum": [request_contract["request_contract_id"]]},
                    "requested_objective_ids": {"type": "array", "minItems": len(request_contract["requested_objective_ids"]), "maxItems": len(request_contract["requested_objective_ids"]), "items": {"type": "string", "enum": request_contract["requested_objective_ids"]}},
                    "source_scope_hash": {"type": "string", "enum": [request_contract["source_scope_hash"]]},
                    "generation_purpose": {"type": "string", "enum": [request_contract["generation_purpose"]]},
                },
            },
            "outcome": {"type": "string", "enum": ["generated", "abstain"]},
            "abstain_reason": {"type": ["string", "null"], "enum": [None, "unsupported_by_allowed_sources"]},
            "questions": {"type": "array", "minItems": item_limit, "maxItems": item_limit, "items": question},
        },
    }


def _evidence_map(request: PracticeGenerationInput) -> dict[str, Any]:
    return {
        item.evidence_id: item
        for binding in request.effective_objective_evidence_bindings()
        for item in binding.support_evidence
    }


def _deterministic_question_failure(
    question: object,
    *,
    contract: ObjectiveContract,
    request: PracticeGenerationInput,
) -> tuple[str, str]:
    if not isinstance(question, dict):
        return "MODEL_FORMAT_FAILURE", "question is not an object"
    required = {
        "question_type", "prompt", "answer_text", "accepted_answers", "options",
        "correct_option_key", "explanation", "objective_ids", "citation_evidence_ids",
        "remediation_purpose",
    }
    if set(question) != required:
        return "MODEL_FORMAT_FAILURE", "question shape is invalid"
    if question["objective_ids"] != [contract.objective_id]:
        return "DETERMINISTIC_CONTRACT_FAILURE", "question objective is outside requested scope"
    options = question["options"]
    accepted_answers = question["accepted_answers"]
    if not isinstance(options, list) or not isinstance(accepted_answers, list):
        return "MODEL_FORMAT_FAILURE", "question options or accepted answers are not lists"
    if LEAKED_IDENTIFIER.search(" ".join([
        str(question["prompt"]), str(question["answer_text"]), str(question["explanation"]),
        *[str(item.get("text", "")) for item in options if isinstance(item, dict)],
        *[str(item) for item in accepted_answers],
    ])):
        return "DETERMINISTIC_CONTRACT_FAILURE", "opaque ID leaked into learner text"
    evidence = _evidence_map(request)
    citation_ids = question["citation_evidence_ids"]
    if not isinstance(citation_ids, list) or not citation_ids or len(set(citation_ids)) != len(citation_ids):
        return "EVIDENCE_FAILURE", "citation evidence IDs are invalid"
    selected = [evidence.get(item) for item in citation_ids]
    if any(item is None for item in selected):
        return "EVIDENCE_FAILURE", "citation evidence is outside the approved source set"
    covered_claims = {claim for item in selected if item for claim in item.claim_ids}
    if not set(contract.required_claim_ids).issubset(covered_claims):
        return "EVIDENCE_FAILURE", "required claims are not covered"
    roles = {role for item in selected if item for role in item.supports}
    if not {"answer", "explanation"}.issubset(roles):
        return "EVIDENCE_FAILURE", "answer and explanation support are not covered"
    if question["question_type"] != contract.question_type:
        return "DETERMINISTIC_CONTRACT_FAILURE", "question type does not match frozen objective contract"
    if question["remediation_purpose"] not in {"none", "direct_correction", "contrast", "prerequisite_refresh", "delayed_verification"}:
        return "DETERMINISTIC_CONTRACT_FAILURE", "remediation purpose is invalid"
    if contract.question_type == "bounded_short_answer_v1":
        if options or question["correct_option_key"] or not isinstance(question["answer_text"], str) or not question["answer_text"].strip():
            return "DETERMINISTIC_CONTRACT_FAILURE", "bounded short-answer shape is invalid"
        if not accepted_answers or any(not isinstance(item, str) or not item.strip() for item in accepted_answers):
            return "GRADING_CONTRACT_FAILURE", "bounded short-answer accepted answers are missing"
        normalized = {normalize_bounded_short_answer(item) for item in accepted_answers}
        if not set(contract.accepted_answers).issubset(normalized):
            return "GRADING_CONTRACT_FAILURE", "frozen accepted answer variants are missing"
    else:
        if question["answer_text"] or question["accepted_answers"] or len(options) != 4:
            return "DETERMINISTIC_CONTRACT_FAILURE", "single-choice shape is invalid"
        keys = [item.get("option_key") for item in options if isinstance(item, dict)]
        if set(keys) != set(OPTION_KEYS) or question["correct_option_key"] not in keys:
            return "DETERMINISTIC_CONTRACT_FAILURE", "single-choice keys are invalid"
        texts = [item.get("text") for item in options]
        if any(not isinstance(item, str) or not item.strip() for item in texts):
            return "DISTRACTOR_FAILURE", "single-choice options are empty"
        if len({item.casefold().strip() for item in texts}) != 4:
            return "DISTRACTOR_FAILURE", "single-choice options are duplicated"
        counts = [len(item.split()) for item in texts]
        if max(counts) - min(counts) > contract.maximum_word_count_delta:
            return "DISTRACTOR_FAILURE", "single-choice option lengths exceed frozen tolerance"
        correct_text = next(item["text"] for item in options if item["option_key"] == question["correct_option_key"])
        if correct_text.casefold().strip() in question["prompt"].casefold():
            return "ANSWER_CUE", "prompt reveals the correct option"
    return "", ""


def _set_failure(
    questions: list[dict[str, Any]],
    *,
    phase: str,
    allocation: dict[str, int],
    contracts: dict[str, ObjectiveContract],
    request: PracticeGenerationInput,
) -> tuple[str, str, list[dict[str, Any]]]:
    if not isinstance(questions, list):
        return "MODEL_FORMAT_FAILURE", "questions is not a list", []
    expected_count = 5 if phase in {"primary", "repeat"} else 2
    if len(questions) < 2 or len(questions) > (5 if phase in {"primary", "repeat"} else 4) or (phase in {"primary", "repeat"} and len(questions) != expected_count):
        return "MODEL_FORMAT_FAILURE", "question count does not match the phase", []
    failures: list[dict[str, Any]] = []
    objective_counts: dict[str, int] = {}
    prompts: list[str] = []
    for index, question in enumerate(questions, start=1):
        objective_id = question.get("objective_ids", [None])[0] if isinstance(question, dict) else None
        if objective_id not in contracts:
            failures.append({"index": index, "failure_class": "DETERMINISTIC_CONTRACT_FAILURE", "detail": "unknown objective"})
            continue
        objective_counts[objective_id] = objective_counts.get(objective_id, 0) + 1
        failure_class, detail = _deterministic_question_failure(question, contract=contracts[objective_id], request=request)
        if failure_class:
            failures.append({"index": index, "failure_class": failure_class, "detail": detail})
        prompt = str(question.get("prompt", "")).casefold().strip()
        if prompt in prompts:
            failures.append({"index": index, "failure_class": "DUPLICATE_FAILURE", "detail": "exact duplicate prompt"})
        if any(difflib.SequenceMatcher(None, prompt, prior).ratio() >= 0.88 for prior in prompts):
            failures.append({"index": index, "failure_class": "DUPLICATE_FAILURE", "detail": "near-duplicate prompt"})
        prompts.append(prompt)
    if phase in {"primary", "repeat"} and objective_counts != allocation:
        failures.append({"failure_class": "OBJECTIVE_ALLOCATION_FAILURE", "detail": f"expected {allocation}, got {objective_counts}"})
    if phase == "remediation":
        missing = sorted(set(allocation) - set(objective_counts))
        unapproved = sorted(set(objective_counts) - set(allocation))
        if missing or unapproved:
            failures.append({
                "failure_class": "OBJECTIVE_ALLOCATION_FAILURE",
                "detail": f"remediation must cover exact misses; missing={missing}, unapproved={unapproved}",
            })
    if failures:
        first = failures[0]
        return str(first["failure_class"]), str(first["detail"]), failures
    return "", "", []


def _individual_judge_schema() -> dict[str, Any]:
    from scripts.run_c3_h3_model_qualification import _judge_schema

    return _judge_schema()


def _individual_judge_instructions() -> str:
    return (
        "You are an independent blinded educational evaluator. Judge one question "
        "against its frozen objective, evidence, and grading contract. Score the "
        "existing H3 dimensions from 0 to 4. Factual correctness, Course evidence "
        "support, single correct answer, and grading fairness must each be 4. All "
        "other dimensions must be at least 3. For bounded short answers, treat "
        "distractor quality as answer-boundary clarity. Add a hard failure for any "
        "incorrect key, unsupported claim, multiple defensible answers, wrong scope, "
        "citation mismatch, answer leakage, opaque learner ID, or misleading "
        "explanation. Return only the structured judge object."
    )


def _set_judge_schema() -> dict[str, Any]:
    dimensions = {
        name: {"type": "integer", "minimum": 0, "maximum": 4}
        for name in (
            "objective_coverage", "question_distinctness", "cognitive_variety",
            "difficulty_balance", "cross_question_answer_cues", "redundancy",
            "assessment_coherence", "course_scope", "overall_student_usefulness",
        )
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["dimensions", "hard_failures", "failure_class", "verdict", "rationale"],
        "properties": {
            "dimensions": {"type": "object", "additionalProperties": False, "required": list(dimensions), "properties": dimensions},
            "hard_failures": {"type": "array", "items": {"type": "string", "enum": sorted(SET_HARD_FAILURES)}},
            "failure_class": {"type": ["string", "null"], "enum": [None, "SET_COHERENCE_FAILURE", "SET_SCOPE_FAILURE", "SET_REDUNDANCY_FAILURE"]},
            "verdict": {"type": "string", "enum": ["QUALIFY", "REJECT_RETRYABLE", "REJECT_CONTRACT"]},
            "rationale": {"type": "string", "minLength": 1, "maxLength": 6000},
        },
    }


def _set_judge_instructions() -> str:
    return (
        "You are an independent blinded set-level educational evaluator. Judge the "
        "complete question set, not individual fluency. Score every requested set "
        "dimension from 0 to 4; every dimension must be at least 3 for QUALIFY. "
        "Use hard failures for missing approved objectives, material duplicates, "
        "repeated answer cues, cross-question leakage, objective imbalance, an "
        "obvious paraphrase set, or wrong Course scope. Return only the structured "
        "judge object."
    )


def _judge_question(
    client: CampaignClient,
    *,
    question: dict[str, Any],
    objective_contract: ObjectiveContract,
    request: PracticeGenerationInput,
    phase: str,
    candidate_number: int,
    question_number: int,
    artifact_root: Path,
    campaign_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    input_payload = {
        "phase": phase,
        "objective": objective_contract.__dict__,
        "approved_evidence": [
            item.model_dump(mode="json")
            for binding in request.effective_objective_evidence_bindings()
            if binding.objective_id == objective_contract.objective_id
            for item in binding.support_evidence
        ],
        "question": question,
    }
    records: list[dict[str, Any]] = []
    verdicts: list[tuple[str, str | None, str]] = []
    for judge_number in (1, 2):
        op = "opg_" + _digest({"campaign": campaign_id, "phase": phase, "candidate": candidate_number, "question": question_number, "judge": judge_number})[:32]
        raw, receipt, events = _call_with_transport_retries(
            client,
            purpose="question_judge",
            operation_id=op,
            instructions=_individual_judge_instructions(),
            input_payload=input_payload,
            schema=_individual_judge_schema(),
            output_limit=3_000,
            artifact_root=artifact_root,
        )
        result = _judge_result(raw)
        verdicts.append(result)
        records.append({"judge_number": judge_number, "provider_receipt": receipt.as_dict(), "raw_output": raw, "transport_events": events})
    if verdicts[0][0] != verdicts[1][0]:
        op = "opg_" + _digest({"campaign": campaign_id, "phase": phase, "candidate": candidate_number, "question": question_number, "judge": "tie-break"})[:32]
        raw, receipt, events = _call_with_transport_retries(
            client,
            purpose="question_judge_tie_break",
            operation_id=op,
            instructions=_individual_judge_instructions(),
            input_payload=input_payload,
            schema=_individual_judge_schema(),
            output_limit=3_000,
            artifact_root=artifact_root,
        )
        result = _judge_result(raw)
        verdicts.append(result)
        records.append({"judge_number": 3, "provider_receipt": receipt.as_dict(), "raw_output": raw, "transport_events": events})
    _write_json(
        artifact_root / phase / f"candidate-{candidate_number}-question-{question_number}-judges.json",
        {"schema_version": "c3-final-question-judges-v1", "phase": phase, "candidate_number": candidate_number, "question_number": question_number, "judges": records},
    )
    if any(item[0] != "QUALIFY" for item in verdicts):
        return {"status": "REJECT_RETRYABLE", "failure_class": next((item[1] for item in verdicts if item[1]), "PEDAGOGY_FAILURE")}, records
    return {"status": "MODEL_QUALIFIED"}, records


def _judge_set(
    client: CampaignClient,
    *,
    phase: str,
    candidate_number: int,
    questions: list[dict[str, Any]],
    allocation: dict[str, int],
    artifact_root: Path,
    campaign_id: str,
) -> dict[str, Any]:
    payload = {"phase": phase, "allocation": allocation, "questions": questions}
    records: list[dict[str, Any]] = []
    verdicts: list[str] = []
    for judge_number in (1, 2):
        op = "opg_" + _digest({"campaign": campaign_id, "phase": phase, "candidate": candidate_number, "judge": f"set-{judge_number}"})[:32]
        raw, receipt, events = _call_with_transport_retries(
            client,
            purpose="set_judge",
            operation_id=op,
            instructions=_set_judge_instructions(),
            input_payload=payload,
            schema=_set_judge_schema(),
            output_limit=3_000,
            artifact_root=artifact_root,
        )
        if not isinstance(raw, dict) or set(raw) != {"dimensions", "hard_failures", "failure_class", "verdict", "rationale"}:
            raise FinalCampaignStop("SET_JUDGE_FORMAT_FAILURE")
        dimensions = raw["dimensions"]
        if not isinstance(dimensions, dict) or set(dimensions) != set(_set_judge_schema()["properties"]["dimensions"]["required"]):
            raise FinalCampaignStop("SET_JUDGE_FORMAT_FAILURE")
        if any(not isinstance(value, int) or not 0 <= value <= 4 for value in dimensions.values()):
            raise FinalCampaignStop("SET_JUDGE_FORMAT_FAILURE")
        verdict = raw["verdict"]
        if verdict == "QUALIFY" and (raw["hard_failures"] or any(value < 3 for value in dimensions.values())):
            raise FinalCampaignStop("SET_JUDGE_CONTRACT_INCONSISTENT")
        verdicts.append(verdict)
        records.append({"judge_number": judge_number, "provider_receipt": receipt.as_dict(), "raw_output": raw, "transport_events": events})
    if verdicts[0] != verdicts[1]:
        op = "opg_" + _digest({"campaign": campaign_id, "phase": phase, "candidate": candidate_number, "judge": "set-tie-break"})[:32]
        raw, receipt, events = _call_with_transport_retries(
            client,
            purpose="set_judge_tie_break",
            operation_id=op,
            instructions=_set_judge_instructions(),
            input_payload=payload,
            schema=_set_judge_schema(),
            output_limit=3_000,
            artifact_root=artifact_root,
        )
        verdicts.append(raw["verdict"])
        records.append({"judge_number": 3, "provider_receipt": receipt.as_dict(), "raw_output": raw, "transport_events": events})
    _write_json(
        artifact_root / phase / f"candidate-{candidate_number}-set-judges.json",
        {"schema_version": "c3-final-set-judges-v1", "phase": phase, "candidate_number": candidate_number, "judges": records},
    )
    return {"status": "MODEL_QUALIFIED" if all(item == "QUALIFY" for item in verdicts) else "REJECT_RETRYABLE", "judge_count": len(verdicts)}


def _instructions(phase: str, contracts: dict[str, ObjectiveContract], allocation: dict[str, int], miss_context: list[dict[str, Any]] | None) -> str:
    return (
        "Generate only the requested complete Course Practice set. Use the exact "
        "approved objective allocation and frozen assessment contracts supplied in "
        "the input. Evidence IDs are machine metadata only and must never appear in "
        "learner-visible prompt, answer, option, explanation, accepted-answer, or "
        "hint text. Do not substitute objectives. Every answer and explanation must "
        "be supported by the cited eligible evidence. For single-choice items, each "
        "distractor must contain exactly one false claim and option word counts may "
        "differ by at most 3. For bounded short answers, preserve the frozen accepted "
        "answer variants. Use remediation_purpose=none except in remediation phase. "
        "Return only the strict structured object.\n\n"
        + json.dumps({
            "campaign_contract_id": FINAL_CONTRACT_ID,
            "phase": phase,
            "allocation": allocation,
            "contracts": [contract.__dict__ for contract in contracts.values()],
            "miss_context": miss_context or [],
            "learner_text_forbidden_patterns": ["ev_*", "src_*", "qst_*", "grd_*", "prv_*", "prc_*", "ati_*", "OBJ-RESP-*"],
        }, ensure_ascii=False, sort_keys=True)
    )


def _run_set_candidate(
    client: CampaignClient,
    *,
    phase: str,
    candidate_number: int,
    contracts: dict[str, ObjectiveContract],
    request: PracticeGenerationInput,
    artifact_root: Path,
    allocation: dict[str, int],
    campaign_id: str,
    miss_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    request_contract = build_practice_generation_request_contract(request).model_dump(mode="json")
    item_limit = request.item_limit
    contract_ids = [contracts[item].contract_id for item in request.effective_requested_objective_ids()]
    raw, receipt, events = _call_with_transport_retries(
        client,
        purpose=f"{phase}_generation",
        operation_id=request.operation_id,
        instructions=_instructions(phase, contracts, allocation, miss_context),
        input_payload={
            "request_contract": request_contract,
            "allocation": allocation,
            "assessment_contracts": [contract.__dict__ for contract in contracts.values() if contract.objective_id in request.effective_requested_objective_ids()],
            "approved_evidence": [item.model_dump(mode="json") for binding in request.effective_objective_evidence_bindings() for item in binding.support_evidence],
            "miss_context": miss_context or [],
        },
        schema=_generation_schema(request_contract, item_limit, contract_ids),
        output_limit=GENERATION_OUTPUT_LIMIT,
        artifact_root=artifact_root,
    )
    record = {"schema_version": "c3-final-generation-receipt-v1", "campaign_id": campaign_id, "phase": phase, "candidate_number": candidate_number, "requested_model": MODEL, "reasoning_effort": REASONING, "store": STORE, "request_contract": request_contract, "provider_receipt": receipt.as_dict(), "transport_events": events, "raw_output": raw}
    _write_json(artifact_root / phase / f"candidate-{candidate_number}-generation.json", record)
    if not isinstance(raw, dict) or raw.get("campaign_contract_id") != FINAL_CONTRACT_ID or raw.get("outcome") != "generated" or raw.get("abstain_reason") is not None:
        return {"status": "REJECT_RETRYABLE", "failure_class": "MODEL_FORMAT_FAILURE", "failure_detail": "generation envelope invalid"}
    if raw.get("request_contract") != request_contract:
        return {"status": "REJECT_RETRYABLE", "failure_class": "DETERMINISTIC_CONTRACT_FAILURE", "failure_detail": "request contract echo mismatch"}
    if set(raw.get("assessment_contract_ids", [])) != set(contract_ids) or len(raw.get("assessment_contract_ids", [])) != len(contract_ids):
        return {"status": "REJECT_RETRYABLE", "failure_class": "DETERMINISTIC_CONTRACT_FAILURE", "failure_detail": "assessment contract set mismatch"}
    questions = raw.get("questions")
    failure_class, detail, failures = _set_failure(questions, phase=phase, allocation=allocation, contracts=contracts, request=request)
    if failure_class:
        return {"status": "REJECT_RETRYABLE", "failure_class": failure_class, "failure_detail": detail, "question_failures": failures}
    for index, question in enumerate(questions, start=1):
        evaluated, _ = _judge_question(client, question=question, objective_contract=contracts[question["objective_ids"][0]], request=request, phase=phase, candidate_number=candidate_number, question_number=index, artifact_root=artifact_root, campaign_id=campaign_id)
        if evaluated["status"] != "MODEL_QUALIFIED":
            return {"status": "REJECT_RETRYABLE", "failure_class": evaluated["failure_class"], "failure_detail": f"question {index} failed individual judge"}
    set_result = _judge_set(client, phase=phase, candidate_number=candidate_number, questions=questions, allocation=allocation, artifact_root=artifact_root, campaign_id=campaign_id)
    if set_result["status"] != "MODEL_QUALIFIED":
        return {"status": "REJECT_RETRYABLE", "failure_class": "SET_COHERENCE_FAILURE", "failure_detail": "set-level judge rejected candidate"}
    qualified = {"phase": phase, "candidate_number": candidate_number, "questions": questions, "allocation": allocation, "status": "MODEL_QUALIFIED"}
    _write_json(artifact_root / phase / "model-qualified-candidate.json", qualified)
    return qualified


def _run_phase(
    client: CampaignClient,
    *,
    phase: str,
    contracts: dict[str, ObjectiveContract],
    material: list[GenerationSourceText],
    evidence: list[Any],
    artifact_root: Path,
    campaign_id: str,
    objective_ids: list[str],
    allocation: dict[str, int],
    item_limit: int,
    purpose: str,
    focus: str,
    miss_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    required_claims = {item: list(contracts[item].required_claim_ids) for item in objective_ids}
    accepted = {item: list(contracts[item].accepted_answers) for item in objective_ids if contracts[item].accepted_answers}
    failures: list[dict[str, Any]] = []
    for candidate_number in range(1, MAX_SET_CANDIDATES + 1):
        request = _request(campaign_id=campaign_id, phase=phase, candidate_number=candidate_number, material=material, evidence=evidence, purpose=purpose, objective_ids=objective_ids, required_claims=required_claims, accepted_answers=accepted, item_limit=item_limit, focus=focus)
        result = _run_set_candidate(client, phase=phase, candidate_number=candidate_number, contracts=contracts, request=request, artifact_root=artifact_root, allocation=allocation, campaign_id=campaign_id, miss_context=miss_context)
        if result["status"] == "MODEL_QUALIFIED":
            return {**result, "failures": failures}
        failures.append({"candidate_number": candidate_number, **{key: value for key, value in result.items() if key != "status"}})
    return {"phase": phase, "status": "REPEATED_QUALIFICATION_FAILURE", "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["primary", "repeat", "remediation"])
    parser.add_argument("--reference-root", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--campaign-id", default=FINAL_CAMPAIGN_ID)
    parser.add_argument("--miss-context", type=Path)
    args = parser.parse_args()
    reference_root = args.reference_root.resolve()
    artifact_root = args.artifact_root.resolve()
    args.state_dir.resolve().mkdir(parents=True, exist_ok=True)
    contracts = _objective_contracts(reference_root)
    material = _material(reference_root)
    evidence = _objective_evidence(reference_root)
    from scripts.run_c3_h3_model_qualification import _load_api_key

    client = CampaignClient(_load_api_key(args.env_file.resolve() if args.env_file else None), args.state_dir.resolve())
    miss_context = json.loads(args.miss_context.read_text(encoding="utf-8")) if args.miss_context else None
    allocation = {"OBJ-RESP-01": 2, "OBJ-RESP-02": 2, "OBJ-RESP-03": 1} if args.phase in {"primary", "repeat"} else {item["objective_id"]: 1 for item in (miss_context or [])}
    objective_ids = APPROVED_OBJECTIVE_IDS if args.phase in {"primary", "repeat"} else list(allocation)
    item_limit = 5 if args.phase in {"primary", "repeat"} else len(objective_ids)
    result = _run_phase(client, phase=args.phase, contracts=contracts, material=material, evidence=evidence, artifact_root=artifact_root, campaign_id=args.campaign_id, objective_ids=objective_ids, allocation=allocation, item_limit=item_limit, purpose="remediation" if args.phase == "remediation" else "practice", focus="Bounded Biology 101 cellular respiration Practice set" if args.phase != "remediation" else "Correct the exact missed Biology 101 objectives without unrelated review content", miss_context=miss_context)
    summary_path = artifact_root / "campaign-summary.json"
    existing = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {"schema_version": "c3-final-quality-campaign-v1", "campaign_id": args.campaign_id, "phases": []}
    existing["phases"] = [phase for phase in existing.get("phases", []) if phase.get("phase") != args.phase]
    existing["phases"].append(result)
    existing["provider_policy"] = {"model": MODEL, "reasoning": REASONING, "store": STORE, "max_provider_spend_microusd": MAX_PROVIDER_SPEND_MICROUSD}
    existing["usage_summary"] = client.ledger.usage_summary()
    _write_json(summary_path, existing)
    print(json.dumps({"phase": args.phase, "status": result["status"], "provider_spend_microusd": existing["usage_summary"]["admitted_cost_microusd"]}, sort_keys=True))
    return 0 if result["status"] == "MODEL_QUALIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
