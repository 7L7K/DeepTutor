"""Offline verification for immutable C3 reviewer answer amendments.

This derives a candidate exact-answer contract for qualification tests. It
does not mutate provider artifacts, ready Practice revisions, or grading
evidence, and an unsigned amendment is never eligible for publication.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import unicodedata

from deeptutor.courses.practice_models import ExactAnswerContract


@dataclass(frozen=True)
class VerifiedReviewerAnswerAmendment:
    effective_answer_contract: ExactAnswerContract
    eligible_for_publication: bool
    provider_artifact_sha256: str
    raw_provider_output_sha256: str
    base_answer_contract_sha256: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def verify_reviewer_answer_amendment(
    reference_root: Path,
    amendment_path: Path,
) -> VerifiedReviewerAnswerAmendment:
    """Bind an amendment to one archived artifact and derive its candidate contract."""

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
        "objective_id",
        "assessment_contract_id",
        "question_index",
        "provider_artifact",
        "provider_artifact_sha256",
        "raw_provider_output_sha256",
        "base_answer_contract_sha256",
        "amendment_kind",
        "grading_algorithm",
        "status",
        "primary_answer",
        "provider_accepted_answers",
        "additional_accepted_answers",
        "agent_recommendation",
        "agent_authority",
        "rationale",
        "immutable_provider_fields",
        "reviewer",
        "reviewed_at",
        "signature",
        "application_policy",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("reviewer amendment schema is invalid")
    if (
        payload["schema_version"] != "c3-reviewer-answer-amendment-v1"
        or payload["amendment_kind"] != "add_exact_accepted_answers"
        or payload["grading_algorithm"] != "exact-v1"
        or payload["agent_recommendation"] != "PASS_WITH_MINOR_EDIT"
        or payload["agent_authority"] != "NON_DECISION_RECOMMENDATION"
        or not isinstance(payload["question_index"], int)
        or payload["question_index"] < 1
    ):
        raise ValueError("reviewer amendment contract is invalid")

    artifact_path = (reference_root / payload["provider_artifact"]).resolve()
    try:
        artifact_path.relative_to(reference_root)
    except ValueError as exc:
        raise ValueError("provider artifact must stay inside the reference fixture") from exc
    if _sha256(artifact_path) != payload["provider_artifact_sha256"]:
        raise ValueError("provider artifact hash does not match the amendment")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    if (
        artifact.get("provider_runtime", {}).get("raw_provider_output_sha256")
        != payload["raw_provider_output_sha256"]
    ):
        raise ValueError("raw provider output hash does not match the amendment")
    if artifact.get("assessment_contract", {}).get("contract_id") != payload[
        "assessment_contract_id"
    ]:
        raise ValueError("assessment contract does not match the amendment")
    questions = artifact.get("validated_output", {}).get("questions", [])
    index = payload["question_index"] - 1
    if not isinstance(questions, list) or index >= len(questions):
        raise ValueError("reviewer amendment question index is invalid")
    question = questions[index]
    if question.get("objective_ids") != [payload["objective_id"]]:
        raise ValueError("objective does not match the amendment")
    base_contract = question.get("answer_contract")
    if not isinstance(base_contract, dict) or _canonical_sha256(base_contract) != payload[
        "base_answer_contract_sha256"
    ]:
        raise ValueError("base answer contract hash does not match the amendment")
    if (
        base_contract.get("kind") != "exact"
        or base_contract.get("answer") != payload["primary_answer"]
        or base_contract.get("accepted_answers", [])
        != payload["provider_accepted_answers"]
    ):
        raise ValueError("base answer contract does not match the amendment")

    additions = payload["additional_accepted_answers"]
    if (
        not isinstance(additions, list)
        or not additions
        or any(not isinstance(item, str) or not item.strip() for item in additions)
    ):
        raise ValueError("reviewer answer additions must be a nonempty string list")
    accepted = [*base_contract.get("accepted_answers", []), *additions]
    normalized = [_normalized(base_contract["answer"]), *map(_normalized, accepted)]
    if len(set(normalized)) != len(normalized):
        raise ValueError("reviewer answer amendment contains a duplicate")
    effective = ExactAnswerContract(
        kind="exact",
        answer=base_contract["answer"],
        accepted_answers=accepted,
    )

    signed_fields = (
        payload["reviewer"],
        payload["reviewed_at"],
        payload["signature"],
    )
    eligible = payload["status"] == "APPROVED_HUMAN_SIGNED" and all(
        isinstance(item, str) and bool(item.strip()) for item in signed_fields
    )
    if payload["status"] == "PROPOSED_PENDING_HUMAN_SIGNATURE":
        if any(item is not None for item in signed_fields):
            raise ValueError("pending reviewer amendment cannot contain partial signature data")
    elif not eligible:
        raise ValueError("reviewer amendment approval state is invalid")

    return VerifiedReviewerAnswerAmendment(
        effective_answer_contract=effective,
        eligible_for_publication=eligible,
        provider_artifact_sha256=payload["provider_artifact_sha256"],
        raw_provider_output_sha256=payload["raw_provider_output_sha256"],
        base_answer_contract_sha256=payload["base_answer_contract_sha256"],
    )


__all__ = [
    "VerifiedReviewerAnswerAmendment",
    "verify_reviewer_answer_amendment",
]
