from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.courses.generation_models import build_practice_generation_request_contract
from scripts.run_c3_h3_model_qualification import (
    MAX_PROVIDER_SPEND_MICROUSD,
    MODEL,
    REASONING,
    _candidate_failure,
    _generation_instructions,
    _judge_result,
    _load_v3_contracts,
    _material,
    _objective_evidence,
    _qualified_candidate,
    _request,
    CampaignClient,
)


REFERENCE_ROOT = Path(__file__).resolve().parents[3] / "evals/reference_course"


def _request_and_contract(objective_id: str = "OBJ-RESP-02"):
    contracts = _load_v3_contracts(REFERENCE_ROOT)
    material = _material(REFERENCE_ROOT)
    evidence = _objective_evidence(REFERENCE_ROOT)
    request = _request(objective_id, 1, material, evidence, contracts[objective_id])
    return request, contracts[objective_id]


def _candidate(request, objective_id: str) -> dict[str, object]:
    contract = request.effective_objective_evidence_bindings()
    evidence_ids = [
        item.evidence_id
        for binding in contract
        if binding.objective_id == objective_id
        for item in binding.support_evidence
    ]
    request_contract = json.loads(
        json.dumps(build_practice_generation_request_contract(request).model_dump(mode="json"))
    )
    options = [
        {"option_key": "A", "text": "Oxygen accepts electrons and protons, forms water, and permits continued electron flow."},
        {"option_key": "B", "text": "Oxygen accepts electrons and protons, forms ATP, and permits continued electron flow."},
        {"option_key": "C", "text": "Oxygen accepts electrons and protons, forms water, and stops continued electron flow."},
        {"option_key": "D", "text": "Oxygen accepts ATP and protons, forms water, and permits continued electron flow."},
    ]
    return {
        "request_contract": request_contract,
        "outcome": "generated",
        "abstain_reason": None,
        "questions": [
            {
                "question_type": "single_choice_v1",
                "prompt": "Which statement explains oxygen's causal role in aerobic electron transport?",
                "options": options,
                "correct_option_key": "A",
                "explanation": "The approved evidence connects oxygen's terminal acceptance to water formation and continued flow.",
                "objective_ids": [objective_id],
                "citation_evidence_ids": evidence_ids,
            }
        ],
    }


def test_generation_candidate_uses_only_frozen_scope_and_passes_deterministic_shape() -> None:
    request, contract = _request_and_contract()
    raw = _candidate(request, contract["objective_id"])

    assert _candidate_failure(raw, request, contract) == ("", "")
    instructions = _generation_instructions(contract)
    assert "opt_resp02_correct" not in instructions
    assert "Oxygen accepts electrons and protons to form water; as the final acceptor" not in instructions
    assert '"maximum_word_count_delta": 0' in instructions


def test_generation_candidate_rejects_objective_substitution() -> None:
    request, contract = _request_and_contract()
    raw = _candidate(request, contract["objective_id"])
    raw["questions"][0]["objective_ids"] = ["OBJ-RESP-03"]

    assert _candidate_failure(raw, request, contract)[0] == "DETERMINISTIC_CONTRACT_FAILURE"


def test_qualified_candidate_matches_runtime_opaque_single_choice_contract() -> None:
    request, contract = _request_and_contract()
    qualified = _qualified_candidate(
        _candidate(request, contract["objective_id"])["questions"][0], request.operation_id
    )

    assert qualified["question_type"] == "single_choice"
    option_ids = [option["option_id"] for option in qualified["options"]]
    assert len(option_ids) == 4
    assert len(set(option_ids)) == 4
    assert qualified["answer_contract"]["correct_option_id"] in option_ids


def test_judge_gate_enforces_all_required_thresholds() -> None:
    dimensions = {
        "factual_correctness": 4,
        "course_evidence_support": 4,
        "objective_alignment": 3,
        "cognitive_target_alignment": 3,
        "single_correct_answer": 4,
        "grading_fairness": 4,
        "distractor_quality": 3,
        "answer_cue_resistance": 3,
        "explanation_quality": 3,
        "scope_and_difficulty": 3,
    }
    result = _judge_result(
        {
            "dimensions": dimensions,
            "hard_failures": [],
            "failure_class": None,
            "verdict": "QUALIFY",
            "rationale": "All required thresholds are met.",
        }
    )
    assert result[0] == "QUALIFY"

    rejected = {**dimensions, "grading_fairness": 3}
    with pytest.raises(RuntimeError, match="MODEL_JUDGE_CONTRACT_INCONSISTENT"):
        _judge_result(
            {
                "dimensions": rejected,
                "hard_failures": [],
                "failure_class": "PEDAGOGY_FAILURE",
                "verdict": "QUALIFY",
                "rationale": "The score is below the required fairness threshold.",
            }
        )


def test_campaign_client_configures_luna_high_and_hard_budget(tmp_path: Path) -> None:
    client = CampaignClient("test-only-not-used", tmp_path)

    policy = client.ledger.load_policy()
    assert MODEL == "gpt-5.6-luna"
    assert REASONING == "high"
    assert policy.max_lifetime_cost_microusd == MAX_PROVIDER_SPEND_MICROUSD
    assert client.ledger.usage_summary()["admitted_cost_microusd"] == 0
