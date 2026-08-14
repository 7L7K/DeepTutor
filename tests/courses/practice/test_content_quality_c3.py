from __future__ import annotations

from contextlib import nullcontext
import hashlib
from pathlib import Path

import pytest

from deeptutor.courses.attempt_repository import CourseAssessmentRepository
from deeptutor.courses.attempt_service import CourseAssessmentService
from deeptutor.courses.content_quality import (
    C3_BIOLOGY_PROFILE,
    ContentQualityError,
    validate_c3_output,
)
from deeptutor.courses.content_quality_repository import CourseContentQualityRepository
from deeptutor.courses.content_quality_service import CourseContentQualityService
from deeptutor.courses.flashcard_generation_models import (
    FlashcardCandidatePublication,
    FlashcardCitation,
    FlashcardSourceReceipt,
    GeneratedFlashcard,
    GeneratedFlashcardOutput,
)
from deeptutor.courses.flashcard_generation_repository import CourseFlashcardGenerationRepository
from deeptutor.courses.generation_models import (
    GeneratedPracticeOutput,
    GeneratedPracticeQuestion,
    GenerationSourceText,
    PracticeGenerationInput,
    PracticeObjectiveContextEvidence,
    PracticeObjectiveEvidenceBinding,
    PracticeObjectiveEvidencePolicy,
    PracticeObjectiveSupportEvidence,
    build_practice_generation_request_contract,
)
from deeptutor.courses.generation_provider import PracticeGenerationProvider
from deeptutor.courses.generation_repository import CoursePracticeGenerationRepository
from deeptutor.courses.generation_service import CoursePracticeGenerationService
from deeptutor.courses.grading_repository import CourseGradingRepository
from deeptutor.courses.grading_service import CourseGradingService
from deeptutor.courses.mastery_adapter import CourseMasteryAdapter
from deeptutor.courses.practice_models import (
    ExactAnswerContract,
    PracticeCitation,
    PracticeSourceReceipt,
)
from deeptutor.courses.practice_repository import CoursePracticeRepository
from deeptutor.courses.practice_service import CoursePracticeService
from deeptutor.courses.repository import CourseConflictError, CourseRepository
from deeptutor.learning.models import KnowledgePoint, KnowledgeType, LearningModule
from deeptutor.learning.storage import LearningStore

SOURCE_TEXT = (
    "[00:13:05] Oxygen is the terminal electron acceptor at the end of the "
    "aerobic electron transport chain. Oxygen accepts electrons and protons to form water."
)
SOURCE_HASH = hashlib.sha256(SOURCE_TEXT.encode()).hexdigest()


def _binding(
    objective_id: str,
    receipt: PracticeSourceReceipt,
    source_text: str,
    *,
    support_quotes: list[str],
    context_quotes: list[str] | None = None,
    claim_ids_by_quote: dict[str, list[str]] | None = None,
) -> PracticeObjectiveEvidenceBinding:
    contexts = []
    for ordinal, quote in enumerate(context_quotes or [], start=1):
        start = source_text.find(quote)
        assert start >= 0
        contexts.append(
            PracticeObjectiveContextEvidence(
                evidence_id=f"ev_{objective_id.lower()}_context_{ordinal}",
                quote=quote,
                start_char=start,
                end_char=start + len(quote),
            )
        )
    support = []
    for ordinal, quote in enumerate(support_quotes, start=1):
        start = source_text.find(quote)
        assert start >= 0
        support.append(
            PracticeObjectiveSupportEvidence(
                evidence_id=f"ev_{objective_id.lower()}_support_{ordinal}",
                quote=quote,
                start_char=start,
                end_char=start + len(quote),
                supports=["answer", "explanation"],
                claim_ids=(claim_ids_by_quote or {}).get(
                    quote, [f"claim_{objective_id.lower()}_{ordinal}"]
                ),
            )
        )
    return PracticeObjectiveEvidenceBinding(
        objective_id=objective_id,
        receipt=receipt,
        context_evidence=contexts,
        support_evidence=support,
    )


def _request() -> tuple[PracticeGenerationInput, GenerationSourceText]:
    receipt = PracticeSourceReceipt(
        source_id="src_" + "a" * 32,
        source_revision=1,
        content_sha256=SOURCE_HASH,
    )
    material = GenerationSourceText(receipt=receipt, text=SOURCE_TEXT)
    evidence_quote = "Oxygen accepts electrons and protons to form water."
    binding = _binding(
        "OBJ-RESP-02",
        receipt,
        SOURCE_TEXT,
        support_quotes=[evidence_quote],
        claim_ids_by_quote={
            evidence_quote: ["oxygen_accepts_and_forms_water"]
        },
    )
    return (
        PracticeGenerationInput(
            operation_id="opg_" + "b" * 32,
            owner_user_id="u_alice",
            course_id="crs_" + "c" * 32,
            practice_set_id="prc_" + "d" * 32,
            practice_set_revision_id="prv_" + "e" * 32,
            source_material=[material],
            objective_ids=["OBJ-RESP-02"],
            objective_evidence_bindings=[binding],
            required_claim_ids_by_objective={
                "OBJ-RESP-02": ["oxygen_accepts_and_forms_water"]
            },
            item_limit=1,
            context_char_limit=12_000,
            focus="oxygen in aerobic respiration",
            difficulty="mixed",
            timing_mode="untimed",
            quality_profile=C3_BIOLOGY_PROFILE,
        ),
        material,
    )


