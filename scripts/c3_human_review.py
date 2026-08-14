"""Fail-closed verification for C3 internal human-review records.

The canonical SHA-256 values in these records make accidental or silent
project-file changes detectable. They are not cryptographic identity proofs,
legal signatures, or evidence that an agent may approve educational content.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from deeptutor.courses.practice_models import BoundedShortAnswerContract

_IDENTITY_CLAIM = "INTERNAL_PROJECT_REVIEW_NOT_LEGAL_OR_CRYPTOGRAPHIC_IDENTITY"
_DECISIONS = {
    "PASS",
    "PASS_WITH_MINOR_EDIT",
    "FAIL_INCORRECT",
    "FAIL_UNSUPPORTED",
    "FAIL_AMBIGUOUS",
    "FAIL_WRONG_SCOPE",
    "FAIL_PEDAGOGY",
    "FAIL_PRIVACY",
}


@dataclass(frozen=True)
class VerifiedHumanReviewRecord:
    review_id: str
    reviewer_id: str
    reviewed_at: str
    objective_id: str
    assessment_contract_id: str
    decision: str
    artifact_sha256: str
    amendment_sha256: str | None
    canonical_review_payload_sha256: str


@dataclass(frozen=True)
class VerifiedBoundedAnswerAmendment:
    amendment_id: str
    reviewer_id: str
    reviewed_at: str
    provider_artifact_sha256: str
    canonical_signature_sha256: str
    answer_contract: BoundedShortAnswerContract


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _bounded_string(value: object, *, field: str, limit: int = 4_000) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > limit
    ):
        raise ValueError(f"{field} must be a non-empty bounded string")
    return value


def _review_timestamp(value: object) -> str:
    timestamp = _bounded_string(value, field="reviewed_at", limit=40)
    if not timestamp.endswith("Z"):
        raise ValueError("reviewed_at must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(timestamp[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("reviewed_at must be an ISO-8601 timestamp") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("reviewed_at must be an explicit UTC timestamp")
    return timestamp


def _inside(reference_root: Path, relative_path: object, *, field: str) -> Path:
    relative = _bounded_string(relative_path, field=field, limit=500)
    path = (reference_root / relative).resolve()
    try:
        path.relative_to(reference_root)
    except ValueError as exc:
        raise ValueError(f"{field} must stay inside the reference fixture") from exc
    if not path.is_file():
        raise ValueError(f"{field} does not resolve to a file")
    return path


def verify_bounded_answer_amendment(
    reference_root: Path,
    amendment_path: Path,
) -> VerifiedBoundedAnswerAmendment:
    reference_root = reference_root.resolve()
    amendment_path = amendment_path.resolve()
    try:
        amendment_path.relative_to(reference_root)
    except ValueError as exc:
        raise ValueError("reviewer amendment must stay inside the reference fixture") from exc
    payload = json.loads(amendment_path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "amendment_id",
        "supersedes_amendment_id",
        "superseded_amendment_sha256",
        "objective_id",
        "assessment_contract_id",
        "question_index",
        "provider_artifact",
        "provider_artifact_sha256",
        "raw_provider_output_sha256",
        "amendment_kind",
        "grading_algorithm",
        "status",
        "candidate_answer_contract",
        "normalization_contract",
        "semantic_matching",
        "agent_recommendation",
        "agent_authority",
        "rationale",
        "immutable_provider_fields",
        "reviewer",
        "reviewed_at",
        "signature_version",
        "signature",
        "application_policy",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("bounded reviewer amendment schema is invalid")
    if (
        payload["schema_version"] != "c3-reviewer-bounded-short-answer-amendment-v2"
        or payload["objective_id"] != "OBJ-RESP-01"
        or payload["question_index"] != 1
        or payload["amendment_kind"] != "replace_exact_with_bounded_short_answer"
        or payload["grading_algorithm"] != "bounded_short_answer_v1"
        or payload["status"] != "APPROVED_HUMAN_REVIEWED"
        or payload["agent_recommendation"] != "PASS_WITH_MINOR_EDIT"
        or payload["agent_authority"] != "NON_DECISION_RECOMMENDATION"
        or payload["signature_version"]
        != "c3-canonical-review-payload-sha256-v1"
    ):
        raise ValueError("bounded reviewer amendment contract is invalid")
    reviewer_id = _bounded_string(payload["reviewer"], field="reviewer")
    reviewed_at = _review_timestamp(payload["reviewed_at"])
    artifact_path = _inside(
        reference_root, payload["provider_artifact"], field="provider_artifact"
    )
    artifact_sha256 = _sha256(
        payload["provider_artifact_sha256"], field="provider_artifact_sha256"
    )
    if _file_sha256(artifact_path) != artifact_sha256:
        raise ValueError("provider artifact hash does not match the amendment")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    if (
        artifact.get("provider_runtime", {}).get("raw_provider_output_sha256")
        != payload["raw_provider_output_sha256"]
        or artifact.get("assessment_contract", {}).get("contract_id")
        != payload["assessment_contract_id"]
    ):
        raise ValueError("provider artifact identity does not match the amendment")
    try:
        answer_contract = BoundedShortAnswerContract.model_validate(
            payload["candidate_answer_contract"]
        )
    except ValidationError as exc:
        raise ValueError("bounded answer contract is invalid") from exc
    signature = _sha256(payload["signature"], field="signature")
    signed_payload = dict(payload)
    signed_payload.pop("signature")
    if canonical_sha256(signed_payload) != signature:
        raise ValueError("bounded amendment canonical signature does not match")
    return VerifiedBoundedAnswerAmendment(
        amendment_id=_bounded_string(payload["amendment_id"], field="amendment_id"),
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
        provider_artifact_sha256=artifact_sha256,
        canonical_signature_sha256=signature,
        answer_contract=answer_contract,
    )


def verify_human_review_record(
    reference_root: Path,
    record_path: Path,
) -> VerifiedHumanReviewRecord:
    reference_root = reference_root.resolve()
    record_path = record_path.resolve()
    try:
        record_path.relative_to(reference_root)
    except ValueError as exc:
        raise ValueError("human review record must stay inside the reference fixture") from exc
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "review_id",
        "reviewer_id",
        "reviewed_at",
        "identity_claim",
        "objective_id",
        "assessment_contract_id",
        "question_index",
        "decision",
        "artifact",
        "artifact_sha256",
        "raw_provider_output_sha256",
        "amendment",
        "amendment_sha256",
        "review_note",
        "canonical_review_payload_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("human review record schema is invalid")
    if (
        payload["schema_version"] != "c3-human-review-record-v1"
        or payload["identity_claim"] != _IDENTITY_CLAIM
        or payload["decision"] not in _DECISIONS
        or not isinstance(payload["question_index"], int)
        or payload["question_index"] < 1
    ):
        raise ValueError("human review record contract is invalid")
    review_id = _bounded_string(payload["review_id"], field="review_id", limit=160)
    reviewer_id = _bounded_string(payload["reviewer_id"], field="reviewer_id")
    reviewed_at = _review_timestamp(payload["reviewed_at"])
    objective_id = _bounded_string(payload["objective_id"], field="objective_id")
    assessment_contract_id = _bounded_string(
        payload["assessment_contract_id"], field="assessment_contract_id"
    )
    _bounded_string(payload["review_note"], field="review_note")
    artifact_path = _inside(reference_root, payload["artifact"], field="artifact")
    artifact_sha256 = _sha256(payload["artifact_sha256"], field="artifact_sha256")
    if _file_sha256(artifact_path) != artifact_sha256:
        raise ValueError("human review artifact hash does not match")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact_contract = artifact.get("assessment_contract")
    if (
        artifact.get("provider_runtime", {}).get("raw_provider_output_sha256")
        != payload["raw_provider_output_sha256"]
        or (
            artifact_contract is not None
            and (
                not isinstance(artifact_contract, dict)
                or artifact_contract.get("contract_id") != assessment_contract_id
            )
        )
    ):
        raise ValueError("human review artifact identity does not match")
    questions = artifact.get("validated_output", {}).get("questions", [])
    index = payload["question_index"] - 1
    if (
        not isinstance(questions, list)
        or index >= len(questions)
        or questions[index].get("objective_ids") != [objective_id]
    ):
        raise ValueError("human review question identity does not match")
    amendment_sha256: str | None = None
    if payload["amendment"] is None or payload["amendment_sha256"] is None:
        if payload["amendment"] is not None or payload["amendment_sha256"] is not None:
            raise ValueError("human review amendment binding is incomplete")
    else:
        amendment_path = _inside(
            reference_root, payload["amendment"], field="amendment"
        )
        amendment_sha256 = _sha256(
            payload["amendment_sha256"], field="amendment_sha256"
        )
        if _file_sha256(amendment_path) != amendment_sha256:
            raise ValueError("human review amendment hash does not match")
        amendment = verify_bounded_answer_amendment(reference_root, amendment_path)
        if (
            amendment.reviewer_id != reviewer_id
            or amendment.reviewed_at != reviewed_at
            or amendment.provider_artifact_sha256 != artifact_sha256
        ):
            raise ValueError("human review amendment authority does not match")
    canonical = _sha256(
        payload["canonical_review_payload_sha256"],
        field="canonical_review_payload_sha256",
    )
    canonical_payload = dict(payload)
    canonical_payload.pop("canonical_review_payload_sha256")
    if canonical_sha256(canonical_payload) != canonical:
        raise ValueError("canonical human review payload hash does not match")
    return VerifiedHumanReviewRecord(
        review_id=review_id,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
        objective_id=objective_id,
        assessment_contract_id=assessment_contract_id,
        decision=payload["decision"],
        artifact_sha256=artifact_sha256,
        amendment_sha256=amendment_sha256,
        canonical_review_payload_sha256=canonical,
    )


__all__ = [
    "VerifiedBoundedAnswerAmendment",
    "VerifiedHumanReviewRecord",
    "canonical_sha256",
    "verify_bounded_answer_amendment",
    "verify_human_review_record",
]
