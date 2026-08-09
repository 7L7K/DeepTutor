from __future__ import annotations

import csv
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
    quotes = [
        quote
        for receipt_quotes in resolved["OBJ-RESP-01"].values()
        for quote in receipt_quotes
    ]
    assert any("converts pyruvate to acetyl-CoA" in quote for quote in quotes)
    assert all("terminal electron acceptor" not in quote for quote in quotes)
    assert all("Fermentation" not in quote for quote in quotes)


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


def test_qualification_matrix_does_not_claim_agent_review_as_human_review() -> None:
    with (
        REFERENCE_ROOT / "objective_qualification_2026-08-09.csv"
    ).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 3
    oxygen = next(row for row in rows if row["objective_id"] == "OBJ-RESP-02")
    assert oxygen["automated_publication_status"] == "PASS"
    assert oxygen["human_review_status"] == "OPEN"
    assert oxygen["human_primary_label"] == ""
    assert oxygen["agent_precheck"] == "POTENTIAL_FAIL_PEDAGOGY"