def _output(*, prompt: str = "What is oxygen's role at the end of aerobic respiration?", objectives=None):
    request, material = _request()
    return request, material, GeneratedPracticeOutput(
        provider_label="openai",
        request_contract=build_practice_generation_request_contract(request),
        requested_model="gpt-5.6-luna",
        actual_model="gpt-5.6-luna-2026-07-30",
        request_id="resp_c3_quality",
        input_tokens=120,
        output_tokens=80,
        latency_ms=420,
        pricing_version="openai-gpt-5.6-luna-2026-08-01",
        questions=[
            GeneratedPracticeQuestion(
                question_type="short_answer",
                prompt=prompt,
                answer_contract={"kind": "exact", "answer": "It accepts electrons and protons to form water."},
                explanation="The packet says oxygen accepts electrons and protons to form water.",
                objective_ids=["OBJ-RESP-02"] if objectives is None else objectives,
                citations=[
                    PracticeCitation(
                        **material.receipt.model_dump(),
                        locator={
                            "evidence_id": "ev_obj-resp-02_support_1",
                            "evidence_quote": "Oxygen accepts electrons and protons to form water.",
                            "offsets_version": "exact-char-v1",
                            "start_char": SOURCE_TEXT.find(
                                "Oxygen accepts electrons and protons to form water."
                            ),
                            "end_char": SOURCE_TEXT.find(
                                "Oxygen accepts electrons and protons to form water."
                            )
                            + len("Oxygen accepts electrons and protons to form water."),
                        },
                    )
                ],
            )
        ],
    )


def test_c3_validator_enriches_reachable_locator_and_preserves_no_id_prompt() -> None:
    request, material, output = _output()
    checked = validate_c3_output(request=request, output=output, material=[material])
    locator = checked.questions[0].citations[0].locator
    assert locator["evidence_quote"] in SOURCE_TEXT
    assert locator["start_char"] < locator["end_char"]
    assert locator["offsets_version"] == "exact-char-v1"
    assert "src_" not in checked.questions[0].prompt


def test_c3_validator_preserves_bounded_answer_variants_and_receipt_versions() -> None:
    request, material, output = _output()
    question = GeneratedPracticeQuestion.model_validate(
        output.questions[0].model_dump(mode="json")
        | {
            "answer_contract": {
                "kind": "exact",
                "answer": "water",
                "accepted_answers": ["the water molecule"],
            }
        }
    )
    checked = validate_c3_output(
        request=request,
        output=output.model_copy(
            update={
                "request_contract": build_practice_generation_request_contract(
                    request
                ),
                "questions": [question],
            }
        ),
        material=[material],
    )
    assert checked.questions[0].answer_contract.accepted_answers == ["the water molecule"]
    assert checked.questions[0].citations[0].locator["offsets_version"] == "exact-char-v1"


def test_c3_validator_accepts_collective_citations_and_short_polarity_answer() -> None:
    request, _original_material, output = _output(
        prompt="Does fermentation replace glycolysis?",
    )
    source_text = (
        "Fermentation does not replace glycolysis. "
        "It lets a cell keep glycolysis running by regenerating NAD+."
    )
    material = GenerationSourceText(
        receipt=PracticeSourceReceipt(
            source_id="src_" + "f" * 32,
            source_revision=1,
            content_sha256=hashlib.sha256(source_text.encode()).hexdigest(),
        ),
        text=source_text,
    )
    binding = _binding(
        "OBJ-RESP-02",
        material.receipt,
        source_text,
        support_quotes=[
            "Fermentation does not replace glycolysis.",
            "It lets a cell keep glycolysis running by regenerating NAD+.",
        ],
    )
    request = request.model_copy(update={"source_material": [material]})
    request = request.model_copy(
        update={
            "objective_evidence_bindings": [binding],
            "required_claim_ids_by_objective": {
                "OBJ-RESP-02": [
                    claim_id
                    for evidence in binding.support_evidence
                    for claim_id in evidence.claim_ids
                ]
            },
        }
    )
    question = GeneratedPracticeQuestion.model_validate(
        output.questions[0].model_dump(mode="json")
        | {
            "answer_contract": {"kind": "exact", "answer": "No"},
            "explanation": "Fermentation does not replace glycolysis; it regenerates NAD+ so glycolysis can continue.",
            "citations": [
                {
                    **material.receipt.model_dump(mode="json"),
                    "locator": {
                        "evidence_id": "ev_obj-resp-02_support_1",
                        "evidence_quote": "Fermentation does not replace glycolysis.",
                        "offsets_version": "exact-char-v1",
                        "start_char": 0,
                        "end_char": len("Fermentation does not replace glycolysis."),
                    },
                },
                {
                    **material.receipt.model_dump(mode="json"),
                    "locator": {
                        "evidence_id": "ev_obj-resp-02_support_2",
                        "evidence_quote": "It lets a cell keep glycolysis running by regenerating NAD+.",
                        "offsets_version": "exact-char-v1",
                        "start_char": source_text.find(
                            "It lets a cell keep glycolysis running by regenerating NAD+."
                        ),
                        "end_char": len(source_text),
                    },
                },
            ],
        }
    )
    checked = validate_c3_output(
        request=request,
        output=output.model_copy(
            update={
                "request_contract": build_practice_generation_request_contract(
                    request
                ),
                "questions": [question],
            }
        ),
        material=[material],
    )
    assert checked.questions[0].citations[0].locator["offsets_version"] == "exact-char-v1"


@pytest.mark.parametrize(
    ("prompt", "objectives", "code"),
    [
        ("What does src_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa do?", ["OBJ-RESP-02"], "PRIVACY_ID_LEAK"),
        ("What is oxygen's role at the end of aerobic respiration?", [], "OBJECTIVE_EMPTY"),
        ("What is oxygen's role at the end of aerobic respiration?", ["OBJ-RESP-01"], "OBJECTIVE_INVALID"),
    ],
)
def test_c3_validator_rejects_unsafe_or_unmapped_output(prompt, objectives, code) -> None:
    request, material, output = _output(prompt=prompt, objectives=objectives)
    with pytest.raises(ContentQualityError) as raised:
        validate_c3_output(request=request, output=output, material=[material])
    assert code in {item.code for item in raised.value.findings}


def test_c3_validator_rejects_neighboring_approved_objective_substitution() -> None:
    request, material, output = _output()
    request = request.model_copy(
        update={
            "objective_ids": ["OBJ-RESP-01", "OBJ-RESP-02"],
            "requested_objective_ids": ["OBJ-RESP-02"],
        }
    )
    question = output.questions[0].model_copy(
        update={"objective_ids": ["OBJ-RESP-01"]}
    )
    output = output.model_copy(
        update={
            "request_contract": build_practice_generation_request_contract(request),
            "questions": [question],
        }
    )

    with pytest.raises(ContentQualityError) as raised:
        validate_c3_output(request=request, output=output, material=[material])

    assert "REQUEST_OBJECTIVE_MISMATCH" in {
        item.code for item in raised.value.findings
    }


