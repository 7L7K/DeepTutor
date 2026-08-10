from __future__ import annotations

import json
from pathlib import Path

from scripts.run_c3_final_set_plan_v2 import (
    ALLOCATION,
    FINAL_SET_PLAN_ID,
    _request,
    _set_failure_v2,
    _slot_contracts,
)
from scripts.run_c3_final_quality_campaign import _material, _objective_evidence


REFERENCE_ROOT = Path(__file__).resolve().parents[3] / "evals/reference_course"


def _request_for_test():
    slots = _slot_contracts(REFERENCE_ROOT)
    return slots, _request(
        campaign_id="test-c3-final-set-plan-v2",
        phase="primary",
        candidate_number=1,
        material=_material(REFERENCE_ROOT),
        evidence=_objective_evidence(REFERENCE_ROOT),
        purpose="practice",
        item_limit=5,
        focus="test",
        slots=slots,
    )


def _choice(slot_id: str, objective_id: str, citations: list[str], stem: str, correct: str = "A", option_prefix: str = "mechanism") -> dict[str, object]:
    return {
        "slot_id": slot_id,
        "question_type": "single_choice_v1",
        "prompt": stem,
        "answer_text": "",
        "accepted_answers": [],
        "options": [
            {"option_key": "A", "text": f"The supported {option_prefix} matches the specified Course evidence."},
            {"option_key": "B", "text": f"The {option_prefix} reverses one specified Course claim in this slot."},
            {"option_key": "C", "text": f"The {option_prefix} replaces one specified Course claim with another product."},
            {"option_key": "D", "text": f"The {option_prefix} changes the pathway consequence described by this slot."},
        ],
        "correct_option_key": correct,
        "explanation": "The selected statement matches the approved evidence for this slot.",
        "objective_ids": [objective_id],
        "citation_evidence_ids": citations,
        "remediation_purpose": "none",
    }


def _valid_questions():
    slots = _slot_contracts(REFERENCE_ROOT)
    return [
        {
            "slot_id": "slot_resp01_conversion_identity",
            "question_type": "bounded_short_answer_v1",
            "prompt": "What conversion occurs during pyruvate oxidation?",
            "answer_text": "Pyruvate is converted to acetyl-CoA.",
            "accepted_answers": list(slots["slot_resp01_conversion_identity"].accepted_answers),
            "options": [], "correct_option_key": "",
            "explanation": "Pyruvate oxidation converts pyruvate to acetyl-CoA before the cycle.",
            "objective_ids": ["OBJ-RESP-01"], "citation_evidence_ids": ["ev_resp01_conversion"], "remediation_purpose": "none",
        },
        _choice("slot_resp02_terminal_mechanism", "OBJ-RESP-02", ["ev_resp02_terminal_acceptor", "ev_resp02_accepts_electrons"], "What does oxygen accept at the end of the aerobic electron transport chain?", option_prefix="terminal-acceptor role"),
        _choice("slot_resp02_flow_consequence", "OBJ-RESP-02", ["ev_resp02_forms_water", "ev_resp02_flow_continues"], "Why does the terminal acceptor allow aerobic electron flow to continue?", option_prefix="electron-flow consequence"),
        _choice("slot_resp03_nad_continuity", "OBJ-RESP-03", ["ev_resp03_fermentation_context", "ev_resp03_regenerates_nad"], "How does fermentation keep glycolysis running?", option_prefix="NAD continuity"),
        _choice("slot_resp03_energy_oxygen_contrast", "OBJ-RESP-03", ["ev_resp03_no_oxygen_low_atp", "ev_resp03_aerobic_comparison"], "How does fermentation differ from aerobic respiration in oxygen use and ATP yield?", option_prefix="oxygen-and-energy contrast"),
    ]


def test_v2_plan_is_frozen_and_uses_supported_distinct_focuses() -> None:
    slots, _ = _request_for_test()
    assert FINAL_SET_PLAN_ID == "c3-final-set-plan-v2"
    assert len(slots) == 5
    counts = {objective: sum(item.objective_id == objective for item in slots.values()) for objective in ALLOCATION}
    assert counts == ALLOCATION
    assert len({slot.assessment_focus_id for slot in slots.values()}) == 5
    assert len({(slot.objective_id, slot.required_claim_ids) for slot in slots.values()}) == 5


def test_distinct_supported_v2_slots_pass_deterministic_set_fence() -> None:
    slots, request = _request_for_test()
    assert _set_failure_v2(_valid_questions(), slots=slots, request=request) == ("", "", [])


def test_duplicate_and_missing_slots_fail_closed() -> None:
    slots, request = _request_for_test()
    duplicate = _valid_questions()
    duplicate[2]["slot_id"] = duplicate[1]["slot_id"]
    failure, _, _ = _set_failure_v2(duplicate, slots=slots, request=request)
    assert failure == "DUPLICATE_SLOT"

    missing = _valid_questions()[:-1]
    failure, _, _ = _set_failure_v2(missing, slots=slots, request=request)
    assert failure == "MODEL_FORMAT_FAILURE"


def test_reused_answer_claim_bundle_and_opaque_metadata_fail_closed() -> None:
    slots, request = _request_for_test()
    altered = _valid_questions()
    altered[2]["slot_id"] = "slot_resp02_terminal_mechanism"
    failure, _, _ = _set_failure_v2(altered, slots=slots, request=request)
    assert failure == "DUPLICATE_SLOT"

    leaked = _valid_questions()
    leaked[0]["explanation"] = "Use slot_resp01_conversion_identity."
    failure, _, _ = _set_failure_v2(leaked, slots=slots, request=request)
    assert failure == "DETERMINISTIC_CONTRACT_FAILURE"
