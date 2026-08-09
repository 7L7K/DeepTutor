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

from .generation_models import (
    GeneratedPracticeOutput,
    GeneratedPracticeQuestion,
    PracticeGenerationInput,
)
from .practice_models import PracticeCitation

C3_BIOLOGY_PROFILE = "c3-biology-v1"
_OPAQUE_ID = re.compile(r"\b(?:src|crs|prc|prv|qst|opg|pln)_[A-Za-z0-9]+\b")
_TOKEN = re.compile(r"[a-z0-9]{3,}")


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


def _supported_by_quote(answer: str, explanation: str, quote: str) -> bool:
    quote_tokens = _tokens(quote)
    answer_tokens = {item for item in _tokens(answer) if item not in {"the", "and", "from", "with", "that", "this"}}
    explanation_tokens = _tokens(explanation)
    if not answer_tokens or not answer_tokens.intersection(quote_tokens):
        return False
    return bool(explanation_tokens.intersection(quote_tokens))


def _locator_with_offsets(citation: PracticeCitation, text: str) -> PracticeCitation:
    quote = citation.locator.get("evidence_quote")
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError("C3 citations require an evidence_quote locator")
    start = text.find(quote)
    if start < 0:
        raise ValueError("C3 citation evidence_quote is not reachable")
    return citation.model_copy(
        update={
            "locator": {
                **citation.locator,
                "start_char": start,
                "end_char": start + len(quote),
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
    if output.provider_label != "openai":
        findings.append(QualityFinding("PROVIDER_NOT_GOLDEN", None, "C3 requires a configured non-deterministic provider"))
    if not output.request_id or not output.actual_model:
        findings.append(QualityFinding("PROVIDER_RECEIPT_INCOMPLETE", None, "request and actual model IDs are required"))
    if output.input_tokens is None or output.output_tokens is None or output.latency_ms is None:
        findings.append(QualityFinding("PROVIDER_RUNTIME_RECEIPT_INCOMPLETE", None, "usage and latency are required"))
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
        cited = False
        for citation in question.citations:
            key = (citation.source_id, citation.source_revision, citation.content_sha256)
            source_text = material_by_receipt.get(key)
            if source_text is None:
                findings.append(QualityFinding("CITATION_OUTSIDE_SNAPSHOT", index, "citation is not in the resolved Course material"))
                continue
            try:
                enriched_citation = _locator_with_offsets(citation, source_text)
            except ValueError as exc:
                findings.append(QualityFinding("CITATION_UNREACHABLE", index, str(exc)))
                continue
            quote = str(enriched_citation.locator["evidence_quote"])
            if not _supported_by_quote(question.answer_contract.answer, question.explanation, quote):
                findings.append(QualityFinding("ANSWER_UNSUPPORTED", index, "answer/explanation is not supported by the cited quote"))
            new_citations.append(enriched_citation)
            cited = True
        if not cited:
            findings.append(QualityFinding("CITATION_MISSING", index, "at least one reachable citation is required"))
        enriched.append(question.model_copy(update={"citations": new_citations}))

    if findings:
        raise ContentQualityError(findings)
    return output.model_copy(update={"questions": enriched})


__all__ = ["C3_BIOLOGY_PROFILE", "ContentQualityError", "QualityFinding", "validate_c3_output"]
