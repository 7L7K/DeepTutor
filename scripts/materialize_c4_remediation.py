#!/usr/bin/env python3
"""Publish the already-qualified two-item remediation into Course Review."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deeptutor.courses.flashcard_generation_models import (
    FlashcardCandidatePublication,
    FlashcardCitation,
    FlashcardGenerationBrief,
    FlashcardSourceReceipt,
    GeneratedFlashcard,
    GeneratedFlashcardOutput,
)
from deeptutor.courses.flashcard_generation_repository import CourseFlashcardGenerationRepository
from deeptutor.courses.grading_repository import CourseGradingRepository
from deeptutor.courses.repository import CourseRepository
from deeptutor.multi_user.paths import get_personal_path_service


REPO_ROOT = Path(__file__).resolve().parents[1]
REMEDIATION = REPO_ROOT / "docs/verification/2026-08-10-teeechr-c3-final-learning-loop-v3-1-remediation-v2/remediation/model-qualified-candidate.json"
EVIDENCE = REPO_ROOT / "evals/reference_course/objective_evidence_roles_v2.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: materialize_c4_remediation.py OWNER_ID FIXTURE_JSON ATTEMPT_ID")
    owner_id, fixture_path, attempt_id = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    remediation = json.loads(REMEDIATION.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    bindings = {item["objective_id"]: item for item in evidence["bindings"]}
    paths = get_personal_path_service(owner_id)
    courses = CourseRepository(paths.get_courses_db(), owner_id)
    course = courses.get_course(fixture["course_id"])
    grading = CourseGradingRepository(courses)
    provenance = grading.remediation_provenance(course.id, attempt_id)
    assert provenance["practice_set_id"] == fixture["practice"]["practice_set_id"]
    assert set(provenance["objective_ids"]) == {"OBJ-RESP-02", "OBJ-RESP-03"}
    assert len(provenance["practice_question_ids"]) == 2
    source_receipt = {
        "source_id": fixture["source_id"],
        "source_revision": fixture["source_revision"],
        "content_sha256": fixture["source_content_sha256"],
    }

    def citation(objective_id: str, evidence_id: str) -> FlashcardCitation:
        span = next(
            item
            for item in bindings[objective_id]["support_evidence"]
            if item["evidence_id"] == evidence_id
        )
        return FlashcardCitation(
            **source_receipt,
            locator={
                "evidence_id": evidence_id,
                "start_char": span["start_char"],
                "end_char": span["end_char"],
                "evidence_quote": span["quote"],
                "offsets_version": "exact-char-v1",
            },
        )

    cards: list[GeneratedFlashcard] = []
    for raw in remediation["questions"]:
        objective_id = raw["objective_ids"][0]
        correct = next(
            item["text"]
            for item in raw["options"]
            if item["option_key"] == raw["correct_option_key"]
        )
        cards.append(
            GeneratedFlashcard(
                prompt=raw["prompt"],
                answer=correct,
                card_type="recall",
                objective_ids=[objective_id],
                citations=[citation(objective_id, evidence_id) for evidence_id in raw["citation_evidence_ids"]],
            )
        )
    flashcards = CourseFlashcardGenerationRepository(courses)
    request = flashcards.create_generated_deck(
        course.id,
        title="Biology 101 Review",
        source_ids=[fixture["source_id"]],
        objective_ids=["OBJ-RESP-02", "OBJ-RESP-03"],
        idempotency_key="c4_remediation_qualified_materialization",
        expected_course_write_epoch=course.write_epoch,
        item_limit=2,
        context_char_limit=12_000,
        provider_available=True,
        generation_brief=FlashcardGenerationBrief(
            focus="Direct correction for the two missed Biology objectives",
            desired_count=2,
            card_type_mix=["recall"],
            difficulty="mixed",
            answer_length="medium",
            include_hints=False,
        ),
        origin={
            "kind": "practice_remediation",
            "practice_attempt_id": attempt_id,
            "practice_set_id": provenance["practice_set_id"],
            "practice_set_revision_id": provenance["practice_set_revision_id"],
            "practice_question_ids": provenance["practice_question_ids"],
            "grading_evidence_ids": provenance["grading_evidence_ids"],
        },
    )
    running, claimed = flashcards.claim_operation(course.id, request.operation.id)
    assert claimed and running.state == "running"
    staged = flashcards.stage_candidates(
        course.id,
        request.operation.id,
        GeneratedFlashcardOutput(
            provider_label="qualified-artifact",
            requested_model="gpt-5.6-luna",
            actual_model="gpt-5.6-luna",
            request_id=f"artifact:{digest(REMEDIATION)}",
            response_status="archived-model-qualified",
            prompt_version="c3-remediation-v2",
            schema_version="c3-qualified-candidate-v3",
            reasoning_effort="high",
            cards=cards,
        ),
        account_active=True,
        material_receipts=[FlashcardSourceReceipt(**source_receipt)],
    )
    published = flashcards.publish_candidates(
        course.id,
        request.operation.id,
        FlashcardCandidatePublication(
            candidate_ids=[candidate.candidate_id for candidate in (staged.candidates or [])],
            expected_candidate_revision=staged.candidate_revision,
        ),
        account_active=True,
    )
    assert published.state == "completed"
    fixture["remediation"] = {
        "deck_id": request.deck_id,
        "generation_operation_id": request.operation.id,
        "artifact_sha256": digest(REMEDIATION),
        "artifact_path": str(REMEDIATION.relative_to(REPO_ROOT)),
        "practice_attempt_id": attempt_id,
        "objectives": provenance["objective_ids"],
        "question_ids": provenance["practice_question_ids"],
        "grading_evidence_ids": provenance["grading_evidence_ids"],
        "card_count": len(cards),
        "candidate_revision": staged.candidate_revision,
        "publication_state": published.state,
        "provider_calls": 0,
        "human_approval": False,
    }
    fixture_path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fixture_path.chmod(0o600)


if __name__ == "__main__":
    main()
