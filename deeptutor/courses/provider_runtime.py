"""Process-wide bounded execution for Course generation providers.

Python cannot safely terminate a provider thread that ignores a deadline.
Keeping one shared permit until that invocation actually exits prevents repeated
timeouts across users or feature types from creating an unbounded number of
live provider threads.
"""

from __future__ import annotations

from collections.abc import Callable
from queue import Empty, Queue
import threading
from typing import TypeVar

_MAX_LIVE_PROVIDER_INVOCATIONS = 4
_provider_permits = threading.BoundedSemaphore(_MAX_LIVE_PROVIDER_INVOCATIONS)

T = TypeVar("T")


def run_provider_with_deadline(
    invoke: Callable[[], T],
    *,
    timeout_seconds: float,
    thread_name: str,
    timeout_error: Callable[[str], Exception],
) -> T:
    """Run one provider call with a deadline and a hard process-wide live cap."""

    if not _provider_permits.acquire(blocking=False):
        raise timeout_error("provider execution capacity is unavailable")

    result: Queue[T | Exception] = Queue(maxsize=1)

    def work() -> None:
        try:
            try:
                result.put(invoke())
            except Exception as exc:  # carried only to the owning worker
                result.put(exc)
        finally:
            _provider_permits.release()

    threading.Thread(target=work, daemon=True, name=thread_name).start()
    try:
        outcome = result.get(timeout=timeout_seconds)
    except Empty as exc:
        # The permit is deliberately retained until the provider really exits.
        raise timeout_error("provider timed out") from exc
    if isinstance(outcome, Exception):
        raise outcome
    return outcome
