"""Fail-closed C3 validation for source-backed Course learning content.

The provider may propose wording and mappings, but this module owns the small
deterministic checks required before a generated Practice revision can become
learner-visible. It intentionally does not pretend to be a semantic human
reviewer: the fixture review artifact remains a separate gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import string
import unicodedata

from .generation_models import (
    GeneratedPracticeOutput,
    GeneratedPracticeQuestion,
    PracticeGenerationInput,
    PracticeObjectiveSupportEvidence,
    build_practice_generation_request_contract,
)
from .practice_models import PracticeCitation

C3_BIOLOGY_PROFILE = "c3-biology-v1"
_OPAQUE_ID = re.compile(r"\b(?:src|crs|prc|prv|qst|opg|pln)_[A-Za-z0-9]+\b")
_TOKEN = re.compile(r"[a-z0-9]{3,}")
_C3_LOCATOR_VERSION = "exact-char-v1"


@dataclass(frozen=True)
class QualityFinding:
    code: str
    question_index: int | None
    detail: str


class ContentQualityError(ValueError):
    """A generated result failed a deterministic C3 publication check."""

    def __init__(self, findings: list[QualityFinding]) -> None:
        self.findings = tuple(findings)
        summary = "; ".join(
            f"{item.code}{'' if item.question_index is None else f'[{item.question_index}]'}"
            for item in findings
        )
        super().__init__(f"C3 content quality rejected generated output: {summary}")


def _normalized(value: str) -> str:
    return " ".join(value.casefold().translate(str.maketrans("", "", string.punctuation)).split())


def _tokens(value: str) -> set[str]:
    return set(_TOKEN.findall(value.casefold()))


def _answer_supported_by_quote(answer: str, quote: str) -> bool:
    quote_tokens = _tokens(quote)
    normalized_answer = _normalized(answer)
    if normalized_answer in {"yes", "no"}:
        return True
    answer_tokens = {
        item
        for item in _tokens(answer)
        if item not in {"the", "and", "from", "with", "that", "this"}
    }
    return not answer_tokens or bool(answer_tokens.intersection(quote_tokens))


def _explanation_supported_by_quote(explanation: str, quote: str) -> bool:
    return bool(_tokens(explanation).intersection(_tokens(quote)))


def _resolved_locator(
    citation: PracticeCitation,
    text: str,
    evidence: PracticeObjectiveSupportEvidence,
) -> PracticeCitation:
    evidence_id = citation.locator.get("evidence_id")
    quote = citation.locator.get("evidence_quote")
    if evidence_id != evidence.evidence_id or quote != evidence.quote:
        raise ValueError("C3 citation does not resolve to its server evidence ID")
    if text[evidence.start_char : evidence.end_char] != evidence.quote:
        raise ValueError("C3 citation evidence span is not reachable")
    return citation.model_copy(
        update={
            "locator": {
                "evidence_id": evidence.evidence_id,
                "evidence_quote": evidence.quote,
                "offsets_version": _C3_LOCATOR_VERSION,
                "start_char": evidence.start_char,
                "end_char": evidence.end_char,
            }
        }
    )


def validate_c3_output(
    request: PracticeGenerationInput,
    output: GeneratedPracticeOutput,
    material: list[object],
) -> GeneratedPracticeOutput:
    """Validate and enrich one C3 result before the repository publication fence."""

    if request.quality_profile != C3_BIOLOGY_PROFILE:
        return output

    findings: list[QualityFinding] = []
    expected_contract = build_practice_generation_request_contract(request)
    if output.outcome != "generated":
        findings.append(
            QualityFinding(
                "ABSTAINED",
                None,
                "an abstention cannot cross the publication fence",
            )
        )
    if output.request_contract is None:
        findings.append(
            QualityFinding(
                "REQUEST_CONTRACT_MISSING",
                None,
                "C3 requires the exact deterministic request contract",
            )
        )
    elif output.request_contract != expected_contract:
        findings.append(
            QualityFinding(
                "REQUEST_CONTRACT_MISMATCH",
                None,
                "provider output does not echo the exact requested scope",
            )
        )
    if output.provider_label != "openai":
        findings.append(QualityFinding("PROVIDER_NOT_GOLDEN", None, "C3 requires a configured non-deterministic provider"))
    if not output.request_id or not output.actual_model:
        findings.append(QualityFinding("PROVIDER_RECEIPT_INCOMPLETE", None, "request and actual model IDs are required"))
    if output.input_tokens is None or output.output_tokens is None or output.latency_ms is None:
        findings.append(QualityFinding("PROVIDER_RUNTIME_RECEIPT_INCOMPLETE", None, "usage and latency are required"))
    if output.store is not False:
        findings.append(QualityFinding("PROVIDER_STORE_POLICY", None, "C3 provider output must record store=false"))
    if not output.prompt_version or not output.schema_version:
        findings.append(QualityFinding("PROVIDER_SCHEMA_RECEIPT_INCOMPLETE", None, "prompt and schema versions are required"))
    if not request.objective_ids:
        findings.append(QualityFinding("OBJECTIVES_EMPTY", None, "C3 requires approved objectives"))
    if len(output.questions) != request.item_limit:
        findings.append(QualityFinding("QUESTION_COUNT", None, "C3 must publish exactly the requested count"))

    material_by_receipt = {
        (
            item.receipt.source_id,
            item.receipt.source_revision,
            item.receipt.content_sha256,
        ): item.text
        for item in material
    }
    allowed = set(request.objective_ids)
    requested = set(request.effective_requested_objective_ids())
    required_claim_ids = request.effective_required_claim_ids_by_objective()
    if any(not required_claim_ids.get(objective_id) for objective_id in requested):
        findings.append(
            QualityFinding(
                "REQUIRED_CLAIM_CONTRACT_MISSING",
                None,
                "every requested C3 objective requires a nonempty claim contract",
            )
        )
    objective_support_evidence = {
        objective_id: {
            evidence.evidence_id: (binding.receipt, evidence)
            for binding in request.effective_objective_evidence_bindings()
            if binding.objective_id == objective_id
            for evidence in binding.support_evidence
        }
        for objective_id in requested
    }
    objective_context_evidence_ids = {
        objective_id: {
            evidence.evidence_id
            for binding in request.effective_objective_evidence_bindings()
            if binding.objective_id == objective_id
            for evidence in binding.context_evidence
        }
        for objective_id in requested
    }
    required_accepted_answers = (
        request.effective_required_accepted_answers_by_objective()
    )
    prompts: list[str] = []
    enriched: list[GeneratedPracticeQuestion] = []
    for index, question in enumerate(output.questions, start=1):
        if _OPAQUE_ID.search(question.prompt) or _OPAQUE_ID.search(question.explanation):
            findings.append(QualityFinding("PRIVACY_ID_LEAK", index, "learner-visible text contains an opaque system ID"))
        if question.question_type != "short_answer" or question.answer_contract.kind != "exact":
            findings.append(QualityFinding("UNSUPPORTED_GRADE_TYPE", index, "C3 supports exact short-answer grading only"))
        if not question.objective_ids:
            findings.append(QualityFinding("OBJECTIVE_EMPTY", index, "every question needs at least one objective"))
        if len(set(question.objective_ids)) != len(question.objective_ids) or any(item not in allowed for item in question.objective_ids):
            findings.append(QualityFinding("OBJECTIVE_INVALID", index, "objective mapping is not a unique approved ID"))
        if any(item not in requested for item in question.objective_ids):
            findings.append(
                QualityFinding(
                    "REQUEST_OBJECTIVE_MISMATCH",
                    index,
                    "objective mapping substitutes a topic outside the requested scope",
                )
            )
        normalized_prompt = _normalized(question.prompt)
        if not normalized_prompt or normalized_prompt in prompts:
            findings.append(QualityFinding("DUPLICATE_PROMPT", index, "question wording is duplicated"))
        for prior in prompts:
            if SequenceMatcher(None, normalized_prompt, prior).ratio() >= 0.92:
                findings.append(QualityFinding("NEAR_DUPLICATE_PROMPT", index, "question wording is too similar to another item"))
        prompts.append(normalized_prompt)
        if question.answer_contract.answer.strip() and _normalized(question.answer_contract.answer) in normalized_prompt and len(_normalized(question.answer_contract.answer)) > 12:
            findings.append(QualityFinding("ANSWER_LEAK", index, "the complete answer is present in the prompt"))
        if not question.explanation.strip():
            findings.append(QualityFinding("EXPLANATION_EMPTY", index, "a supported explanation is required"))
        new_citations: list[PracticeCitation] = []
        cited_support: list[tuple[str, PracticeObjectiveSupportEvidence]] = []
        cited = False
        eligible_for_question = {
            evidence_id: (objective_id, evidence)
            for objective_id in question.objective_ids
            for evidence_id, evidence in objective_support_evidence.get(
                objective_id, {}
            ).items()
        }
        context_only_for_question = {
            evidence_id
            for objective_id in question.objective_ids
            for evidence_id in objective_context_evidence_ids.get(
                objective_id, set()
            )
        }
        for citation in question.citations:
            key = (citation.source_id, citation.source_revision, citation.content_sha256)
            source_text = material_by_receipt.get(key)
            if source_text is None:
                findings.append(QualityFinding("CITATION_OUTSIDE_SNAPSHOT", index, "citation is not in the resolved Course material"))
                continue
            evidence_id = citation.locator.get("evidence_id")
            if evidence_id in context_only_for_question:
                findings.append(
                    QualityFinding(
                        "CITATION_CONTEXT_ONLY",
                        index,
                        "background context is not citation eligible",
                    )
                )
                continue
            eligible = eligible_for_question.get(evidence_id)
            if eligible is None:
                findings.append(
                    QualityFinding(
                        "CITATION_OUTSIDE_OBJECTIVE_EVIDENCE",
                        index,
                        "evidence ID is not support bound to the question objective",
                    )
                )
                continue
            evidence_objective_id, (expected_receipt, support_evidence) = eligible
            if (
                citation.source_id != expected_receipt.source_id
                or citation.source_revision != expected_receipt.source_revision
                or citation.content_sha256 != expected_receipt.content_sha256
            ):
                findings.append(
                    QualityFinding(
                        "CITATION_OUTSIDE_OBJECTIVE_EVIDENCE",
                        index,
                        "evidence ID does not resolve to the cited source receipt",
                    )
                )
                continue
            try:
                enriched_citation = _resolved_locator(
                    citation, source_text, support_evidence
                )
            except ValueError as exc:
                findings.append(QualityFinding("CITATION_UNREACHABLE", index, str(exc)))
                continue
            new_citations.append(enriched_citation)
            cited_support.append((evidence_objective_id, support_evidence))
            cited = True
        if not cited:
            findings.append(QualityFinding("CITATION_MISSING", index, "at least one reachable citation is required"))
        else:
            covered_claim_ids = {
                (objective_id, claim_id)
                for objective_id, item in cited_support
                for claim_id in item.claim_ids
            }
            required_for_question = {
                (objective_id, claim_id)
                for objective_id in question.objective_ids
                for claim_id in required_claim_ids.get(objective_id, [])
            }
            if not required_for_question.issubset(covered_claim_ids):
                findings.append(
                    QualityFinding(
                        "REQUIRED_CLAIM_UNCOVERED",
                        index,
                        "cited support evidence does not cover every required claim",
                    )
                )
            for objective_id in question.objective_ids:
                covered_roles = {
                    role
                    for evidence_objective_id, item in cited_support
                    if evidence_objective_id == objective_id
                    for role in item.supports
                }
                if not {"answer", "explanation"}.issubset(covered_roles):
                    findings.append(
                        QualityFinding(
                            "EVIDENCE_ROLE_UNCOVERED",
                            index,
                            "each objective's cited support must cover answer and explanation",
                        )
                    )
            # A question may cite multiple adjacent source fragments.  The
            # answer and explanation must be supported by the reachable set as
            # a whole, not redundantly by every individual fragment.
            combined_quote = "\n".join(
                str(citation.locator["evidence_quote"])
                for citation in new_citations
                if isinstance(citation.locator.get("evidence_quote"), str)
            )
            answer_values = [question.answer_contract.answer, *question.answer_contract.accepted_answers]
            if not all(
                _answer_supported_by_quote(answer, combined_quote)
                for answer in answer_values
            ):
                findings.append(
                    QualityFinding(
                        "ANSWER_UNSUPPORTED",
                        index,
                        "answer is not supported by the cited source set",
                    )
                )
            if not _explanation_supported_by_quote(
                question.explanation, combined_quote
            ):
                findings.append(
                    QualityFinding(
                        "EXPLANATION_UNSUPPORTED",
                        index,
                        "explanation is not supported by the cited source set",
                    )
                )
            required_answer_values = {
                unicodedata.normalize("NFC", answer).strip().casefold()
                for objective_id in question.objective_ids
                for answer in required_accepted_answers.get(objective_id, [])
            }
            provided_answer_values = {
                unicodedata.normalize("NFC", answer).strip().casefold()
                for answer in [
                    question.answer_contract.answer,
                    *question.answer_contract.accepted_answers,
                ]
            }
            if not required_answer_values.issubset(provided_answer_values):
                findings.append(
                    QualityFinding(
                        "ACCEPTED_ANSWER_VARIANTS_INCOMPLETE",
                        index,
                        "the exact-grade contract omits required bounded variants",
                    )
                )
        enriched.append(question.model_copy(update={"citations": new_citations}))

    emitted_objectives = {
        objective_id
        for question in output.questions
        for objective_id in question.objective_ids
    }
    if emitted_objectives != requested:
        findings.append(
            QualityFinding(
                "REQUEST_OBJECTIVE_COVERAGE_INCOMPLETE",
                None,
                "generated questions must collectively cover every requested objective",
            )
        )

    if findings:
        raise ContentQualityError(findings)
    return output.model_copy(update={"questions": enriched})


__all__ = [
    "C3_BIOLOGY_PROFILE",
    "ContentQualityError",
    "QualityFinding",
    "validate_c3_output",
]
