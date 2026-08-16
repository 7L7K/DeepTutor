from __future__ import annotations

import csv
import json
from pathlib import Path

from deeptutor.courses.generation_models import (
    build_practice_generation_request_contract,
)
from deeptutor.courses.generation_provider import (
    OpenAIPracticeGenerationProvider,
)
from scripts.run_c3_luna_probe import (
    APPROVED_OBJECTIVE_IDS,
    _assessment_contracts,
    _material,
    _objective_evidence,
    _probe_contract,
    _request,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_ROOT = REPO_ROOT / "evals/reference_course"


def test_assessment_contracts_cover_every_approved_objective_once() -> None:
    contracts = _assessment_contracts(REFERENCE_ROOT)

    assert list(contracts) == APPROVED_OBJECTIVE_IDS
    assert len({item["contract_id"] for item in contracts.values()}) == 3
    assert all(item["question_type"] == "short_answer" for item in contracts.values())


def test_qualification_modes_are_single_objective_and_exact_gradeable() -> None:
    contracts = _assessment_contracts(REFERENCE_ROOT)
    expected = {
        "qualify-resp-01": "OBJ-RESP-01",
        "qualify-resp-02": "OBJ-RESP-02",
        "qualify-resp-03": "OBJ-RESP-03",
    }

    for mode, objective_id in expected.items():
        probe = _probe_contract(mode, contracts)
        assert probe["requested_objective_ids"] == [objective_id]
        assert probe["item_limit"] == 1
        assert probe["assessment_contract"] == contracts[objective_id]
        assert "exact-gradeable" in probe["focus"]


def test_obj_resp_01_binding_contains_transition_evidence_not_neighboring_roles() -> None:
    contracts = _assessment_contracts(REFERENCE_ROOT)
    material = _material(REFERENCE_ROOT)
    bindings = _objective_evidence(REFERENCE_ROOT)
    request = _request("qualify-resp-01", material, bindings, contracts)

    resolved = OpenAIPracticeGenerationProvider._objective_bound_evidence(request)

    assert resolved is not None
    evidence = resolved["OBJ-RESP-01"]
    support_quotes = [item.quote for item in evidence.support]
    context_quotes = [item.quote for item in evidence.context]
    assert any(
        "converts pyruvate to acetyl-CoA" in quote for quote in support_quotes
    )
    assert any("four teaching stages" in quote for quote in context_quotes)
    assert evidence.required_claim_ids == ("pyruvate_to_acetyl_coa",)
    assert all(
        "terminal electron acceptor" not in quote for quote in support_quotes
    )
    assert all("Fermentation" not in quote for quote in support_quotes)


def test_each_qualification_request_has_distinct_evidence_scope_and_contract() -> None:
    contracts = _assessment_contracts(REFERENCE_ROOT)
    material = _material(REFERENCE_ROOT)
    bindings = _objective_evidence(REFERENCE_ROOT)
    requests = [
        _request(mode, material, bindings, contracts)
        for mode in ("qualify-resp-01", "qualify-resp-02", "qualify-resp-03")
    ]
    receipts = [
        build_practice_generation_request_contract(request) for request in requests
    ]

    assert len({receipt.request_contract_id for receipt in receipts}) == 3
    assert len({receipt.source_scope_hash for receipt in receipts}) == 3
    assert [receipt.requested_objective_ids for receipt in receipts] == [
        ["OBJ-RESP-01"],
        ["OBJ-RESP-02"],
        ["OBJ-RESP-03"],
    ]


def test_required_claims_are_bound_only_to_the_fragment_that_completes_them() -> None:
    bindings = {
        binding.objective_id: binding
        for binding in _objective_evidence(REFERENCE_ROOT)
    }

    oxygen_claims = {
        evidence.evidence_id: set(evidence.claim_ids)
        for evidence in bindings["OBJ-RESP-02"].support_evidence
    }
    assert "terminal_acceptor_enables_flow" not in oxygen_claims[
        "ev_resp02_forms_water"
    ]
    assert "terminal_acceptor_enables_flow" in oxygen_claims[
        "ev_resp02_flow_continues"
    ]

    fermentation_claims = {
        evidence.evidence_id: set(evidence.claim_ids)
        for evidence in bindings["OBJ-RESP-03"].support_evidence
    }
    assert "fermentation_lower_atp" not in fermentation_claims[
        "ev_resp03_no_oxygen_low_atp"
    ]
    assert "fermentation_lower_atp" in fermentation_claims[
        "ev_resp03_aerobic_comparison"
    ]


def test_qualification_matrix_records_human_decisions_separately_from_agent_precheck() -> None:
    with (
        REFERENCE_ROOT / "objective_qualification_evidence_roles_v2_2026-08-09.csv"
    ).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 3
    transition = next(row for row in rows if row["objective_id"] == "OBJ-RESP-01")
    assert transition["automated_publication_status"] == "PASS"
    assert transition["human_review_status"] == "HUMAN_QUALIFIED"
    assert transition["human_primary_label"] == "PASS_WITH_MINOR_EDIT"
    assert transition["failure_class"] == "NONE"
    oxygen = next(row for row in rows if row["objective_id"] == "OBJ-RESP-02")
    assert oxygen["automated_publication_status"] == "PASS"
    assert oxygen["human_review_status"] == "SIGNED_FAIL"
    assert oxygen["human_primary_label"] == "FAIL_PEDAGOGY"
    assert oxygen["agent_precheck"] == "RECOMMEND_FAIL_PEDAGOGY"
    fermentation = next(
        row for row in rows if row["objective_id"] == "OBJ-RESP-03"
    )
    assert fermentation["human_review_status"] == "SIGNED_FAIL"
    assert fermentation["human_primary_label"] == "FAIL_AMBIGUOUS"
    assert fermentation["agent_precheck"] == "RECOMMEND_FAIL_AMBIGUOUS"


def test_human_review_worksheet_binds_king_decisions_without_promoting_agent_precheck() -> None:
    with (
        REFERENCE_ROOT
        / "human_review_objective_qualification_evidence_roles_v2_2026-08-09.csv"
    ).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert {row["objective_id"] for row in rows} == set(APPROVED_OBJECTIVE_IDS)
    assert {row["agent_recommendation"] for row in rows} == {
        "PASS_WITH_MINOR_EDIT",
        "FAIL_PEDAGOGY",
        "FAIL_AMBIGUOUS",
    }
    expected = {
        "OBJ-RESP-01": "PASS_WITH_MINOR_EDIT",
        "OBJ-RESP-02": "FAIL_PEDAGOGY",
        "OBJ-RESP-03": "FAIL_AMBIGUOUS",
    }
    for row in rows:
        assert row["automated_publication_status"] == "PASS"
        assert row["artifact_sha256"]
        assert row["raw_provider_output_sha256"]
        assert row["human_primary_label"] == expected[row["objective_id"]]
        assert row["human_citation_reachable"] == "true"
        assert row["human_answer_correct"] == "true"
        assert row["human_objective_aligned"] in {"true", "false"}
        assert row["human_grade_fair"] in {"true", "false"}
        assert row["reviewer_id"] == "King"
        assert row["reviewed_at"] == "2026-08-09T21:33:40Z"
        assert len(row["signature"]) == 64


def test_v2_contracts_preserve_failed_outputs_and_remain_evaluation_only() -> None:
    payload = json.loads(
        (REFERENCE_ROOT / "assessment_contracts_v2.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload["status"] == "DESIGN_ONLY_NOT_RUN"
    by_objective = {
        item["objective_id"]: item for item in payload["contracts"]
    }
    assert set(by_objective) == {"OBJ-RESP-02", "OBJ-RESP-03"}
    assert all(
        item["question_type"] == "single_answer_multiple_choice"
        for item in by_objective.values()
    )
    assert all(
        item["implementation_status"]
        == "PARKED_UNTIL_BOUNDED_CHOICE_GRADER_EXISTS"
        for item in by_objective.values()
    )
    assert by_objective["OBJ-RESP-02"]["supersedes_contract_id"] == (
        "ac_resp_02_causal_role_v1"
    )
    assert by_objective["OBJ-RESP-03"]["supersedes_contract_id"] == (
        "ac_resp_03_bounded_contrast_v1"
    )


def test_v3_choice_contracts_are_machine_bounded_but_precall_blocked() -> None:
    payload = json.loads(
        (
            REFERENCE_ROOT / "assessment_contracts_v3_evaluation_only.json"
        ).read_text(encoding="utf-8")
    )
    evidence_by_objective = {
        binding.objective_id: {
            item.evidence_id for item in binding.support_evidence
        }
        for binding in _objective_evidence(REFERENCE_ROOT)
    }

    assert payload["status"] == "FROZEN_DESIGN_PRECALL_BLOCKED"
    assert payload["assessment_format_precedence"] == {
        "applies_to_objective_ids": ["OBJ-RESP-02", "OBJ-RESP-03"],
        "source_packet_is_content_evidence_only": True,
        "qualification_question_type": "single_answer_multiple_choice",
        "supersedes_source_packet_short_answer_format_statement": True,
    }
    contracts = {item["objective_id"]: item for item in payload["contracts"]}
    assert set(contracts) == {"OBJ-RESP-02", "OBJ-RESP-03"}
    for objective_id, contract in contracts.items():
        assert contract["question_type"] == "single_answer_multiple_choice"
        assert contract["implementation_status"] == (
            "PARKED_UNTIL_BOUNDED_CHOICE_GRADER_EXISTS"
        )
        assert contract["provider_qualification_status"] == "BLOCKED_PRECALL"
        assert set(contract["required_evidence_ids"]) == evidence_by_objective[
            objective_id
        ]
        options = contract["options"]
        assert len(options) == contract["option_constraints"]["option_count"] == 4
        assert len({item["option_id"] for item in options}) == 4
        assert len({" ".join(item["text"].casefold().split()) for item in options}) == 4
        assert max(len(item["text"].split()) for item in options) == min(
            len(item["text"].split()) for item in options
        )
        correct = [item for item in options if item["role"] == "correct"]
        assert len(correct) == 1
        assert correct[0]["option_id"] == contract["correct_option_id"]
        required_claims = set(contract["required_claim_ids"])
        assert set(correct[0]["entailed_claim_ids"]) == required_claims
        assert correct[0]["defect"] is None
        for distractor in [item for item in options if item["role"] == "distractor"]:
            defect = distractor["defect"]
            assert defect["kind"] == "contradicted_claim"
            assert defect["claim_id"] in required_claims
            assert set(distractor["entailed_claim_ids"]) == required_claims - {
                defect["claim_id"]
            }
            assert set(defect["counterevidence_ids"]).issubset(
                evidence_by_objective[objective_id]
            )
