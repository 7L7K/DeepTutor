from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.c3_human_review import (
    verify_bounded_answer_amendment,
    verify_human_review_record,
)


REFERENCE_ROOT = Path(__file__).resolve().parents[3] / "evals/reference_course"
REVIEW_ROOT = REFERENCE_ROOT / "human_reviews"


def test_king_historical_dispositions_are_artifact_bound_and_tamper_evident() -> None:
    expected = {
        "OBJ-RESP-01": "PASS_WITH_MINOR_EDIT",
        "OBJ-RESP-02": "FAIL_PEDAGOGY",
        "OBJ-RESP-03": "FAIL_AMBIGUOUS",
    }
    records = [
        verify_human_review_record(REFERENCE_ROOT, path)
        for path in sorted(REVIEW_ROOT.glob("obj-resp-*-v1.json"))
    ]

    assert len(records) == 3
    assert {record.objective_id: record.decision for record in records} == expected
    assert {record.reviewer_id for record in records} == {"King"}
    assert {record.reviewed_at for record in records} == {"2026-08-09T21:33:40Z"}
    transition = next(
        record for record in records if record.objective_id == "OBJ-RESP-01"
    )
    assert transition.amendment_sha256 is not None
    assert all(
        record.amendment_sha256 is None
        for record in records
        if record.objective_id != "OBJ-RESP-01"
    )


def test_signed_bounded_amendment_is_human_bound_and_successor_only() -> None:
    path = (
        REFERENCE_ROOT
        / "reviewer_amendments/obj-resp-01-bounded-short-answer-v2.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    verified = verify_bounded_answer_amendment(REFERENCE_ROOT, path)

    assert verified.reviewer_id == "King"
    assert verified.reviewed_at == "2026-08-09T21:33:40Z"
    assert payload["status"] == "APPROVED_HUMAN_REVIEWED"
    assert "successor immutable Practice revision" in payload["application_policy"]
    assert verified.answer_contract.kind == "bounded_short_answer_v1"


def test_human_review_worksheet_matches_verified_records() -> None:
    with (
        REFERENCE_ROOT
        / "human_review_objective_qualification_evidence_roles_v2_2026-08-09.csv"
    ).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    records = {
        record.objective_id: record
        for record in (
            verify_human_review_record(REFERENCE_ROOT, path)
            for path in REVIEW_ROOT.glob("obj-resp-*-v1.json")
        )
    }

    assert len(rows) == len(records) == 3
    for row in rows:
        record = records[row["objective_id"]]
        assert row["human_primary_label"] == record.decision
        assert row["reviewer_id"] == record.reviewer_id
        assert row["reviewed_at"] == record.reviewed_at
        assert row["signature"] == record.canonical_review_payload_sha256
