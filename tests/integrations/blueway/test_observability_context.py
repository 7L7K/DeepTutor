"""Concurrency and cleanup proof for the shared structured log context."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import threading

from deeptutor.logging.context import bind_log_context, current_log_context
from deeptutor.logging.formatters import ContextFilter


class _RecordHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self._records_lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        with self._records_lock:
            self.records.append(record)


def test_fifty_concurrent_contexts_do_not_cross_contaminate_or_leak() -> None:
    logger = logging.getLogger("deeptutor.integrations.blueway.context-isolation")
    handler = _RecordHandler()
    handler.addFilter(ContextFilter())
    previous_level = logger.level
    previous_propagate = logger.propagate
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)

    def worker(index: int) -> bool:
        request_ref = f"request-{index}"
        trace_id = f"bwr_{index:032x}"
        try:
            with bind_log_context(request_id=request_ref, blueway_event={"trace_id": trace_id}):
                logger.info("before-nested")
                with bind_log_context(task_id=f"task-{index}"):
                    logger.info("nested")
                    assert current_log_context()["request_id"] == request_ref
                    assert current_log_context()["blueway_event"]["trace_id"] == trace_id
                raise RuntimeError("synthetic context failure")
        except RuntimeError:
            assert current_log_context() == {}
            with bind_log_context(request_id=request_ref, blueway_event={"trace_id": trace_id}):
                logger.info("after-exception")
        return current_log_context() == {}

    try:
        with ThreadPoolExecutor(max_workers=50) as pool:
            assert all(pool.map(worker, range(50)))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate

    assert len(handler.records) == 150
    for record in handler.records:
        context = record.log_context
        request_ref = context["request_id"]
        index = int(request_ref.removeprefix("request-"))
        assert context["blueway_event"]["trace_id"] == f"bwr_{index:032x}"
        if record.getMessage() == "nested":
            assert context["task_id"] == f"task-{index}"