def test_c3_validator_rejects_reachable_citation_outside_objective_binding() -> None:
    request, material, output = _output()
    other_quote = "Oxygen is the terminal electron acceptor"
    question = output.questions[0].model_copy(
        update={
            "citations": [
                PracticeCitation(
                    **material.receipt.model_dump(),
                    locator={"evidence_quote": other_quote},
                )
            ]
        }
    )
    output = output.model_copy(update={"questions": [question]})

    with pytest.raises(ContentQualityError) as raised:
        validate_c3_output(request=request, output=output, material=[material])

    assert "CITATION_OUTSIDE_OBJECTIVE_EVIDENCE" in {
        item.code for item in raised.value.findings
    }


def test_c3_validator_accepts_support_evidence_while_context_remains_visible() -> None:
    context = "The pathway has four teaching stages."
    support = "Pyruvate is converted to acetyl-CoA."
    source_text = f"{context}\n{support}"
    receipt = PracticeSourceReceipt(
        source_id="src_" + "7" * 32,
        source_revision=1,
        content_sha256=hashlib.sha256(source_text.encode()).hexdigest(),
    )
    material = GenerationSourceText(receipt=receipt, text=source_text)
    binding = _binding(
        "OBJ-RESP-01",
        receipt,
        source_text,
        context_quotes=[context],
        support_quotes=[support],
        claim_ids_by_quote={support: ["pyruvate_to_acetyl_coa"]},
    )
    request, _old_material, template = _output()
    request = request.model_copy(
        update={
            "source_material": [material],
            "objective_ids": ["OBJ-RESP-01"],
            "requested_objective_ids": ["OBJ-RESP-01"],
            "objective_evidence_bindings": [binding],
            "required_claim_ids_by_objective": {
                "OBJ-RESP-01": ["pyruvate_to_acetyl_coa"]
            },
        }
    )
    evidence = binding.support_evidence[0]
    question = template.questions[0].model_copy(
        update={
            "prompt": "What does pyruvate become during pyruvate oxidation?",
            "answer_contract": ExactAnswerContract.model_validate({
                "kind": "exact",
                "answer": "acetyl-CoA",
                "accepted_answers": ["acetyl CoA", "acetyl coenzyme A"],
            }),
            "explanation": "Pyruvate is converted to acetyl-CoA.",
            "objective_ids": ["OBJ-RESP-01"],
            "citations": [
                PracticeCitation(
                    **receipt.model_dump(),
                    locator={
                        "evidence_id": evidence.evidence_id,
                        "evidence_quote": evidence.quote,
                        "offsets_version": "exact-char-v1",
                        "start_char": evidence.start_char,
                        "end_char": evidence.end_char,
                    },
                )
            ],
        }
    )
    output = template.model_copy(
        update={
            "request_contract": build_practice_generation_request_contract(request),
            "questions": [question],
        }
    )

    checked = validate_c3_output(
        request=request, output=output, material=[material]
    )

    assert checked.questions[0].citations[0].locator["evidence_id"] == (
        evidence.evidence_id
    )


def test_c3_validator_rejects_context_evidence_as_citation() -> None:
    context = "The pathway has four teaching stages."
    support = "Pyruvate is converted to acetyl-CoA."
    source_text = f"{context}\n{support}"
    receipt = PracticeSourceReceipt(
        source_id="src_" + "8" * 32,
        source_revision=1,
        content_sha256=hashlib.sha256(source_text.encode()).hexdigest(),
    )
    material = GenerationSourceText(receipt=receipt, text=source_text)
    binding = _binding(
        "OBJ-RESP-01",
        receipt,
        source_text,
        context_quotes=[context],
        support_quotes=[support],
    )
    request, _old_material, output = _output()
    request = request.model_copy(
        update={
            "source_material": [material],
            "objective_ids": ["OBJ-RESP-01"],
            "requested_objective_ids": ["OBJ-RESP-01"],
            "objective_evidence_bindings": [binding],
        }
    )
    evidence = binding.context_evidence[0]
    question = output.questions[0].model_copy(
        update={
            "objective_ids": ["OBJ-RESP-01"],
            "citations": [
                PracticeCitation(
                    **receipt.model_dump(),
                    locator={
                        "evidence_id": evidence.evidence_id,
                        "evidence_quote": evidence.quote,
                        "offsets_version": "exact-char-v1",
                        "start_char": evidence.start_char,
                        "end_char": evidence.end_char,
                    },
                )
            ],
        }
    )
    output = output.model_copy(
        update={
            "request_contract": build_practice_generation_request_contract(request),
            "questions": [question],
        }
    )

    with pytest.raises(ContentQualityError) as raised:
        validate_c3_output(request=request, output=output, material=[material])

    assert "CITATION_CONTEXT_ONLY" in {
        item.code for item in raised.value.findings
    }


def test_c3_validator_rejects_support_without_required_claim_coverage() -> None:
    identity = (
        "Oxygen is the terminal electron acceptor at the end of the aerobic "
        "electron transport chain."
    )
    causal = "Oxygen accepts electrons and protons to form water."
    request, material, output = _output()
    binding = _binding(
        "OBJ-RESP-02",
        material.receipt,
        material.text,
        support_quotes=[identity, causal],
        claim_ids_by_quote={
            identity: ["oxygen_is_terminal_acceptor"],
            causal: ["oxygen_accepts_and_forms_water"],
        },
    )
    request = request.model_copy(
        update={
            "objective_evidence_bindings": [binding],
            "required_claim_ids_by_objective": {
                "OBJ-RESP-02": ["oxygen_accepts_and_forms_water"]
            },
        }
    )
    evidence = binding.support_evidence[0]
    question = output.questions[0].model_copy(
        update={
            "citations": [
                PracticeCitation(
                    **material.receipt.model_dump(),
                    locator={
                        "evidence_id": evidence.evidence_id,
                        "evidence_quote": evidence.quote,
                        "offsets_version": "exact-char-v1",
                        "start_char": evidence.start_char,
                        "end_char": evidence.end_char,
                    },
                )
            ]
        }
    )
    output = output.model_copy(
        update={
            "request_contract": build_practice_generation_request_contract(request),
            "questions": [question],
        }
    )

    with pytest.raises(ContentQualityError) as raised:
        validate_c3_output(request=request, output=output, material=[material])

    assert "REQUIRED_CLAIM_UNCOVERED" in {
        item.code for item in raised.value.findings
    }


