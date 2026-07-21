from __future__ import annotations

import multiprocessing

import pytest

from deeptutor.courses.deployment import SingleProcessCourseLock, _configured_worker_count


def _try_lock(path: str, result) -> None:
    lock = SingleProcessCourseLock(path)
    try:
        lock.acquire({})
    except RuntimeError:
        result.put("blocked")
    else:
        result.put("acquired")
        lock.release()


def test_worker_configuration_requires_exactly_one() -> None:
    assert _configured_worker_count({}) == 1
    assert _configured_worker_count({"WEB_CONCURRENCY": "1"}) == 1
    with pytest.raises(RuntimeError, match="worker count is 2"):
        lock = SingleProcessCourseLock("unused")
        lock.acquire({"UVICORN_WORKERS": "2"})


def test_second_process_cannot_acquire_course_runtime_lock(tmp_path) -> None:
    lock_path = tmp_path / "course.lock"
    lock = SingleProcessCourseLock(lock_path)
    lock.acquire({})
    context = multiprocessing.get_context("spawn")
    result = context.Queue()
    process = context.Process(target=_try_lock, args=(str(lock_path), result))
    process.start()
    process.join(timeout=10)
    try:
        assert process.exitcode == 0
        assert result.get(timeout=2) == "blocked"
    finally:
        lock.release()
