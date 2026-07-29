"""Fail-closed provider seam for grounded Flashcards."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from deeptutor.courses.deterministic_provider import enabled as deterministic_enabled
from deeptutor.courses.service import source_kb_name
from deeptutor.multi_user.paths import get_personal_path_service

from .flashcard_generation_models import (
    FlashcardCitation,
    FlashcardGenerationInput,
    FlashcardGenerationSourceText,
    FlashcardSourceReceipt,
    GeneratedFlashcard,
    GeneratedFlashcardOutput,
)


class FlashcardGenerationProviderError(RuntimeError):
    pass


class FlashcardGenerationProviderUnavailable(FlashcardGenerationProviderError):
    pass


class FlashcardGenerationProviderTimedOut(FlashcardGenerationProviderError):
    pass


class FlashcardGenerationProvider(Protocol):
    def generate(self, request: FlashcardGenerationInput) -> GeneratedFlashcardOutput: ...


class FlashcardSourceTextResolver(Protocol):
    def resolve(
        self,
        *,
        owner_user_id: str,
        course_id: str,
        receipts: list[FlashcardSourceReceipt],
        context_char_limit: int,
    ) -> list[FlashcardGenerationSourceText]: ...


class UnavailableFlashcardGenerationProvider:
    def generate(self, request: FlashcardGenerationInput) -> GeneratedFlashcardOutput:
        del request
        raise FlashcardGenerationProviderUnavailable("provider unavailable")


class DeterministicFlashcardGenerationProvider:
    """Test-only generator: source text is hashed inert data, never instructions."""

    def generate(self, request: FlashcardGenerationInput) -> GeneratedFlashcardOutput:
        if not deterministic_enabled():
            raise FlashcardGenerationProviderUnavailable("provider unavailable")
        material = request.source_material[0]
        digest = hashlib.sha256(material.text.encode("utf-8")).hexdigest()
        return GeneratedFlashcardOutput(
            provider_label="deterministic-local",
            cards=[
                GeneratedFlashcard(
                    prompt=f"What bounded fact is represented by source {material.receipt.source_id}?",
                    answer=f"fact-{digest[:16]}",
                    objective_ids=request.objective_ids,
                    citations=[FlashcardCitation(**material.receipt.model_dump())],
                )
            ],
        )


class DeterministicIndexFlashcardSourceTextResolver:
    def resolve(
        self,
        *,
        owner_user_id: str,
        course_id: str,
        receipts: list[FlashcardSourceReceipt],
        context_char_limit: int,
    ) -> list[FlashcardGenerationSourceText]:
        root = get_personal_path_service(owner_user_id).get_knowledge_bases_root().resolve()
        result: list[FlashcardGenerationSourceText] = []
        remaining = min(context_char_limit, 48_000)
        for receipt in receipts:
            path = (
                root / source_kb_name(course_id, receipt.source_id) / "deterministic-index.json"
            ).resolve()
            try:
                path.relative_to(root)
                raw = path.read_bytes()
                if len(raw) > 256_000:
                    raise ValueError
                payload = json.loads(raw.decode("utf-8"))
                if payload.get("course_source_content_sha256") != receipt.content_sha256:
                    raise ValueError
                text = "\n".join(
                    str(item.get("text") or "")
                    for item in payload.get("chunks", [])
                    if isinstance(item, dict)
                ).strip()
            except (
                OSError,
                ValueError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                AttributeError,
            ) as exc:
                raise FlashcardGenerationProviderError("source text is unavailable") from exc
            if not text:
                raise FlashcardGenerationProviderError("source text is unavailable")
            excerpt = text[: min(12_000, remaining)]
            if not excerpt:
                break
            result.append(FlashcardGenerationSourceText(receipt=receipt, text=excerpt))
            remaining -= len(excerpt)
        if not result:
            raise FlashcardGenerationProviderError("source text is unavailable")
        return result


def default_flashcard_generation_provider() -> FlashcardGenerationProvider:
    return (
        DeterministicFlashcardGenerationProvider()
        if deterministic_enabled()
        else UnavailableFlashcardGenerationProvider()
    )


def flashcard_generation_provider_available(
    provider: FlashcardGenerationProvider | None = None,
) -> bool:
    """Whether the selected provider can be admitted for a new operation."""

    return not isinstance(
        provider if provider is not None else default_flashcard_generation_provider(),
        UnavailableFlashcardGenerationProvider,
    )