def test_c3_validator_requires_a_claim_contract_for_every_requested_objective() -> None:
    request, material, output = _output()
    request = request.model_copy(update={"required_claim_ids_by_objective": {}})
    output = output.model_copy(
        update={
            "request_contract": build_practice_generation_request_contract(request)
        }
    )

    with pytest.raises(ContentQualityError) as raised:
        validate_c3_output(request=request, output=output, material=[material])

    assert "REQUIRED_CLAIM_CONTRACT_MISSING" in {
        item.code for item in raised.value.findings
    }


@pytest.mark.parametrize(
    ("question_objectives", "expected_code"),
    [
        (["OBJ-A", "OBJ-B"], "REQUIRED_CLAIM_UNCOVERED"),
        (["OBJ-A"], "REQUEST_OBJECTIVE_COVERAGE_INCOMPLETE"),
    ],
)
def test_c3_validator_enforces_objective_qualified_claims_and_aggregate_coverage(
    question_objectives: list[str],
    expected_code: str,
) -> None:
    line_a = "Objective A has its own supporting fact."
    line_b = "Objective B has a different supporting fact."
    source_text = f"{line_a}\n{line_b}"
    receipt = PracticeSourceReceipt(
        source_id="src_" + "9" * 32,
        source_revision=1,
        content_sha256=hashlib.sha256(source_text.encode()).hexdigest(),
    )
    material = GenerationSourceText(receipt=receipt, text=source_text)
    binding_a = _binding(
        "OBJ-A",
        receipt,
        source_text,
        support_quotes=[line_a],
        claim_ids_by_quote={line_a: ["shared_claim_name"]},
    )
    binding_b = _binding(
        "OBJ-B",
        receipt,
        source_text,
        support_quotes=[line_b],
        claim_ids_by_quote={line_b: ["shared_claim_name"]},
    )
    request, _old_material, template = _output()
    request = PracticeGenerationInput.model_validate(
        {
            **request.model_dump(mode="python"),
            "source_material": [material.model_dump(mode="python")],
            "objective_ids": ["OBJ-A", "OBJ-B"],
            "requested_objective_ids": ["OBJ-A", "OBJ-B"],
            "objective_evidence_bindings": [
                binding_a.model_dump(mode="python"),
                binding_b.model_dump(mode="python"),
            ],
            "required_claim_ids_by_objective": {
                "OBJ-A": ["shared_claim_name"],
                "OBJ-B": ["shared_claim_name"],
            },
        }
    )
    evidence = binding_a.support_evidence[0]
    question = template.questions[0].model_copy(
        update={
            "prompt": "What supporting fact belongs to Objective A?",
            "answer_contract": ExactAnswerContract(
                kind="exact", answer="Objective A has its own supporting fact."
            ),
            "explanation": "Objective A has its own supporting fact.",
            "objective_ids": question_objectives,
            "citations": [
                PracticeCitation(
                    **receipt.model_dump(),
                    locator={
                        "evidence_id": evidence.evidence_id,
                        "evidence_quote": evidence.quote,
                        "offsets_version": "exact-char-v1",
                        "start_char": evidence.start_char,
                        "end_char": evidence.end_char,
                    },
                )
            ],
        }
    )
    output = template.model_copy(
        update={
            "request_contract": build_practice_generation_request_contract(request),
            "questions": [question],
        }
    )

    with pytest.raises(ContentQualityError) as raised:
        validate_c3_output(request=request, output=output, material=[material])

    assert expected_code in {
        item.code for item in raised.value.findings
    }


def test_c3_validator_enforces_required_exact_answer_variants_at_publication() -> None:
    context = "The pathway has four teaching stages."
    support = "Pyruvate is converted to acetyl-CoA."
    source_text = f"{context}\n{support}"
    receipt = PracticeSourceReceipt(
        source_id="src_" + "6" * 32,
        source_revision=1,
        content_sha256=hashlib.sha256(source_text.encode()).hexdigest(),
    )
    material = GenerationSourceText(receipt=receipt, text=source_text)
    binding = _binding(
        "OBJ-RESP-01",
        receipt,
        source_text,
        context_quotes=[context],
        support_quotes=[support],
        claim_ids_by_quote={support: ["pyruvate_to_acetyl_coa"]},
    )
    request, _old_material, template = _output()
    request = PracticeGenerationInput.model_validate(
        {
            **request.model_dump(mode="python"),
            "source_material": [material.model_dump(mode="python")],
            "objective_ids": ["OBJ-RESP-01"],
            "requested_objective_ids": ["OBJ-RESP-01"],
            "objective_evidence_bindings": [binding.model_dump(mode="python")],
            "required_claim_ids_by_objective": {
                "OBJ-RESP-01": ["pyruvate_to_acetyl_coa"]
            },
            "required_accepted_answers_by_objective": {
                "OBJ-RESP-01": [
                    "Pyruvate is converted to acetyl CoA.",
                    "Pyruvate is converted to acetyl coenzyme A.",
                ]
            },
        }
    )
    evidence = binding.support_evidence[0]
    question = template.questions[0].model_copy(
        update={
            "prompt": "What conversion links pyruvate to the citric acid cycle?",
            "answer_contract": ExactAnswerContract(
                kind="exact",
                answer="Pyruvate is converted to acetyl-CoA.",
                accepted_answers=["Pyruvate is converted to acetyl CoA."],
            ),
            "explanation": support,
            "objective_ids": ["OBJ-RESP-01"],
            "citations": [
                PracticeCitation(
                    **receipt.model_dump(),
                    locator={
                        "evidence_id": evidence.evidence_id,
                        "evidence_quote": evidence.quote,
                        "offsets_version": "exact-char-v1",
                        "start_char": evidence.start_char,
                        "end_char": evidence.end_char,
                    },
                )
            ],
        }
    )
    output = template.model_copy(
        update={
            "request_contract": build_practice_generation_request_contract(request),
            "questions": [question],
        }
    )

    with pytest.raises(ContentQualityError) as raised:
        validate_c3_output(request=request, output=output, material=[material])

    assert "ACCEPTED_ANSWER_VARIANTS_INCOMPLETE" in {
        item.code for item in raised.value.findings
    }


