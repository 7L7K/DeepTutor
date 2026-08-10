#!/usr/bin/env python3
"""Run the versioned C3 final set-plan-v2 campaign.

This successor harness preserves the rejected v1 campaign and gives the
provider an explicit server-owned five-slot composition contract.  It reuses
the frozen individual publication and Luna-judge machinery; it does not alter
learner-facing generation behavior.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import difflib
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
from scripts.run_c3_final_quality_campaign import (
    FINAL_INDIVIDUAL_JUDGE_OUTPUT_LIMIT,
    FINAL_PROVIDER_POLICY_ID,
    _call_once,
    _deterministic_question_failure,
    _judge_question,
    _judge_set,
    _material,
    _normalize_question,
    _objective_contracts,
    _objective_evidence,
    _write_json,
    CampaignStop,
    FinalCampaignStop,
    ObjectiveContract,
)
from scripts.run_c3_h3_model_qualification import (
    CampaignClient,
    GENERATION_OUTPUT_LIMIT,
    MAX_PROVIDER_SPEND_MICROUSD,
    MODEL,
    REASONING,
    STORE,
)
from scripts.run_c3_luna_probe import APPROVED_OBJECTIVE_IDS


FINAL_SET_PLAN_ID = "c3-final-set-plan-v2"
FINAL_SET_PLAN_FILENAME = "final_set_plan_v2.json"
FINAL_CAMPAIGN_ID = "2026-08-10-teeechr-c3-final-learning-loop-v2-2"
FINAL_GENERATION_PROMPT_ID = "c3-final-set-generation-prompt-v2-2"
FINAL_CAMPAIGN_SCHEMA_VERSION = "c3-final-quality-campaign-v2"
FINAL_GENERATION_RECEIPT_SCHEMA_VERSION = "c3-final-generation-receipt-v2"
FINAL_NORMALIZED_SCHEMA_VERSION = "c3-final-normalized-questions-v2"
ITEM_LIMIT = 5
MAX_CANDIDATES = 3
ALLOCATION = {"OBJ-RESP-01": 1, "OBJ-RESP-02": 2, "OBJ-RESP-03": 2}
LEAKED_IDENTIFIER = re.compile(
    r"(?:src|ev|qst|grd|prv|prc|ati|slot)[_-][A-Za-z0-9_-]+|OBJ-RESP-[A-Za-z0-9_-]+"
)


@dataclass(frozen=True)
class SlotContract:
    slot_id: str
    contract_id: str
    objective_id: str
    assessment_focus_id: str
    focus_description: str
    required_claim_ids: tuple[str, ...]
    required_evidence_ids: tuple[str, ...]
    question_type: str
    grading_contract_kind: str
    cognitive_target: str
    accepted_answers: tuple[str, ...]
    maximum_word_count_delta: int


def _slot_contracts(reference_root: Path) -> dict[str, SlotContract]:
    plan = json.loads((reference_root / FINAL_SET_PLAN_FILENAME).read_text(encoding="utf-8"))
    if plan.get("schema_version") != FINAL_SET_PLAN_ID or plan.get("status") != "FROZEN":
        raise FinalCampaignStop("FINAL_SET_PLAN_NOT_FROZEN")
    if plan.get("campaign_contract_id") != FINAL_SET_PLAN_ID:
        raise FinalCampaignStop("FINAL_SET_PLAN_ID_MISMATCH")
    if plan.get("allocation") != ALLOCATION:
        raise FinalCampaignStop("FINAL_SET_PLAN_ALLOCATION_MISMATCH")
    objective_contracts = _objective_contracts(reference_root)
    slots: dict[str, SlotContract] = {}
    focus_by_objective: dict[str, set[str]] = {}
    claim_bundle_by_objective: dict[str, set[tuple[str, ...]]] = {}
    for raw in plan.get("slots", []):
        objective_id = str(raw["objective_id"])
        base = objective_contracts[objective_id]
        claims = tuple(str(item) for item in raw["required_claim_ids"])
        evidence = tuple(str(item) for item in raw["eligible_evidence_ids"])
        focus = str(raw["assessment_focus_id"])
        if objective_id not in APPROVED_OBJECTIVE_IDS:
            raise FinalCampaignStop("FINAL_SET_PLAN_OBJECTIVE_NOT_APPROVED")
        if focus in focus_by_objective.setdefault(objective_id, set()):
            raise FinalCampaignStop("FINAL_SET_PLAN_DUPLICATE_FOCUS")
        if claims in claim_bundle_by_objective.setdefault(objective_id, set()):
            raise FinalCampaignStop("FINAL_SET_PLAN_DUPLICATE_CLAIM_BUNDLE")
        if not set(claims).issubset(set(base.required_claim_ids)):
            raise FinalCampaignStop("FINAL_SET_PLAN_CLAIM_OUTSIDE_OBJECTIVE")
        if not set(evidence).issubset(set(base.required_evidence_ids)):
            raise FinalCampaignStop("FINAL_SET_PLAN_EVIDENCE_OUTSIDE_OBJECTIVE")
        slot_id = str(raw["slot_id"])
        if slot_id in slots:
            raise FinalCampaignStop("FINAL_SET_PLAN_DUPLICATE_SLOT")
        slots[slot_id] = SlotContract(
            slot_id=slot_id,
            contract_id=f"{FINAL_SET_PLAN_ID}:{slot_id}",
            objective_id=objective_id,
            assessment_focus_id=focus,
            focus_description=str(raw["focus_description"]),
            required_claim_ids=claims,
            required_evidence_ids=evidence,
            question_type=str(raw["question_type"]),
            grading_contract_kind=str(raw["grading_contract_kind"]),
            cognitive_target=str(raw["focus_description"]),
            accepted_answers=base.accepted_answers,
            maximum_word_count_delta=base.maximum_word_count_delta,
        )
        focus_by_objective[objective_id].add(focus)
        claim_bundle_by_objective[objective_id].add(claims)
    if len(slots) != ITEM_LIMIT:
        raise FinalCampaignStop("FINAL_SET_PLAN_SLOT_COUNT_INVALID")
    if {objective: sum(slot.objective_id == objective for slot in slots.values()) for objective in ALLOCATION} != ALLOCATION:
        raise FinalCampaignStop("FINAL_SET_PLAN_OBJECTIVE_ALLOCATION_INVALID")
    return slots


def _required_claims(slots: dict[str, SlotContract]) -> dict[str, list[str]]:
    return {
        objective_id: sorted({claim for slot in slots.values() if slot.objective_id == objective_id for claim in slot.required_claim_ids})
        for objective_id in APPROVED_OBJECTIVE_IDS
    }


def _accepted_answers(slots: dict[str, SlotContract]) -> dict[str, list[str]]:
    return {
        objective_id: list(next(slot for slot in slots.values() if slot.objective_id == objective_id).accepted_answers)
        for objective_id in APPROVED_OBJECTIVE_IDS
        if any(slot.accepted_answers for slot in slots.values() if slot.objective_id == objective_id)
    }


def _request(
    *,
    campaign_id: str,
    phase: str,
    candidate_number: int,
    material: list[GenerationSourceText],
    evidence: list[Any],
    purpose: str,
    item_limit: int,
    focus: str,
    slots: dict[str, SlotContract],
) -> PracticeGenerationInput:
    from scripts.run_c3_final_quality_campaign import _request as base_request

    return base_request(
        campaign_id=campaign_id,
        phase=phase,
        candidate_number=candidate_number,
        material=material,
        evidence=evidence,
        purpose=purpose,
        objective_ids=list(APPROVED_OBJECTIVE_IDS),
        required_claims=_required_claims(slots),
        accepted_answers=_accepted_answers(slots),
        item_limit=item_limit,
        focus=focus,
    )


def _question_schema(slot_ids: list[str]) -> dict[str, Any]:
    from scripts.run_c3_final_quality_campaign import _question_schema as base_schema

    question = base_schema()
    question["required"].append("slot_id")
    question["properties"]["slot_id"] = {"type": "string", "enum": slot_ids}
    return question


def _generation_schema(request_contract: dict[str, Any], item_limit: int, contract_ids: list[str], slot_ids: list[str]) -> dict[str, Any]:
    question = _question_schema(slot_ids)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["campaign_contract_id", "assessment_contract_ids", "request_contract", "outcome", "abstain_reason", "questions"],
        "properties": {
            "campaign_contract_id": {"type": "string", "enum": [FINAL_SET_PLAN_ID]},
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


def _norm_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _answer_target(question: dict[str, Any]) -> str:
    if question["question_type"] == "bounded_short_answer_v1":
        return normalize_bounded_short_answer(str(question["answer_text"]))
    correct = next(item["text"] for item in question["options"] if item["option_key"] == question["correct_option_key"])
    return _norm_text(correct)


def _set_failure_v2(
    questions: object,
    *,
    slots: dict[str, SlotContract],
    request: PracticeGenerationInput,
) -> tuple[str, str, list[dict[str, Any]]]:
    if not isinstance(questions, list) or len(questions) != ITEM_LIMIT:
        return "MODEL_FORMAT_FAILURE", f"set requires exactly {ITEM_LIMIT} questions", []
    failures: list[dict[str, Any]] = []
    seen_slots: set[str] = set()
    prompts: list[tuple[str, str]] = []
    answer_targets: dict[str, set[str]] = {}
    claim_bundles: dict[str, set[tuple[str, ...]]] = {}
    option_templates: set[tuple[str, ...]] = set()
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            failures.append({"index": index, "failure_class": "MODEL_FORMAT_FAILURE", "detail": "question is not an object"})
            continue
        slot_id = question.get("slot_id")
        if not isinstance(slot_id, str) or slot_id not in slots:
            failures.append({"index": index, "failure_class": "MISSING_SLOT", "detail": f"unknown slot_id: {slot_id}"})
            continue
        if slot_id in seen_slots:
            failures.append({"index": index, "failure_class": "DUPLICATE_SLOT", "detail": slot_id})
        seen_slots.add(slot_id)
        slot = slots[slot_id]
        objective_id = slot.objective_id
        without_slot = {key: value for key, value in question.items() if key != "slot_id"}
        failure_class, detail = _deterministic_question_failure(without_slot, contract=slot, request=request)
        if failure_class:
            failures.append({"index": index, "failure_class": failure_class, "detail": detail})
        citations = question.get("citation_evidence_ids", [])
        if isinstance(citations, list) and not set(citations).issubset(set(slot.required_evidence_ids)):
            failures.append({"index": index, "failure_class": "EVIDENCE_FAILURE", "detail": "citation evidence is outside the slot allowlist"})
        learner_text = " ".join(
            [
                str(question.get("prompt", "")),
                str(question.get("answer_text", "")),
                str(question.get("explanation", "")),
                *[str(item) for item in question.get("accepted_answers", [])],
                *[str(item.get("text", "")) for item in question.get("options", []) if isinstance(item, dict)],
            ]
        )
        if LEAKED_IDENTIFIER.search(learner_text):
            failures.append({"index": index, "failure_class": "DETERMINISTIC_CONTRACT_FAILURE", "detail": "slot or authority metadata leaked into learner text or question envelope"})
        prompt = _norm_text(str(question.get("prompt", "")))
        for prior_objective, prior_prompt in prompts:
            if prior_objective == objective_id and difflib.SequenceMatcher(None, prompt, prior_prompt).ratio() >= 0.80:
                failures.append({"index": index, "failure_class": "STEM_NEAR_DUPLICATE", "detail": "same-objective stems are materially similar"})
        prompts.append((objective_id, prompt))
        target = _answer_target(question)
        if target and target in answer_targets.setdefault(objective_id, set()):
            failures.append({"index": index, "failure_class": "ANSWER_TARGET_REUSE", "detail": "same-objective answer target is reused"})
        answer_targets[objective_id].add(target)
        bundle = tuple(slot.required_claim_ids)
        if bundle in claim_bundles.setdefault(objective_id, set()):
            failures.append({"index": index, "failure_class": "ANSWER_TARGET_REUSE", "detail": "same-objective required claim bundle is reused"})
        claim_bundles[objective_id].add(bundle)
        if question.get("question_type") == "single_choice_v1":
            template = tuple(_norm_text(str(item["text"])) for item in question.get("options", []))
            if template in option_templates:
                failures.append({"index": index, "failure_class": "OPTION_TEMPLATE_REUSE", "detail": "single-choice option template is reused"})
            option_templates.add(template)
    missing = sorted(set(slots) - seen_slots)
    if missing:
        failures.append({"failure_class": "MISSING_SLOT", "detail": f"missing slots: {missing}"})
    objective_counts: dict[str, int] = {}
    for slot_id in seen_slots:
        objective = slots[slot_id].objective_id
        objective_counts[objective] = objective_counts.get(objective, 0) + 1
    if objective_counts != ALLOCATION:
        failures.append({"failure_class": "SET_OBJECTIVE_COVERAGE_FAILURE", "detail": f"expected {ALLOCATION}, got {objective_counts}"})
    if failures:
        return str(failures[0]["failure_class"]), str(failures[0]["detail"]), failures
    return "", "", []


def _instructions(slots: dict[str, SlotContract]) -> str:
    if {"slot_resp02_terminal_mechanism", "slot_resp02_flow_consequence"}.issubset(slots):
        slot_separation = (
            " In particular, slot_resp02_terminal_mechanism must assess terminal "
            "acceptor identity and electron/proton acceptance without assessing water "
            "formation or continued flow, while slot_resp02_flow_consequence must assess "
            "water formation and continued flow without re-testing terminal-acceptor identity."
        )
    else:
        slot_separation = ""
    choice_slots = [slot for slot in slots.values() if slot.question_type == "single_choice_v1"]
    if len(choice_slots) == 4:
        position_rule = "Across the four single-choice slots, use correct_option_key A, B, C, and D exactly once each."
    else:
        position_rule = "Use distinct correct_option_key values across the single-choice slots."
    return (
        "Generate exactly one learner-facing question for each server-owned slot. "
        "Do not merge slots, duplicate slots, or substitute objectives. The slot_id "
        "is machine metadata only and must never appear in prompt, options, answer, "
        "explanation, accepted-answer, or hint text. Use only the slot's required "
        "claims and eligible evidence. Every answer and explanation must be supported. "
        "The primary assessment target for each slot is exactly its required claim "
        "bundle; do not turn eligible but non-required claims into a second assessment "
        "target."
        + slot_separation
        + " "
        "For every single-choice slot, return four options that address every required "
        "dimension, exactly one correct option, and exactly one false claim in each "
        "distractor. Option word counts may differ by at most the slot's frozen "
        "maximum_word_count_delta. If answer_text is present for a single-choice item, "
        "it must exactly match the correct option text. Do not use all-or-none options. "
        + position_rule
        + " "
        "Return the strict structured object with the exact slot_id echoed per question.\n\n"
        + json.dumps({
            "campaign_contract_id": FINAL_SET_PLAN_ID,
            "allocation": ALLOCATION,
            "slots": [asdict(slot) for slot in slots.values()],
            "learner_text_forbidden_patterns": ["ev_*", "src_*", "qst_*", "grd_*", "prv_*", "prc_*", "ati_*", "OBJ-RESP-*", "slot_*"],
        }, ensure_ascii=False, sort_keys=True)
    )


def _run_candidate(
    client: CampaignClient,
    *,
    phase: str,
    candidate_number: int,
    slots: dict[str, SlotContract],
    request: PracticeGenerationInput,
    material: list[GenerationSourceText],
    evidence: list[Any],
    artifact_root: Path,
    campaign_id: str,
) -> dict[str, Any]:
    request_contract = build_practice_generation_request_contract(request).model_dump(mode="json")
    contract_ids = [slot.contract_id for slot in slots.values()]
    raw, receipt, events = _call_once(
        client,
        purpose=f"{phase}_generation_v2",
        operation_id=request.operation_id,
        instructions=_instructions(slots),
        input_payload={
            "request_contract": request_contract,
            "set_plan": [asdict(slot) for slot in slots.values()],
            "approved_evidence": [item.model_dump(mode="json") for binding in request.effective_objective_evidence_bindings() for item in binding.support_evidence],
        },
        schema=_generation_schema(request_contract, ITEM_LIMIT, contract_ids, list(slots)),
        output_limit=GENERATION_OUTPUT_LIMIT,
        artifact_root=artifact_root,
    )
    _write_json(
        artifact_root / phase / f"candidate-{candidate_number}-generation.json",
        {
            "schema_version": FINAL_GENERATION_RECEIPT_SCHEMA_VERSION,
            "campaign_id": campaign_id,
            "phase": phase,
            "candidate_number": candidate_number,
            "set_plan": FINAL_SET_PLAN_ID,
            "generation_prompt_id": FINAL_GENERATION_PROMPT_ID,
            "requested_model": MODEL,
            "reasoning_effort": REASONING,
            "store": STORE,
            "request_contract": request_contract,
            "provider_receipt": receipt.as_dict(),
            "transport_events": events,
            "raw_output": raw,
        },
    )
    if not isinstance(raw, dict) or raw.get("campaign_contract_id") != FINAL_SET_PLAN_ID or raw.get("outcome") != "generated" or raw.get("abstain_reason") is not None:
        return {"status": "REJECT_RETRYABLE", "failure_class": "MODEL_FORMAT_FAILURE", "failure_detail": "generation envelope invalid"}
    if raw.get("request_contract") != request_contract:
        return {"status": "REJECT_RETRYABLE", "failure_class": "DETERMINISTIC_CONTRACT_FAILURE", "failure_detail": "request contract echo mismatch"}
    if set(raw.get("assessment_contract_ids", [])) != set(contract_ids) or len(raw.get("assessment_contract_ids", [])) != len(contract_ids):
        return {"status": "REJECT_RETRYABLE", "failure_class": "DETERMINISTIC_CONTRACT_FAILURE", "failure_detail": "slot contract set mismatch"}
    questions = raw.get("questions")
    failure_class, detail, failures = _set_failure_v2(questions, slots=slots, request=request)
    if failure_class:
        return {"status": "REJECT_RETRYABLE", "failure_class": failure_class, "failure_detail": detail, "question_failures": failures}
    normalized_questions = [_normalize_question(question) for question in questions]
    _write_json(artifact_root / phase / f"candidate-{candidate_number}-normalized.json", {"schema_version": FINAL_NORMALIZED_SCHEMA_VERSION, "phase": phase, "candidate_number": candidate_number, "set_plan": FINAL_SET_PLAN_ID, "questions": normalized_questions})
    for index, question in enumerate(normalized_questions, start=1):
        slot = slots[question["slot_id"]]
        evaluated, _ = _judge_question(client, question=question, objective_contract=slot, request=request, phase=phase, candidate_number=candidate_number, question_number=index, artifact_root=artifact_root, campaign_id=campaign_id)
        if evaluated["status"] != "MODEL_QUALIFIED":
            return {"status": "REJECT_RETRYABLE", "failure_class": evaluated["failure_class"], "failure_detail": f"question {index} failed individual judge"}
    set_result = _judge_set(client, phase=phase, candidate_number=candidate_number, questions=normalized_questions, allocation=ALLOCATION, artifact_root=artifact_root, campaign_id=campaign_id)
    if set_result["status"] != "MODEL_QUALIFIED":
        return {"status": "REJECT_RETRYABLE", "failure_class": "SET_COHERENCE_FAILURE", "failure_detail": "set-level judge rejected candidate"}
    qualified = {"phase": phase, "candidate_number": candidate_number, "set_plan": FINAL_SET_PLAN_ID, "questions": normalized_questions, "allocation": ALLOCATION, "status": "MODEL_QUALIFIED"}
    _write_json(artifact_root / phase / "model-qualified-candidate.json", qualified)
    return qualified


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["primary", "repeat"])
    parser.add_argument("--reference-root", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--campaign-id", default=FINAL_CAMPAIGN_ID)
    parser.add_argument("--start-candidate", type=int, default=1, choices=range(1, MAX_CANDIDATES + 1))
    args = parser.parse_args()
    reference_root = args.reference_root.resolve()
    artifact_root = args.artifact_root.resolve()
    slots = _slot_contracts(reference_root)
    material = _material(reference_root)
    evidence = _objective_evidence(reference_root)
    from scripts.run_c3_h3_model_qualification import _load_api_key

    client = CampaignClient(
        _load_api_key(args.env_file.resolve() if args.env_file else None),
        args.state_dir.resolve(),
        timeout_seconds=120.0,
        enforce_daily_output_limits=False,
        provider_policy_id=FINAL_PROVIDER_POLICY_ID,
    )
    failures: list[dict[str, Any]] = []
    result: dict[str, Any] | None = None
    for candidate_number in range(args.start_candidate, MAX_CANDIDATES + 1):
        request = _request(campaign_id=args.campaign_id, phase=args.phase, candidate_number=candidate_number, material=material, evidence=evidence, purpose="practice", item_limit=ITEM_LIMIT, focus="Bounded Biology 101 cellular respiration Practice set with frozen diverse assessment slots", slots=slots)
        try:
            result = _run_candidate(client, phase=args.phase, candidate_number=candidate_number, slots=slots, request=request, material=material, evidence=evidence, artifact_root=artifact_root, campaign_id=args.campaign_id)
        except CampaignStop as exc:
            result = {"phase": args.phase, "candidate_number": candidate_number, "status": "BLOCKED_PROVIDER_TRANSPORT", "failure_class": str(exc), "failures": failures}
            break
        if result["status"] == "MODEL_QUALIFIED":
            result = {**result, "failures": failures}
            break
        failures.append({"candidate_number": candidate_number, **{key: value for key, value in result.items() if key != "status"}})
    if result is None:
        result = {"phase": args.phase, "status": "REPEATED_QUALIFICATION_FAILURE", "failures": failures}
    elif result.get("status") != "MODEL_QUALIFIED" and result.get("status") != "BLOCKED_PROVIDER_TRANSPORT":
        result = {"phase": args.phase, "status": "REPEATED_QUALIFICATION_FAILURE" if len(failures) >= MAX_CANDIDATES else result.get("status"), "failures": failures}
    summary_path = artifact_root / "campaign-summary.json"
    existing = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {"schema_version": FINAL_CAMPAIGN_SCHEMA_VERSION, "campaign_id": args.campaign_id, "phases": []}
    existing["phases"] = [item for item in existing.get("phases", []) if item.get("phase") != args.phase]
    existing["phases"].append(result)
    existing["provider_policy"] = {"policy_id": FINAL_PROVIDER_POLICY_ID, "model": MODEL, "reasoning": REASONING, "store": STORE, "max_provider_spend_microusd": MAX_PROVIDER_SPEND_MICROUSD, "daily_output_token_limit": {"enforced": False, "scope": "final_c3_campaign_only", "historical_ledger_preserved": True}}
    existing["set_plan"] = {"id": FINAL_SET_PLAN_ID, "filename": FINAL_SET_PLAN_FILENAME, "candidate_limit": MAX_CANDIDATES}
    existing["generation_prompt"] = {"id": FINAL_GENERATION_PROMPT_ID, "frozen_set_plan_unchanged": True, "frozen_individual_validator_unchanged": True}
    existing["usage_summary"] = client.ledger.usage_summary()
    _write_json(summary_path, existing)
    print(json.dumps({"phase": args.phase, "status": result["status"], "provider_spend_microusd": existing["usage_summary"]["admitted_cost_microusd"]}, sort_keys=True))
    return 0 if result["status"] == "MODEL_QUALIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
