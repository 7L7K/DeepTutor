"""Bounded, local-only provider seam for grounded Practice generation.

There is deliberately no configured remote-model implementation in Phase 4.
The default adapter fails closed unless the already-existing deterministic test
provider flag is enabled.  A future provider must implement this narrow typed
contract and receive only server-resolved source material.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from deeptutor.courses.deterministic_provider import enabled as deterministic_enabled
from deeptutor.courses.service import source_kb_name
from deeptutor.multi_user.paths import get_personal_path_service

from .generation_models import (
    GeneratedPracticeOutput,
    GeneratedPracticeQuestion,
    GenerationSourceText,
    PracticeGenerationInput,
)
from .practice_models import PracticeCitation, PracticeSourceReceipt

_MAX_SOURCE_EXCERPT_CHARS = 12_000
_MAX_INDEX_BYTES = 256_000


class PracticeGenerationProviderError(RuntimeError):
    """Safe classification for unavailable or failed provider work."""


class PracticeGenerationProviderUnavailable(PracticeGenerationProviderError):
    """The only safe default until a separately approved provider exists."""


class PracticeGenerationProviderTimedOut(PracticeGenerationProviderError):
    """A bounded local wait expired; the late result has no commit authority."""


class PracticeGenerationProvider(Protocol):
    def generate(self, request: PracticeGenerationInput) -> GeneratedPracticeOutput:
        """Generate strict structured questions only; never return free-form text."""


class CourseSourceTextResolver(Protocol):
    def resolve(
        self,
        *,
        owner_user_id: str,
        course_id: str,
        receipts: list[PracticeSourceReceipt],
        context_char_limit: int,
    ) -> list[GenerationSourceText]:
        """Return bounded text for the exact frozen receipts or fail closed."""


class UnavailablePracticeGenerationProvider:
    """Production-safe default until a separately approved provider is added."""

    def generate(self, request: PracticeGenerationInput) -> GeneratedPracticeOutput:
        del request
        raise PracticeGenerationProviderUnavailable("provider unavailable")


class DeterministicPracticeGenerationProvider:
    """A test-only provider which treats source text as inert data.

    It derives an answer from a text hash; it never parses, executes, or follows
    text that appears in Course material.  The flag keeps it out of ordinary
    runtime use even though it makes deterministic local proof convenient.
    """

    def generate(self, request: PracticeGenerationInput) -> GeneratedPracticeOutput:
        if not deterministic_enabled():
            raise PracticeGenerationProviderUnavailable("provider unavailable")
        material = request.source_material[0]
        text_digest = hashlib.sha256(material.text.encode("utf-8")).hexdigest()
        answer = f"fact-{text_digest[:16]}"
        return GeneratedPracticeOutput(
            provider_label="deterministic-local",
            questions=[
                GeneratedPracticeQuestion(
                    question_type="short_answer",
                    prompt=f"What bounded fact is represented by source {material.receipt.source_id}?",
                    answer_contract={"kind": "exact", "answer": answer},
                    explanation="This deterministic local question is grounded in the cited Course source.",
                    objective_ids=request.objective_ids,
                    citations=[PracticeCitation(**material.receipt.model_dump())],
                )
            ],
        )


class DeterministicIndexCourseSourceTextResolver:
    """Read only deterministic Course shards below the authenticated owner's root."""

    @staticmethod
    def _read_chunks(index_path: Path, *, expected_content_sha256: str) -> list[str]:
        try:
            raw = index_path.read_bytes()
        except OSError as exc:
            raise PracticeGenerationProviderError("source text is unavailable") from exc
        if len(raw) > _MAX_INDEX_BYTES:
            raise PracticeGenerationProviderError("source text is unavailable")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise PracticeGenerationProviderError("source text is unavailable") from exc
        if not isinstance(payload, dict) or payload.get("course_source_content_sha256") != expected_content_sha256:
            raise PracticeGenerationProviderError("source provenance is unavailable")
        chunks = payload.get("chunks")
        if not isinstance(chunks, list):
            raise PracticeGenerationProviderError("source text is unavailable")
        text = [str(item.get("text") or "") for item in chunks if isinstance(item, dict)]
        return [item for item in text if item.strip()]

    def resolve(
        self,
        *,
        owner_user_id: str,
        course_id: str,
        receipts: list[PracticeSourceReceipt],
        context_char_limit: int,
    ) -> list[GenerationSourceText]:
        root = get_personal_path_service(owner_user_id).get_knowledge_bases_root().resolve()
        remaining = min(context_char_limit, 48_000)
        material: list[GenerationSourceText] = []
        for receipt in receipts:
            if remaining <= 0:
                break
            index_path = (
                root / source_kb_name(course_id, receipt.source_id) / "deterministic-index.json"
            ).resolve()
            try:
                index_path.relative_to(root)
            except ValueError as exc:
                raise PracticeGenerationProviderError("source text is unavailable") from exc
            excerpt = "\n".join(self._read_chunks(
                index_path, expected_content_sha256=receipt.content_sha256
            ))[: min(remaining, _MAX_SOURCE_EXCERPT_CHARS)]
            if not excerpt.strip():
                continue
            material.append(GenerationSourceText(receipt=receipt, text=excerpt))
            remaining -= len(excerpt)
        if not material:
            raise PracticeGenerationProviderError("source text is unavailable")
        return material


def default_practice_generation_provider() -> PracticeGenerationProvider:
    """Return the local test provider only when explicitly enabled."""

    return (
        DeterministicPracticeGenerationProvider()
        if deterministic_enabled()
        else UnavailablePracticeGenerationProvider()
    )


def practice_generation_provider_available(
    provider: PracticeGenerationProvider | None = None,
) -> bool:
    """Whether the selected provider can be admitted for a new operation."""

    return not isinstance(
        provider if provider is not None else default_practice_generation_provider(),
        UnavailablePracticeGenerationProvider,
    )
