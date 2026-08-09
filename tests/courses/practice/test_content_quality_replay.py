from __future__ import annotations

from pathlib import Path

from deeptutor.courses.content_quality_replay import replay_manifest


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = (
    REPO_ROOT
    / "evals/reference_course/provider_runs/2026-08-09-c3-offline-replay-contracts.json"
)


def test_archived_c3_replay_is_provider_free_and_exposes_first_failures() -> None:
    ledger = replay_manifest(MANIFEST)

    assert ledger["provider_requests_made"] == 0
    by_case = {item["case_id"]: item for item in ledger["cases"]}
    assert set(by_case) == {
        "earlier_primary",
        "final_primary",
        "repeat",
        "unsupported",
        "remediation",
    }
    assert by_case["final_primary"]["first_failing_stage"] == (
        "RAW_RESPONSE_NOT_PRESERVED"
    )
    assert by_case["repeat"]["raw_response_provenance"] == "not_preserved"
    assert by_case["unsupported"]["items"][0]["stages"][
        "objective_allowlist"
    ] == "pass"
    assert by_case["unsupported"]["items"][0]["stages"][
        "request_objective_fidelity"
    ] == "fail"
    assert by_case["unsupported"]["previous_validator_result"]["status"] == (
        "PASS"
    )
    assert by_case["unsupported"]["current_validator_result"]["status"] == (
        "REJECT"
    )
    assert by_case["earlier_primary"]["items"][1][
        "first_failing_stage"
    ] == "answer_support"
    assert by_case["remediation"]["items"][0]["stages"][
        "answer_support"
    ] == "fail"
