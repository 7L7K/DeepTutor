"""Background-safe service seam for grounded Course Practice generation."""

from __future__ import annotations

from queue import Empty, Queue
import threading
from typing import Callable, ContextManager

from deeptutor.multi_user.identity import get_user_by_id, identity_write_lock
from deeptutor.multi_user.models import LOCAL_ADMIN_ID

from .generation_models import (
    PracticeGenerationInput,
    PracticeGenerationOperation,
    PracticeGenerationRequest,
)
from .generation_provider import (
    CourseSourceTextResolver,
    DeterministicIndexCourseSourceTextResolver,
    PracticeGenerationProvider,
    PracticeGenerationProviderError,
    PracticeGenerationProviderTimedOut,
    PracticeGenerationProviderUnavailable,
    default_practice_generation_provider,
)
from .generation_repository import CoursePracticeGenerationRepository
from .repository import CourseConflictError, CourseNotFoundError

_live_generation_lock = threading.RLock()
_live_generation_operations: dict[tuple[str, str], set[str]] = {}
_DEFAULT_PROVIDER_TIMEOUT_SECONDS = 30.0
_MAX_PROVIDER_TIMEOUT_SECONDS = 120.0


def register_live_practice_generation(
    owner_user_id: str, course_id: str, operation_id: str
) -> bool:
    """Mark a just-scheduled local operation live until its worker returns.

    This is deliberately process-local.  A process restart loses this marker,
    which is exactly the signal used by the next owned read to terminalize an
    orphaned durable queued/running row.
    """
    with _live_generation_lock:
        operations = _live_generation_operations.setdefault(
            (owner_user_id, course_id), set()
        )
        if operation_id in operations:
            return False
        operations.add(operation_id)
        return True


def unregister_live_practice_generation(
    owner_user_id: str, course_id: str, operation_id: str
) -> None:
    with _live_generation_lock:
        key = (owner_user_id, course_id)
        operations = _live_generation_operations.get(key)
        if operations is None:
            return
        operations.discard(operation_id)
        if not operations:
            _live_generation_operations.pop(key, None)


def _live_operation_ids(owner_user_id: str, course_id: str) -> set[str]:
    with _live_generation_lock:
        return set(_live_generation_operations.get((owner_user_id, course_id), set()))


def _default_account_active(user_id: str) -> bool:
    if user_id == LOCAL_ADMIN_ID:
        return True
    record = get_user_by_id(user_id)
    return record is not None and not bool(record[1].get("disabled", False))