class _Provider:
    def generate(self, request):
        _request_data, material, output = _output()
        assert request.quality_profile == C3_BIOLOGY_PROFILE
        # A real provider must cite the resolved snapshot, not the fixture's
        # standalone synthetic receipt.  Keep this fake provider aligned with
        # that contract so the integration test exercises the publication
        # fence rather than failing on a test-only source mismatch.
        resolved_material = request.source_material[0]
        support = request.objective_evidence_bindings[0].support_evidence[0]
        question = output.questions[0].model_copy(
            update={
                "citations": [
                    PracticeCitation(
                        **resolved_material.receipt.model_dump(),
                        locator={
                            "evidence_id": support.evidence_id,
                            "evidence_quote": support.quote,
                            "offsets_version": "exact-char-v1",
                            "start_char": support.start_char,
                            "end_char": support.end_char,
                        },
                    )
                ]
            }
        )
        return output.model_copy(
            update={
                "request_contract": build_practice_generation_request_contract(
                    request
                ),
                "questions": [question],
            }
        )


class _Resolver:
    def resolve(self, *, receipts, **_kwargs):
        return [GenerationSourceText(receipt=receipts[0], text=SOURCE_TEXT)]


def _objective_evidence(
    request: PracticeGenerationInput,
) -> PracticeObjectiveEvidencePolicy:
    binding = _binding(
            "OBJ-RESP-02",
            request.source_material[0].receipt,
            request.source_material[0].text,
            support_quotes=[
                "Oxygen accepts electrons and protons to form water."
            ],
            claim_ids_by_quote={
                "Oxygen accepts electrons and protons to form water.": [
                    "oxygen_accepts_and_forms_water"
                ]
            },
    )
    return PracticeObjectiveEvidencePolicy(
        bindings=[binding],
        required_claim_ids_by_objective={
            "OBJ-RESP-02": ["oxygen_accepts_and_forms_water"]
        },
    )


def _objective_evidence_without_required_claims(
    request: PracticeGenerationInput,
) -> PracticeObjectiveEvidencePolicy:
    return _objective_evidence(request).model_copy(
        update={"required_claim_ids_by_objective": {}}
    )


def _objective_evidence_with_missing_required_variant(
    request: PracticeGenerationInput,
) -> PracticeObjectiveEvidencePolicy:
    return _objective_evidence(request).model_copy(
        update={
            "required_accepted_answers_by_objective": {
                "OBJ-RESP-02": [
                    "Oxygen accepts electrons and protons to form water."
                ]
            }
        }
    )


class _AbstainingProvider:
    def generate(self, request):
        return GeneratedPracticeOutput(
            provider_label="policy-local",
            request_contract=build_practice_generation_request_contract(request),
            outcome="abstain",
            abstain_reason="unsupported_by_allowed_sources",
            response_status="not_called",
            latency_ms=0,
            questions=[],
        )


def _ready_source(repo: CourseRepository, course_id: str):
    source = repo.create_source(
        course_id,
        kind="document",
        display_name="lecture_06_transcript.md",
        manifest=[],
        content_sha256=SOURCE_HASH,
        operation_id="op_source_c3",
    )
    return repo.transition_source(
        course_id,
        source.id,
        operation_id=source.operation_id or "",
        expected_source_revision=source.revision,
        expected_course_revision=repo.get_course(course_id).revision,
        expected_write_epoch=repo.get_course(course_id).write_epoch,
        state="ready",
    )


