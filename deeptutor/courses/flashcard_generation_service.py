"""Restart-safe runner for bounded grounded Flashcard deck generation."""

from __future__ import annotations

import threading
from typing import Callable, ContextManager

from deeptutor.multi_user.identity import get_user_by_id, identity_write_lock
from deeptutor.multi_user.models import LOCAL_ADMIN_ID

from .flashcard_generation_models import (
    FlashcardCandidatePublication,
    FlashcardGenerationBriefReceipt,
    FlashcardGenerationInput,
    FlashcardGenerationOperation,
    FlashcardGenerationRequest,
)
from .flashcard_generation_provider import (
    DeterministicIndexFlashcardSourceTextResolver,
    FlashcardGenerationProvider,
    FlashcardGenerationProviderError,
    FlashcardGenerationProviderQuotaExceeded,
    FlashcardGenerationProviderTimedOut,
    FlashcardGenerationProviderUnavailable,
    FlashcardSourceTextResolver,
    default_flashcard_generation_provider,
    flashcard_generation_provider_available,
)
from .flashcard_generation_repository import (
    CourseFlashcardGenerationRepository,
    FlashcardGenerationInsufficientCandidates,
)
from .provider_runtime import run_provider_with_deadline
from .repository import CourseConflictError, CourseNotFoundError

_live_lock = threading.RLock()
_live: dict[tuple[str, str], set[str]] = {}


def register_live_flashcard_generation(
    owner_user_id: str, course_id: str, operation_id: str
) -> bool:
    with _live_lock:
        operations = _live.setdefault((owner_user_id, course_id), set())
        if operation_id in operations:
            return False
        operations.add(operation_id)
        return True


def unregister_live_flashcard_generation(
    owner_user_id: str, course_id: str, operation_id: str
) -> None:
    with _live_lock:
        items = _live.get((owner_user_id, course_id))
        if items:
            items.discard(operation_id)
            if not items:
                _live.pop((owner_user_id, course_id), None)


def _live_ids(owner: str, course: str) -> set[str]:
    with _live_lock:
        return set(_live.get((owner, course), set()))


def _account_active(user_id: str) -> bool:
    if user_id == LOCAL_ADMIN_ID:
        return True
    record = get_user_by_id(user_id)
    return record is not None and not bool(record[1].get("disabled", False))