class CoursePracticeGenerationService:
    """Run a provider only between fenced SQLite state transitions.

    The service uses identity -> Course database lock order at the final commit.
    Tests can inject a deliberately simple account authority without changing
    the durable repository contract.
    """

    def __init__(
        self,
        repository: CoursePracticeGenerationRepository,
        provider: PracticeGenerationProvider | None = None,
        source_text_resolver: CourseSourceTextResolver | None = None,
        *,
        account_active: Callable[[str], bool] = _default_account_active,
        identity_lock: Callable[[], ContextManager[object]] = identity_write_lock,
        provider_timeout_seconds: float = _DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    ) -> None:
        self.repository = repository
        self.provider = provider or default_practice_generation_provider()
        self.source_text_resolver = source_text_resolver or DeterministicIndexCourseSourceTextResolver()
        self._account_active = account_active
        self._identity_lock = identity_lock
        if not 0.01 <= provider_timeout_seconds <= _MAX_PROVIDER_TIMEOUT_SECONDS:
            raise ValueError("provider_timeout_seconds must be between 0.01 and 120 seconds")
        self._provider_timeout_seconds = provider_timeout_seconds

    def _generate_with_deadline(self, request: PracticeGenerationInput):
        result: Queue[object] = Queue(maxsize=1)

        def invoke() -> None:
            try:
                result.put(self.provider.generate(request))
            except Exception as exc:  # carried back only to the owning worker
                result.put(exc)

        thread = threading.Thread(target=invoke, daemon=True, name="practice-generation-provider")
        thread.start()
        try:
            outcome = result.get(timeout=self._provider_timeout_seconds)
        except Empty as exc:
            raise PracticeGenerationProviderTimedOut("provider timed out") from exc
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def create_generated_practice(self, course_id: str, **kwargs: object) -> PracticeGenerationRequest:
        if not self._account_active(self.repository.owner_user_id):
            raise CourseConflictError("Generation account authority is no longer active")
        return self.repository.create_generated_practice(course_id, **kwargs)

    def get_operation(self, course_id: str, operation_id: str) -> PracticeGenerationOperation:
        self._reconcile_for_owned_read(course_id)
        return self.repository.get_operation(course_id, operation_id)

    def list_operations(self, course_id: str, **kwargs: object) -> list[PracticeGenerationOperation]:
        self._reconcile_for_owned_read(course_id)
        return self.repository.list_operations(course_id, **kwargs)

    def request_generation(self, course_id: str, practice_set_id: str, **kwargs: object) -> PracticeGenerationRequest:
        if not self._account_active(self.repository.owner_user_id):
            raise CourseConflictError("Generation account authority is no longer active")
        return self.repository.request_generation(course_id, practice_set_id, **kwargs)

    def run_operation(self, course_id: str, operation_id: str) -> PracticeGenerationOperation:
        """Synchronously run one operation; API adapters may schedule this in background."""
        try:
            operation, claimed = self.repository.claim_operation(course_id, operation_id)
            if not claimed:
                return operation
            if not self._account_active(self.repository.owner_user_id):
                return self.repository.fail_operation(course_id, operation_id, "authority_changed")
            material = self.source_text_resolver.resolve(
                owner_user_id=operation.owner_user_id,
                course_id=operation.course_id,
                receipts=operation.source_snapshot,
                context_char_limit=operation.context_char_limit,
            )
            output = self._generate_with_deadline(PracticeGenerationInput(
                operation_id=operation.id,
                course_id=operation.course_id,
                practice_set_id=operation.practice_set_id,
                practice_set_revision_id=operation.practice_set_revision_id,
                source_material=material,
                objective_ids=operation.objective_ids,
                item_limit=operation.item_limit,
                context_char_limit=operation.context_char_limit,
            ))
            with self._identity_lock():
                return self.repository.complete_operation(
                    course_id, operation_id, output,
                    account_active=self._account_active(self.repository.owner_user_id),
                    material_receipts=[item.receipt for item in material],
                )
        except PracticeGenerationProviderUnavailable:
            return self.repository.fail_operation(course_id, operation_id, "provider_unavailable")
        except PracticeGenerationProviderTimedOut:
            return self.repository.fail_operation(course_id, operation_id, "provider_timed_out")
        except PracticeGenerationProviderError:
            return self.repository.fail_operation(course_id, operation_id, "provider_failed")
        except ValueError:
            return self.repository.fail_operation(course_id, operation_id, "invalid_output")
        except CourseNotFoundError:
            # The only repository lookup after a successful claim is a fenced
            # Course/set/revision/source revalidation.  Missing then means the
            # worker lost authority, never that a provider result is usable.
            return self.repository.fail_operation(course_id, operation_id, "source_changed")
        except CourseConflictError as exc:
            message = str(exc).lower()
            code = "source_changed" if "source" in message else "authority_changed"
            return self.repository.fail_operation(course_id, operation_id, code)
        except Exception:
            return self.repository.fail_operation(course_id, operation_id, "provider_failed")
        finally:
            unregister_live_practice_generation(
                self.repository.owner_user_id, course_id, operation_id
            )

    def _reconcile_for_owned_read(self, course_id: str) -> None:
        self.repository.reconcile_orphaned_operations(
            course_id,
            live_operation_ids=_live_operation_ids(self.repository.owner_user_id, course_id),
        )

    def reconcile_orphaned_operations(self, course_id: str, *, live_operation_ids: set[str] | None = None) -> int:
        return self.repository.reconcile_orphaned_operations(
            course_id, live_operation_ids=live_operation_ids or set()
        )


def build_practice_generation_service(course_service: object) -> CoursePracticeGenerationService:
    """Build the safe local-only service from an authenticated CourseService."""
    repository = getattr(course_service, "repository")
    return CoursePracticeGenerationService(CoursePracticeGenerationRepository(repository))
