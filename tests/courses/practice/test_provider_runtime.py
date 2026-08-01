"""Hard bounds for provider calls that ignore their deadline."""

from __future__ import annotations

import threading
import time

import pytest

from deeptutor.courses.provider_runtime import run_provider_with_deadline


class ProviderDeadline(RuntimeError):
    pass


def test_timed_out_provider_threads_remain_process_wide_bounded() -> None:
    release = threading.Event()
    thread_name = "phase4-bounded-provider-test"

    def blocked() -> str:
        release.wait(timeout=2)
        return "done"

    try:
        for _ in range(4):
            with pytest.raises(ProviderDeadline, match="timed out"):
                run_provider_with_deadline(
                    blocked,
                    timeout_seconds=0.01,
                    thread_name=thread_name,
                    timeout_error=ProviderDeadline,
                )
        assert sum(thread.name == thread_name for thread in threading.enumerate()) == 4
        with pytest.raises(ProviderDeadline, match="capacity"):
            run_provider_with_deadline(
                blocked,
                timeout_seconds=0.01,
                thread_name=thread_name,
                timeout_error=ProviderDeadline,
            )
        assert sum(thread.name == thread_name for thread in threading.enumerate()) == 4
    finally:
        release.set()
        deadline = time.monotonic() + 1
        while (
            any(thread.name == thread_name for thread in threading.enumerate())
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

    assert not any(thread.name == thread_name for thread in threading.enumerate())