class CourseFlashcardGenerationService:
    def __init__(
        self,
        repository: CourseFlashcardGenerationRepository,
        provider: FlashcardGenerationProvider | None = None,
        source_text_resolver: FlashcardSourceTextResolver | None = None,
        *,
        account_active: Callable[[str], bool] = _account_active,
        identity_lock: Callable[[], ContextManager[object]] = identity_write_lock,
        provider_timeout_seconds: float = 30.0,
    ) -> None:
        if not 0.01 <= provider_timeout_seconds <= 120:
            raise ValueError("provider_timeout_seconds must be between 0.01 and 120 seconds")
        self.repository, self.provider = (
            repository,
            provider or default_flashcard_generation_provider(),
        )
        self.source_text_resolver = (
            source_text_resolver or DeterministicIndexFlashcardSourceTextResolver()
        )
        self._account_active, self._identity_lock, self._timeout = (
            account_active,
            identity_lock,
            provider_timeout_seconds,
        )

    def create_generated_deck(self, course_id: str, **kwargs: object) -> FlashcardGenerationRequest:
        if not self._account_active(self.repository.owner_user_id):
            raise CourseConflictError("Generation account authority is no longer active")
        return self.repository.create_generated_deck(
            course_id, provider_available=self.provider_available(), **kwargs
        )

    def provider_available(self) -> bool:
        """Expose admission truth without allocating a generated draft."""

        return flashcard_generation_provider_available(self.provider)

    def request_successor(
        self, course_id: str, deck_id: str, **kwargs: object
    ) -> FlashcardGenerationRequest:
        # A successor is always a new deck: no previous ready deck, cards, or reviews are rewritten.
        return self.create_generated_deck(course_id, supersedes_deck_id=deck_id, **kwargs)

    def prepare_brief(
        self, course_id: str, **kwargs: object
    ) -> FlashcardGenerationBriefReceipt:
        if not self._account_active(self.repository.owner_user_id):
            raise CourseConflictError("Generation account authority is no longer active")
        return self.repository.prepare_brief(
            course_id,
            provider_available=self.provider_available(),
            **kwargs,
        )

    def _generate(self, request: FlashcardGenerationInput):
        return run_provider_with_deadline(
            lambda: self.provider.generate(request),
            timeout_seconds=self._timeout,
            thread_name="flashcard-generation-provider",
            timeout_error=FlashcardGenerationProviderTimedOut,
        )

    def run_operation(self, course_id: str, operation_id: str) -> FlashcardGenerationOperation:
        try:
            operation, claimed = self.repository.claim_operation(course_id, operation_id)
            if not claimed:
                return operation
            if not self._account_active(self.repository.owner_user_id):
                return self.repository.fail_operation(course_id, operation_id, "authority_changed")
            material = self.source_text_resolver.resolve(
                owner_user_id=operation.owner_user_id,
                course_id=course_id,
                receipts=operation.source_snapshot,
                context_char_limit=operation.context_char_limit,
            )
            # This is the final zero-call authority fence.  Source resolution
            # is intentionally before it so archive/revocation/replacement
            # races during retrieval stop before provider invocation.
            operation = self.repository.preflight_provider_call(
                course_id,
                operation_id,
                account_active=self._account_active(self.repository.owner_user_id),
            )
            output = self._generate(
                FlashcardGenerationInput(
                    operation_id=operation.id,
                    owner_user_id=operation.owner_user_id,
                    course_id=course_id,
                    deck_id=operation.deck_id,
                    source_material=material,
                    objective_ids=operation.objective_ids,
                    generation_brief=operation.generation_brief,
                    item_limit=operation.item_limit,
                    context_char_limit=operation.context_char_limit,
                )
            )
            with self._identity_lock():
                return self.repository.stage_candidates(
                    course_id,
                    operation_id,
                    output,
                    account_active=self._account_active(self.repository.owner_user_id),
                    material_receipts=[item.receipt for item in material],
                )
        except FlashcardGenerationProviderUnavailable:
            return self.repository.fail_operation(course_id, operation_id, "provider_unavailable")
        except FlashcardGenerationProviderTimedOut:
            return self.repository.fail_operation(course_id, operation_id, "provider_timed_out")
        except FlashcardGenerationProviderQuotaExceeded:
            return self.repository.fail_operation(course_id, operation_id, "quota_exceeded")
        except FlashcardGenerationProviderError:
            return self.repository.fail_operation(course_id, operation_id, "provider_failed")
        except FlashcardGenerationInsufficientCandidates:
            return self.repository.fail_operation(
                course_id, operation_id, "insufficient_valid_cards"
            )
        except ValueError:
            return self.repository.fail_operation(course_id, operation_id, "invalid_output")
        except CourseNotFoundError:
            return self.repository.fail_operation(course_id, operation_id, "source_changed")
        except CourseConflictError as exc:
            return self.repository.fail_operation(
                course_id,
                operation_id,
                "source_changed" if "source" in str(exc).lower() else "authority_changed",
            )
        except Exception:
            return self.repository.fail_operation(course_id, operation_id, "provider_failed")
        finally:
            try:
                self.repository.finalize_cancellation(course_id, operation_id)
            except (CourseNotFoundError, CourseConflictError):
                pass
            unregister_live_flashcard_generation(
                self.repository.owner_user_id, course_id, operation_id
            )

    def get_operation(self, course_id: str, operation_id: str) -> FlashcardGenerationOperation:
        self.repository.expire_review_candidates(course_id)
        self.repository.reconcile_orphaned_operations(
            course_id, live_operation_ids=_live_ids(self.repository.owner_user_id, course_id)
        )
        return self.repository.get_operation(course_id, operation_id)

    def list_operations(self, course_id: str) -> list[FlashcardGenerationOperation]:
        self.repository.expire_review_candidates(course_id)
        self.repository.reconcile_orphaned_operations(
            course_id, live_operation_ids=_live_ids(self.repository.owner_user_id, course_id)
        )
        return self.repository.list_operations(course_id)

    def publish_candidates(
        self,
        course_id: str,
        operation_id: str,
        publication: FlashcardCandidatePublication,
    ) -> FlashcardGenerationOperation:
        self.repository.expire_review_candidates(course_id)
        with self._identity_lock():
            return self.repository.publish_candidates(
                course_id,
                operation_id,
                publication,
                account_active=self._account_active(self.repository.owner_user_id),
            )

    def cancel_operation(
        self, course_id: str, operation_id: str
    ) -> FlashcardGenerationOperation:
        return self.repository.cancel_operation(course_id, operation_id)


def build_flashcard_generation_service(course_service: object) -> CourseFlashcardGenerationService:
    return CourseFlashcardGenerationService(
        CourseFlashcardGenerationRepository(getattr(course_service, "repository"))
    )
