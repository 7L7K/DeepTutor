from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.c3_human_review import canonical_sha256, verify_human_review_record

REFERENCE_ROOT = Path(__file__).resolve().parents[3] / "evals/reference_course"
ARTIFACT = (
    REFERENCE_ROOT
    / "provider_runs/2026-08-09-gpt-5.6-luna-c3-objective-evidence-v1/supported-one.json"
)


def _record_payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "c3-human-review-record-v1",
        "review_id": "hr_verifier_fixture",
        "reviewer_id": "fixture-reviewer",
        "reviewed_at": "2026-08-09T21:33:40Z",
        "identity_claim": (
            "INTERNAL_PROJECT_REVIEW_NOT_LEGAL_OR_CRYPTOGRAPHIC_IDENTITY"
        ),
        "objective_id": "OBJ-RESP-02",
        "assessment_contract_id": "ac_resp_02_causal_role_v1",
        "question_index": 1,
        "decision": "FAIL_PEDAGOGY",
        "artifact": "provider.json",
        "artifact_sha256": hashlib.sha256(ARTIFACT.read_bytes()).hexdigest(),
        "raw_provider_output_sha256": (
            "e97de6a3a356b3393f93da7b3683edef5c1cd96e45f00fcd201641e85ace4dd0"
        ),
        "amendment": None,
        "amendment_sha256": None,
        "review_note": "Fixture review used only to test canonical tamper detection.",
    }
    payload["canonical_review_payload_sha256"] = canonical_sha256(payload)
    return payload


def test_canonical_review_record_verifier_accepts_an_intact_payload(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "provider.json").write_bytes(ARTIFACT.read_bytes())
    record = fixture / "review.json"
    record.write_text(json.dumps(_record_payload()), encoding="utf-8")

    verified = verify_human_review_record(fixture, record)

    assert verified.objective_id == "OBJ-RESP-02"
    assert verified.decision == "FAIL_PEDAGOGY"


@pytest.mark.parametrize(
    "mutation",
    [
        "decision",
        "reviewer",
        "artifact_hash",
        "review_note",
        "canonical_hash",
    ],
)
def test_human_review_record_tampering_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    payload = _record_payload()
    fixture = tmp_path / mutation
    fixture.mkdir()
    (fixture / "provider.json").write_bytes(ARTIFACT.read_bytes())
    record = fixture / "review.json"

    if mutation == "decision":
        payload["decision"] = "PASS"
    elif mutation == "reviewer":
        payload["reviewer_id"] = "agent"
    elif mutation == "artifact_hash":
        payload["artifact_sha256"] = "0" * 64
    elif mutation == "review_note":
        payload["review_note"] = "Changed after review."
    else:
        payload["canonical_review_payload_sha256"] = "0" * 64
    record.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        verify_human_review_record(fixture, record)
