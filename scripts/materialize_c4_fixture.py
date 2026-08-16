#!/usr/bin/env python3
"""Materialize the frozen C3-H3 artifacts into a disposable Course.

This is a proof harness, not a provider or a production import path.  It uses
the same generated Practice and Review repositories as the authenticated API,
while retaining the source artifact digests and the mechanical field mapping
in the C4 fixture receipt.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deeptutor.courses.generation_models import (
    GeneratedPracticeOutput,
    GeneratedPracticeQuestion,
    PracticeGenerationRequestContract,
)
from deeptutor.courses.generation_repository import CoursePracticeGenerationRepository
from deeptutor.courses.practice_models import (
    BoundedShortAnswerContract,
    PracticeCitation,
    PracticeSourceReceipt,
    SingleChoiceAnswerContract,
    SingleChoiceOption,
    normalize_bounded_short_answer,
)
from deeptutor.courses.repository import CourseRepository
from deeptutor.multi_user.paths import get_personal_path_service

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIMARY = REPO_ROOT / "docs/verification/2026-08-10-teeechr-c3-final-learning-loop-v3-1/primary/model-qualified-candidate.json"
REMEDIATION = REPO_ROOT / "docs/verification/2026-08-10-teeechr-c3-final-learning-loop-v3-1-remediation-v2/remediation/model-qualified-candidate.json"
EVIDENCE = REPO_ROOT / "evals/reference_course/objective_evidence_roles_v2.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def option_id(artifact_hash: str, ordinal: int, option_key: str) -> str:
    return "opt_" + hashlib.sha256(
        f"c4:{artifact_hash}:{ordinal}:{option_key}".encode()
    ).hexdigest()[:32]


def source_binding(evidence: dict, objective_id: str) -> dict:
    return next(item for item in evidence["bindings"] if item["objective_id"] == objective_id)


def citation(
    binding: dict,
    evidence_id: str,
    *,
    source_id: str,
    source_revision: int,
    content_sha256: str,
) -> PracticeCitation:
    span = next(item for item in binding["support_evidence"] if item["evidence_id"] == evidence_id)
    return PracticeCitation(
        source_id=source_id,
        source_revision=source_revision,
        content_sha256=content_sha256,
        locator={
            "evidence_id": evidence_id,
            "start_char": span["start_char"],
            "end_char": span["end_char"],
            "evidence_quote": span["quote"],
            "offsets_version": "exact-char-v1",
        },
    )


def primary_output(
    artifact: dict,
    artifact_hash: str,
    bindings: dict[str, dict],
    *,
    source_id: str,
    source_revision: int,
    content_sha256: str,
) -> GeneratedPracticeOutput:
    questions: list[GeneratedPracticeQuestion] = []
    for ordinal, raw in enumerate(artifact["questions"], 1):
        objective_id = raw["objective_ids"][0]
        binding = bindings[objective_id]
        citations = [
            citation(
                binding,
                evidence_id,
                source_id=source_id,
                source_revision=source_revision,
                content_sha256=content_sha256,
            )
            for evidence_id in raw["citation_evidence_ids"]
        ]
        if raw["question_type"] == "bounded_short_answer_v1":
            canonical = normalize_bounded_short_answer(raw["answer_text"])
            accepted = []
            for item in [*raw["accepted_answers"]]:
                normalized = normalize_bounded_short_answer(item)
                if normalized != canonical and normalized not in accepted:
                    accepted.append(normalized)
            answer_contract = BoundedShortAnswerContract(
                kind="bounded_short_answer_v1",
                canonical_answer=raw["answer_text"],
                accepted_normalized_answers=[canonical, *accepted],
                normalization_version="bounded-text-normalization-v1",
            )
            question_type = "short_answer"
            options = []
        else:
            runtime_options = [
                SingleChoiceOption(
                    option_id=option_id(artifact_hash, ordinal, item["option_key"]),
                    text=item["text"],
                )
                for item in raw["options"]
            ]
            by_key = {
                item["option_key"]: runtime.option_id
                for item, runtime in zip(raw["options"], runtime_options)
            }
            answer_contract = SingleChoiceAnswerContract(
                kind="single_choice_v1",
                correct_option_id=by_key[raw["correct_option_key"]],
            )
            question_type = "single_choice"
            options = runtime_options
        questions.append(
            GeneratedPracticeQuestion(
                question_type=question_type,
                prompt=raw["prompt"],
                options=options,
                answer_contract=answer_contract,
                explanation=raw["explanation"],
                objective_ids=raw["objective_ids"],
                citations=citations,
            )
        )
    scope_hash = hashlib.sha256(
        json.dumps(
            [{"source_id": source_id, "source_revision": source_revision, "content_sha256": content_sha256}],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return GeneratedPracticeOutput(
        provider_label="qualified-artifact",
        requested_model="gpt-5.6-luna",
        actual_model="gpt-5.6-luna",
        request_id=f"artifact:{artifact_hash}",
        response_status="archived-model-qualified",
        prompt_version="c3-final-set-plan-v3",
        schema_version="c3-qualified-candidate-v3",
        reasoning_effort="high",
        request_contract=PracticeGenerationRequestContract(
            request_contract_id="pgc_c4_primary_materialization",
            requested_objective_ids=["OBJ-RESP-01", "OBJ-RESP-02", "OBJ-RESP-03"],
            source_scope_hash=scope_hash,
            generation_purpose="practice",
        ),
        questions=questions,
    )


def make_course(owner_id: str) -> tuple[CourseRepository, object, object]:
    paths = get_personal_path_service(owner_id)
    courses = CourseRepository(paths.get_courses_db(), owner_id)
    course = courses.create_course("Biology 101")
    artifact_evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    source_hash = artifact_evidence["bindings"][0]["receipt"]["content_sha256"]
    source = courses.create_source(
        course.id,
        kind="notes",
        display_name="Cellular Respiration Course Transcript",
        manifest=[],
        content_sha256=source_hash,
        operation_id="c4_fixture_source_operation",
        idempotency_key="c4_fixture_source",
    )
    source = courses.transition_source(
        course.id,
        source.id,
        operation_id="c4_fixture_source_operation",
        expected_source_revision=source.revision,
        expected_course_revision=course.revision,
        expected_write_epoch=course.write_epoch,
        state="ready",
    )
    return courses, course, source


def materialize_primary(courses: CourseRepository, course: object, source: object, primary: dict, evidence: dict) -> dict:
    generation = CoursePracticeGenerationRepository(courses)
    current_course = courses.get_course(course.id)
    request = generation.create_generated_practice(
        course.id,
        title="Biology 101 Practice",
        source_ids=[source.id],
        objective_ids=["OBJ-RESP-01", "OBJ-RESP-02", "OBJ-RESP-03"],
        idempotency_key="c4_primary_qualified_materialization",
        expected_course_write_epoch=current_course.write_epoch,
        item_limit=3,
        context_char_limit=12_000,
        focus="Cellular respiration response objectives",
        quality_profile="c3-biology-v1",
    )
    running, claimed = generation.claim_operation(course.id, request.operation.id)
    assert claimed and running.state == "running"
    output = primary_output(
        primary,
        digest(PRIMARY),
        {item["objective_id"]: item for item in evidence["bindings"]},
        source_id=source.id,
        source_revision=source.revision,
        content_sha256=source.content_sha256,
    )
    completed = generation.complete_operation(
        course.id,
        request.operation.id,
        output,
        account_active=True,
        material_receipts=[
            PracticeSourceReceipt(
                source_id=source.id,
                source_revision=source.revision,
                content_sha256=source.content_sha256,
            )
        ],
    )
    assert completed.state == "completed"
    revision = generation.get_operation(course.id, request.operation.id)
    return {
        "practice_set_id": request.practice_set_id,
        "revision_id": request.practice_set_revision_id,
        "generation_operation_id": request.operation.id,
        "generation_state": revision.state,
        "artifact_sha256": digest(PRIMARY),
        "artifact_path": str(PRIMARY.relative_to(REPO_ROOT)),
        "question_count": len(primary["questions"]),
        "objectives": [item["objective_id"] for item in evidence["bindings"]],
    }


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: materialize_c4_fixture.py OWNER_ID OUTPUT_JSON")
    owner_id, output_path = sys.argv[1], Path(sys.argv[2])
    primary = json.loads(PRIMARY.read_text(encoding="utf-8"))
    remediation = json.loads(REMEDIATION.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    courses, course, source = make_course(owner_id)
    practice = materialize_primary(courses, course, source, primary, evidence)
    payload = {
        "status": "C4_FIXTURE_READY",
        "owner_id": owner_id,
        "course_id": course.id,
        "course_title": course.title,
        "source_id": source.id,
        "source_revision": source.revision,
        "source_content_sha256": source.content_sha256,
        "practice": practice,
        "remediation_artifact_sha256": digest(REMEDIATION),
        "remediation_artifact_path": str(REMEDIATION.relative_to(REPO_ROOT)),
        "remediation_question_count": len(remediation["questions"]),
        "provider_calls": 0,
        "human_approval": False,
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_path.chmod(0o600)


if __name__ == "__main__":
    main()
