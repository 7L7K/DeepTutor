"""Deterministic gates for the final C3 learning-loop campaign harness."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.run_c3_final_quality_campaign import (
    FINAL_CONTRACT_ID,
    _objective_contracts,
    _request,
    _set_failure,
)
from scripts.run_c3_luna_probe import _material, _objective_evidence


REFERENCE_ROOT = Path(__file__).resolve().parents[3] / "evals/reference_course"


def _request_for_campaign():
    contracts = _objective_contracts(REFERENCE_ROOT)
    material = _material(REFERENCE_ROOT)
    evidence = _objective_evidence(REFERENCE_ROOT)
    request = _request(
        campaign_id="test-c3-final",
        phase="primary",
        candidate_number=1,
        material=material,
        evidence=evidence,
        purpose="practice",
        objective_ids=["OBJ-RESP-01", "OBJ-RESP-02", "OBJ-RESP-03"],
        required_claims={key: list(value.required_claim_ids) for key, value in contracts.items()},
        accepted_answers={key: list(value.accepted_answers) for key, value in contracts.items() if value.accepted_answers},
        item_limit=5,
        focus="cellular respiration",
    )
    return contracts, request


def _choice(objective_id: str, prompt: str, correct: str, options: list[str], citations: list[str]) -> dict[str, object]:
    return {
        "question_type": "single_choice_v1",
        "prompt": prompt,
        "answer_text": "",
        "accepted_answers": [],
        "options": [
            {"option_key": key, "text": text}
            for key, text in zip(("A", "B", "C", "D"), options)
        ],
        "correct_option_key": correct,
        "explanation": "The selected statement matches the approved Course evidence.",
        "objective_ids": [objective_id],
        "citation_evidence_ids": citations,
        "remediation_purpose": "none",
    }


def _short(prompt: str) -> dict[str, object]:
    return {
        "question_type": "bounded_short_answer_v1",
        "prompt": prompt,
        "answer_text": "Pyruvate is converted to acetyl-CoA.",
        "accepted_answers": [
            "pyruvate is converted to acetyl-coa",
            "pyruvate becomes acetyl-coa",
            "pyruvate converts to acetyl-coa",
            "conversion of pyruvate to acetyl-coa",
            "pyruvate is converted to acetyl coenzyme a",
        ],
        "options": [],
        "correct_option_key": "",
        "explanation": "Pyruvate oxidation converts pyruvate to acetyl-CoA before the citric acid cycle.",
        "objective_ids": ["OBJ-RESP-01"],
        "citation_evidence_ids": ["ev_resp01_conversion"],
        "remediation_purpose": "none",
    }


def _valid_primary():
    return [
        _short("What conversion links pyruvate oxidation to the citric acid cycle?"),
        _short("Which molecule is produced when pyruvate enters the next respiration stage?"),
        _choice(
            "OBJ-RESP-02",
            "Which statement explains oxygen's role at the end of aerobic respiration?",
            "A",
            [
                "Oxygen is the terminal electron acceptor, accepts electrons and protons to form water, and permits aerobic electron flow to continue.",
                "Oxygen is the initial electron donor, accepts electrons and protons to form water, and permits aerobic electron flow to continue.",
                "Oxygen is the terminal electron acceptor, accepts electrons but not protons to form water, and permits aerobic electron flow to continue.",
                "Oxygen is the terminal electron acceptor, accepts electrons and protons to form another product, and permits aerobic electron flow to continue.",
            ],
            ["ev_resp02_terminal_acceptor", "ev_resp02_accepts_electrons", "ev_resp02_forms_water", "ev_resp02_flow_continues"],
        ),
        _choice(
            "OBJ-RESP-02",
            "Why does the terminal acceptor matter for continued aerobic electron flow?",
            "A",
            [
                "The terminal acceptor takes electrons and protons, forms water, and allows the aerobic chain to keep transferring electrons.",
                "The terminal acceptor donates the first electrons, forms water, and allows the aerobic chain to keep transferring electrons.",
                "The terminal acceptor takes electrons but not protons, forms water, and allows the aerobic chain to keep transferring electrons.",
                "The terminal acceptor takes electrons and protons, forms a different product, and allows the aerobic chain to keep transferring electrons.",
            ],
            ["ev_resp02_terminal_acceptor", "ev_resp02_accepts_electrons", "ev_resp02_forms_water", "ev_resp02_flow_continues"],
        ),
        _choice(
            "OBJ-RESP-03",
            "Which statement correctly contrasts fermentation with aerobic respiration?",
            "D",
            [
                "Fermentation preserves glycolysis, fails to regenerate NAD+, lacks oxygen as terminal acceptor, and yields less ATP per glucose.",
                "Fermentation preserves glycolysis, regenerates NAD+, uses oxygen as terminal acceptor, and yields less ATP per glucose.",
                "Fermentation preserves glycolysis, regenerates NAD+, lacks oxygen as terminal acceptor, and yields similar ATP per glucose.",
                "Fermentation preserves glycolysis, regenerates NAD+, lacks oxygen as terminal acceptor, and yields less ATP per glucose.",
            ],
            ["ev_resp03_fermentation_context", "ev_resp03_regenerates_nad", "ev_resp03_no_oxygen_low_atp", "ev_resp03_aerobic_comparison"],
        ),
    ]


def test_primary_candidate_enforces_frozen_five_question_allocation() -> None:
    contracts, request = _request_for_campaign()
    failure, detail, all_failures = _set_failure(
        _valid_primary(),
        phase="primary",
        allocation={"OBJ-RESP-01": 2, "OBJ-RESP-02": 2, "OBJ-RESP-03": 1},
        contracts=contracts,
        request=request,
    )
    assert (failure, detail, all_failures) == ("", "", [])


def test_primary_candidate_rejects_near_duplicate_and_wrong_allocation() -> None:
    contracts, request = _request_for_campaign()
    candidate = _valid_primary()
    candidate[1]["prompt"] = candidate[0]["prompt"]
    failure, detail, failures = _set_failure(
        candidate,
        phase="primary",
        allocation={"OBJ-RESP-01": 2, "OBJ-RESP-02": 2, "OBJ-RESP-03": 1},
        contracts=contracts,
        request=request,
    )
    assert failure == "DUPLICATE_FAILURE"
    assert "duplicate" in detail
    assert failures

    candidate = _valid_primary()[:-1]
    failure, detail, _ = _set_failure(
        candidate,
        phase="primary",
        allocation={"OBJ-RESP-01": 2, "OBJ-RESP-02": 2, "OBJ-RESP-03": 1},
        contracts=contracts,
        request=request,
    )
    assert failure == "MODEL_FORMAT_FAILURE"
    assert "count" in detail


def test_learner_text_opaque_ids_are_rejected_but_machine_citations_are_allowed() -> None:
    contracts, request = _request_for_campaign()
    candidate = _valid_primary()
    candidate[0]["explanation"] = "See ev_resp01_conversion for the answer."
    failure, _, _ = _set_failure(
        candidate,
        phase="primary",
        allocation={"OBJ-RESP-01": 2, "OBJ-RESP-02": 2, "OBJ-RESP-03": 1},
        contracts=contracts,
        request=request,
    )
    assert failure == "DETERMINISTIC_CONTRACT_FAILURE"

    clean = _valid_primary()
    failure, detail, _ = _set_failure(
        clean,
        phase="primary",
        allocation={"OBJ-RESP-01": 2, "OBJ-RESP-02": 2, "OBJ-RESP-03": 1},
        contracts=contracts,
        request=request,
    )
    assert failure == ""
    assert detail == ""
    assert clean[2]["citation_evidence_ids"]


def test_remediation_is_bounded_to_two_through_four_items() -> None:
    contracts, request = _request_for_campaign()
    remediation = [
        {**_valid_primary()[2], "objective_ids": ["OBJ-RESP-02"], "remediation_purpose": "direct_correction"},
        {**_valid_primary()[4], "objective_ids": ["OBJ-RESP-03"], "remediation_purpose": "contrast"},
    ]
    failure, detail, _ = _set_failure(
        remediation,
        phase="remediation",
        allocation={"OBJ-RESP-02": 1, "OBJ-RESP-03": 1},
        contracts=contracts,
        request=request,
    )
    assert failure == ""
    assert detail == ""

    too_many = remediation * 3
    failure, detail, _ = _set_failure(
        too_many,
        phase="remediation",
        allocation={"OBJ-RESP-02": 1, "OBJ-RESP-03": 1},
        contracts=contracts,
        request=request,
    )
    assert failure == "MODEL_FORMAT_FAILURE"
    assert "count" in detail

    missing_objective = [remediation[0], {**remediation[0], "prompt": "Which accepted statement reinforces the oxygen role?"}]
    failure, detail, _ = _set_failure(
        missing_objective,
        phase="remediation",
        allocation={"OBJ-RESP-02": 1, "OBJ-RESP-03": 1},
        contracts=contracts,
        request=request,
    )
    assert failure == "OBJECTIVE_ALLOCATION_FAILURE"
    assert "OBJ-RESP-03" in detail


def test_malformed_question_collections_fail_closed() -> None:
    contracts, request = _request_for_campaign()
    candidate = _valid_primary()
    candidate[0]["options"] = None
    failure, detail, _ = _set_failure(
        candidate,
        phase="primary",
        allocation={"OBJ-RESP-01": 2, "OBJ-RESP-02": 2, "OBJ-RESP-03": 1},
        contracts=contracts,
        request=request,
    )
    assert failure == "MODEL_FORMAT_FAILURE"
    assert "lists" in detail


def test_contract_identifier_remains_versioned() -> None:
    assert FINAL_CONTRACT_ID == "c3-final-learning-loop-v1"
    payload = json.loads((REFERENCE_ROOT / "assessment_contracts_v4_generation_only.json").read_text())
    assert payload["status"] == "FROZEN_GENERATION_ONLY"