def test_c3_quality_profile_validates_before_ready_publication(tmp_path: Path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Biology 101")
    source = _ready_source(repo, course.id)
    service = CoursePracticeGenerationService(
        CoursePracticeGenerationRepository(repo),
        provider=_Provider(),
        source_text_resolver=_Resolver(),
        account_active=lambda _owner: True,
        identity_lock=lambda: nullcontext(),
        objective_evidence_resolver=_objective_evidence,
    )
    request = service.create_generated_practice(
        course.id,
        title="Cellular respiration quality quiz",
        source_ids=[source.id],
        objective_ids=["OBJ-RESP-02"],
        idempotency_key="c3-quality-operation",
        expected_course_write_epoch=repo.get_course(course.id).write_epoch,
        item_limit=1,
        quality_profile=C3_BIOLOGY_PROFILE,
    )
    completed = service.run_operation(course.id, request.operation.id)
    assert completed.state == "completed"
    practice = CoursePracticeService(CoursePracticeRepository(repo))
    revision = practice.get_revision(course.id, completed.practice_set_id, completed.practice_set_revision_id)
    assert revision.state == "ready"
    assert revision.generation_receipt is not None
    assert revision.generation_receipt["content_quality"] == "passed"
    question = practice.list_questions(course.id, completed.practice_set_id, revision.id)[0]
    assert question.citations[0].locator["start_char"] >= 0


@pytest.mark.parametrize(
    ("policy_resolver", "idempotency_key"),
    [
        (
            _objective_evidence_without_required_claims,
            "c3-missing-required-claim-policy",
        ),
        (
            _objective_evidence_with_missing_required_variant,
            "c3-missing-required-answer-variant",
        ),
    ],
)
def test_c3_service_fails_closed_when_policy_or_answer_variants_are_incomplete(
    tmp_path: Path,
    policy_resolver,
    idempotency_key: str,
) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Biology 101")
    source = _ready_source(repo, course.id)
    service = CoursePracticeGenerationService(
        CoursePracticeGenerationRepository(repo),
        provider=_Provider(),
        source_text_resolver=_Resolver(),
        account_active=lambda _owner: True,
        identity_lock=lambda: nullcontext(),
        objective_evidence_resolver=policy_resolver,
    )
    requested = service.create_generated_practice(
        course.id,
        title="Fail-closed C3 policy probe",
        source_ids=[source.id],
        objective_ids=["OBJ-RESP-02"],
        idempotency_key=idempotency_key,
        expected_course_write_epoch=repo.get_course(course.id).write_epoch,
        item_limit=1,
        quality_profile=C3_BIOLOGY_PROFILE,
    )

    terminal = service.run_operation(course.id, requested.operation.id)

    assert (terminal.state, terminal.error_code) == ("failed", "invalid_output")
    practice = CoursePracticeService(CoursePracticeRepository(repo))
    revision = practice.get_revision(
        course.id,
        terminal.practice_set_id,
        terminal.practice_set_revision_id,
    )
    assert revision.state == "draft"
    assert revision.generation_receipt is None
    assert practice.list_questions(
        course.id,
        terminal.practice_set_id,
        terminal.practice_set_revision_id,
    ) == []


def test_c3_abstention_leaves_draft_empty_and_never_publishes(
    tmp_path: Path,
) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Biology 101")
    source = _ready_source(repo, course.id)
    service = CoursePracticeGenerationService(
        CoursePracticeGenerationRepository(repo),
        provider=_AbstainingProvider(),
        source_text_resolver=_Resolver(),
        account_active=lambda _owner: True,
        identity_lock=lambda: nullcontext(),
        objective_evidence_resolver=_objective_evidence,
    )
    requested = service.create_generated_practice(
        course.id,
        title="Unsupported scope",
        source_ids=[source.id],
        objective_ids=["OBJ-RESP-02"],
        idempotency_key="c3-abstention-operation",
        expected_course_write_epoch=repo.get_course(course.id).write_epoch,
        item_limit=1,
        quality_profile=C3_BIOLOGY_PROFILE,
    )

    terminal = service.run_operation(course.id, requested.operation.id)

    assert (terminal.state, terminal.error_code) == ("failed", "invalid_output")
    practice = CoursePracticeService(CoursePracticeRepository(repo))
    revision = practice.get_revision(
        course.id,
        terminal.practice_set_id,
        terminal.practice_set_revision_id,
    )
    assert revision.state == "draft"
    assert revision.generation_receipt is None
    assert (
        practice.list_questions(
            course.id,
            terminal.practice_set_id,
            terminal.practice_set_revision_id,
        )
        == []
    )


def test_quality_report_review_and_invalidation_are_append_only(tmp_path: Path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Biology 101")
    practice = CoursePracticeService(CoursePracticeRepository(repo))
    practice_set = practice.create_practice_set(
        course.id, title="Quality review", expected_course_write_epoch=course.write_epoch
    )
    revision = practice.create_draft_revision(
        course.id, practice_set.id, expected_course_write_epoch=repo.get_course(course.id).write_epoch
    )
    question = practice.add_question(
        course.id,
        practice_set.id,
        revision.id,
        question_type="short_answer",
        prompt="What does oxygen form?",
        answer_contract={"kind": "exact", "answer": "water"},
        objective_ids=["OBJ-RESP-02"],
        expected_course_write_epoch=repo.get_course(course.id).write_epoch,
    )
    practice.ready_revision(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=repo.get_course(course.id).write_epoch,
    )
    quality = CourseContentQualityRepository(repo)
    report = quality.report_question(
        course.id, practice_set.id, revision.id, question.id, reason="The answer key is flawed"
    )
    assert report["state"] == "reported"
    resolved, evidence_ids = quality.resolve_report(
        course.id,
        report["id"],
        decision="invalidate",
        reviewer_user_id="u_alice",
        note="Reviewed against the approved source packet",
    )
    assert resolved["state"] == "invalidated"
    assert evidence_ids == []
    assert quality.invalidated_question_ids(course.id) == {question.id}
    with pytest.raises(CourseConflictError):
        quality.resolve_report(
            course.id,
            report["id"],
            decision="reject",
            reviewer_user_id="u_alice",
            note="duplicate review",
        )


def test_invalidation_archives_already_derived_review_cards_and_keeps_history(
    tmp_path: Path,
) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Biology 101")
    source = _ready_source(repo, course.id)
    practice = CoursePracticeService(CoursePracticeRepository(repo))
    practice_set = practice.create_practice_set(
        course.id, title="Quality review", expected_course_write_epoch=course.write_epoch
    )
    revision = practice.create_draft_revision(
        course.id, practice_set.id, expected_course_write_epoch=repo.get_course(course.id).write_epoch
    )
    question = practice.add_question(
        course.id,
        practice_set.id,
        revision.id,
        question_type="short_answer",
        prompt="What does oxygen form?",
        answer_contract={"kind": "exact", "answer": "water"},
        objective_ids=["OBJ-RESP-02"],
        expected_course_write_epoch=repo.get_course(course.id).write_epoch,
    )
    practice.ready_revision(
        course.id,
        practice_set.id,
        revision.id,
        expected_course_write_epoch=repo.get_course(course.id).write_epoch,
    )

    flashcards = CourseFlashcardGenerationRepository(repo)
    request = flashcards.create_generated_deck(
        course.id,
        title="Derived Review",
        source_ids=[source.id],
        objective_ids=["OBJ-RESP-02"],
        idempotency_key="derived-review-c3",
        expected_course_write_epoch=repo.get_course(course.id).write_epoch,
        item_limit=1,
        generation_brief={
            "focus": "oxygen",
            "desired_count": 1,
            "card_type_mix": ["recall"],
            "difficulty": "mixed",
            "answer_length": "short",
            "include_hints": False,
        },
        origin={
            "kind": "practice_remediation",
            "practice_attempt_id": "att_" + "a" * 32,
            "practice_set_id": practice_set.id,
            "practice_set_revision_id": revision.id,
            "practice_question_ids": [question.id],
        },
    )
    running, claimed = flashcards.claim_operation(course.id, request.operation.id)
    assert claimed and running.state == "running"
    receipt = FlashcardSourceReceipt(
        source_id=source.id,
        source_revision=source.revision,
        content_sha256=source.content_sha256,
    )
    staged = flashcards.stage_candidates(
        course.id,
        request.operation.id,
        GeneratedFlashcardOutput(
            provider_label="deterministic-local",
            cards=[
                GeneratedFlashcard(
                    prompt="What does oxygen form in aerobic respiration?",
                    answer="water",
                    citations=[FlashcardCitation(**receipt.model_dump())],
                )
            ],
        ),
        account_active=True,
        material_receipts=[receipt],
    )
    published = flashcards.publish_candidates(
        course.id,
        request.operation.id,
        FlashcardCandidatePublication(
            candidate_ids=[staged.candidates[0].candidate_id],
            expected_candidate_revision=staged.candidate_revision,
        ),
        account_active=True,
    )
    assert published.state == "completed"

    quality = CourseContentQualityRepository(repo)
    report = quality.report_question(
        course.id, practice_set.id, revision.id, question.id, reason="The answer key is flawed"
    )
    resolved, _evidence_ids = quality.resolve_report(
        course.id,
        report["id"],
        decision="invalidate",
        reviewer_user_id="u_alice",
        note="Reviewed against the approved source packet",
    )
    assert resolved["state"] == "invalidated"
    assert quality.invalidated_review_operation_ids(course.id, question.id) == [request.operation.id]
    with repo._connect() as conn:
        deck = conn.execute(
            "SELECT state FROM flashcard_decks WHERE id = ?", (request.deck_id,)
        ).fetchone()
        card = conn.execute(
            "SELECT state FROM flashcards WHERE deck_id = ?", (request.deck_id,)
        ).fetchone()
        operation = conn.execute(
            "SELECT state FROM flashcard_generation_operations WHERE id = ?",
            (request.operation.id,),
        ).fetchone()
    assert deck["state"] == "archived"
    assert card["state"] == "archived"
    assert operation["state"] == "completed"


def test_invalidation_removes_graded_learning_effect_and_remediation_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reviewed bad question is excluded without rewriting immutable grade rows."""
    courses = CourseRepository(tmp_path / "courses.db", "u_alice")
    practice = CoursePracticeService(CoursePracticeRepository(courses))
    attempts = CourseAssessmentService(CourseAssessmentRepository(courses))
    learning_root = tmp_path / "learning"
    adapter = CourseMasteryAdapter(LearningStore(root=learning_root))
    grading = CourseGradingService(CourseGradingRepository(courses), adapter)
    course = courses.create_course("Biology 101")
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    adapter.service.init_modules(
        progress,
        [LearningModule(
            id="mod_resp", name="Cellular respiration", order=1,
            knowledge_points=[KnowledgePoint(
                id="OBJ-RESP-02", name="Oxygen role", type=KnowledgeType.MEMORY,
                module_id="mod_resp",
            )],
        )],
    )
    adapter.service.save(progress)
    practice_set = practice.create_practice_set(
        course.id, title="C3 quality quiz", expected_course_write_epoch=course.write_epoch
    )
    revision = practice.create_draft_revision(
        course.id, practice_set.id,
        expected_course_write_epoch=courses.get_course(course.id).write_epoch,
    )
    question = practice.add_question(
        course.id, practice_set.id, revision.id,
        question_type="short_answer",
        prompt="What is oxygen's role at the end of the aerobic electron transport chain?",
        answer_contract={"kind": "exact", "answer": "water"},
        objective_ids=["OBJ-RESP-02"],
        expected_course_write_epoch=courses.get_course(course.id).write_epoch,
    )
    practice.ready_revision(
        course.id, practice_set.id, revision.id,
        expected_course_write_epoch=courses.get_course(course.id).write_epoch,
    )
    view = attempts.start_or_resume_attempt(
        course.id, practice_set.id, revision.id,
        expected_course_write_epoch=courses.get_course(course.id).write_epoch,
        expected_practice_set_write_epoch=2,
    )
    item = view.items[0]
    attempts.autosave_answer(
        course.id, practice_set.id, view.attempt.id, item.id,
        response={"answer": "electron donor"}, expected_answer_revision=1,
        idempotency_token="c3-quality-answer",
        expected_course_write_epoch=courses.get_course(course.id).write_epoch,
        expected_practice_set_write_epoch=2,
    )
    attempts.submit_attempt(
        course.id, practice_set.id, view.attempt.id,
        expected_course_write_epoch=courses.get_course(course.id).write_epoch,
        expected_practice_set_write_epoch=2,
    )
    graded = grading.grade_attempt(
        course.id, practice_set.id, view.attempt.id,
        expected_course_write_epoch=courses.get_course(course.id).write_epoch,
        expected_practice_set_write_epoch=2,
    )
    assert graded.score == {"correct": 0, "total": 1, "fraction": 0.0}
    projected_before = adapter.service.get_or_create(f"lp_{course.id}")
    assert "OBJ-RESP-02" in projected_before.mastery_levels
    assert "OBJ-RESP-02" in projected_before.repetition_states
    assert [item.knowledge_point_id for item in projected_before.review_queue] == [
        "OBJ-RESP-02"
    ]
    with courses._connect() as conn:
        evidence_before = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM quiz_item_grading_evidence ORDER BY id"
            ).fetchall()
        ]
        item_grade_before = dict(
            conn.execute(
                "SELECT grading_json, error_type, graded_at FROM quiz_attempt_items WHERE id = ?",
                (item.id,),
            ).fetchone()
        )
    assert evidence_before and {row["state"] for row in evidence_before} == {"applied"}

    class _Paths:
        def get_workspace_dir(self) -> Path:
            return tmp_path

    monkeypatch.setattr(
        "deeptutor.courses.content_quality_service.get_personal_path_service",
        lambda _owner: _Paths(),
    )
    quality_repository = CourseContentQualityRepository(courses)
    report = quality_repository.report_question(
        course.id, practice_set.id, revision.id, question.id,
        reason="The answer key does not match the approved source.",
    )
    quality_service = CourseContentQualityService(quality_repository)

    def _crash_after_ledger_commit(*_args, **_kwargs):
        raise RuntimeError("injected crash after invalidation ledger commit")

    monkeypatch.setattr(quality_service, "_reconcile_learning", _crash_after_ledger_commit)
    with pytest.raises(RuntimeError, match="injected crash"):
        quality_service.resolve_report(
            course.id,
            report["id"],
            decision="invalidate",
            reviewer_user_id="u_alice",
            note="Reviewed against the approved Biology packet.",
        )

    stale_after_crash = adapter.service.get_or_create(f"lp_{course.id}")
    assert len(stale_after_crash.quiz_attempts) == 1
    assert "OBJ-RESP-02" in stale_after_crash.repetition_states
    assert stale_after_crash.review_queue
    with courses._connect() as conn:
        committed_report = conn.execute(
            "SELECT state FROM practice_question_quality_reports WHERE id = ?",
            (report["id"],),
        ).fetchone()
        committed_ledger = conn.execute(
            "SELECT COUNT(*) FROM practice_question_invalidations WHERE report_id = ?",
            (report["id"],),
        ).fetchone()[0]
    assert committed_report["state"] == "invalidated"
    assert committed_ledger == len(evidence_before) + 1

    recovered = CourseContentQualityService(quality_repository)
    assert recovered.reconcile_pending(course.id) is True
    repaired_version = adapter.service.get_or_create(f"lp_{course.id}").version
    assert recovered.reconcile_pending(course.id) is False
    assert adapter.service.get_or_create(f"lp_{course.id}").version == repaired_version

    resolved, invalidated_evidence_ids = recovered.resolve_report(
        course.id,
        report["id"],
        decision="invalidate",
        reviewer_user_id="u_alice",
        note="Reviewed against the approved Biology packet.",
    )
    assert resolved["id"] == report["id"]
    assert invalidated_evidence_ids

    attempt_view = attempts.get_attempt(course.id, practice_set.id, view.attempt.id)
    effective = recovered.effective_result(
        course.id, practice_set.id, attempt_view
    )
    assert effective["score"] == {"correct": 0, "total": 0, "fraction": 0.0}
    assert effective["invalidated_question_ids"] == [question.id]
    with pytest.raises(CourseConflictError, match="no missed answers"):
        grading.remediation_scope(course.id, view.attempt.id)
    updated_progress = adapter.service.get_or_create(f"lp_{course.id}")
    assert updated_progress.quiz_attempts == []
    assert updated_progress.error_records == []
    assert updated_progress.grading_evidence_receipts == {}
    assert "OBJ-RESP-02" not in updated_progress.mastery_levels
    assert "OBJ-RESP-02" not in updated_progress.repetition_states
    assert updated_progress.review_queue == []
    with courses._connect() as conn:
        evidence_after = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM quiz_item_grading_evidence ORDER BY id"
            ).fetchall()
        ]
        item_grade_after = dict(
            conn.execute(
                "SELECT grading_json, error_type, graded_at FROM quiz_attempt_items WHERE id = ?",
                (item.id,),
            ).fetchone()
        )
        audit_rows = conn.execute(
            """SELECT evidence_id, reason, invalidated_by
               FROM practice_question_invalidations
               WHERE report_id = ? ORDER BY evidence_id""",
            (report["id"],),
        ).fetchall()
    assert evidence_after == evidence_before
    assert item_grade_after == item_grade_before
    assert len(audit_rows) == len(evidence_before) + 1
    assert {row["invalidated_by"] for row in audit_rows} == {"u_alice"}


def test_invalidation_rebuilds_repetition_from_retained_valid_events(
    tmp_path: Path,
) -> None:
    adapter = CourseMasteryAdapter(LearningStore(root=tmp_path / "learning"))
    progress = adapter.service.get_or_create("lp_rebuild")
    adapter.service.init_modules(
        progress,
        [
            LearningModule(
                id="mod_resp",
                name="Cellular respiration",
                order=1,
                knowledge_points=[
                    KnowledgePoint(
                        id="OBJ-RESP-02",
                        name="Oxygen role",
                        type=KnowledgeType.MEMORY,
                        module_id="mod_resp",
                    )
                ],
            )
        ],
    )
    adapter.service.record_course_grading_evidence(
        progress,
        evidence_id="grd_valid",
        payload_sha256="a" * 64,
        question_id="q_valid",
        knowledge_point_id="OBJ-RESP-02",
        module_id="mod_resp",
        is_correct=True,
        user_answer="water",
        knowledge_type=KnowledgeType.MEMORY,
        scheduler=adapter.scheduler,
        persist=False,
    )
    adapter.service.record_course_grading_evidence(
        progress,
        evidence_id="grd_invalid",
        payload_sha256="b" * 64,
        question_id="q_invalid",
        knowledge_point_id="OBJ-RESP-02",
        module_id="mod_resp",
        is_correct=False,
        user_answer="electron donor",
        knowledge_type=KnowledgeType.MEMORY,
        scheduler=adapter.scheduler,
        persist=False,
    )

    changed = adapter.service.reconcile_invalidated_course_evidence(
        progress,
        invalidated_evidence_ids={"grd_invalid"},
        invalidated_question_ids={"q_invalid"},
        affected_knowledge_point_ids={"OBJ-RESP-02"},
        scheduler=adapter.scheduler,
    )

    assert changed is True
    assert [item.question_id for item in progress.quiz_attempts] == ["q_valid"]
    assert progress.error_records == []
    assert progress.grading_evidence_receipts == {"grd_valid": "a" * 64}
    assert progress.mastery_levels["OBJ-RESP-02"] == 0.5
    rebuilt = progress.repetition_states["OBJ-RESP-02"]
    assert (rebuilt.interval_index, rebuilt.consecutive_correct) == (1, 1)
    assert [item.knowledge_point_id for item in progress.review_queue] == [
        "OBJ-RESP-02"
    ]
    assert (
        adapter.service.reconcile_invalidated_course_evidence(
            progress,
            invalidated_evidence_ids={"grd_invalid"},
            invalidated_question_ids={"q_invalid"},
            affected_knowledge_point_ids={"OBJ-RESP-02"},
            scheduler=adapter.scheduler,
        )
        is False
    )
