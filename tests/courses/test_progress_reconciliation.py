from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.api.routers import courses as courses_router
from deeptutor.api.utils.task_log_stream import KnowledgeTaskStreamManager


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "terminal_event"),
    [("ready", "event: complete"), ("failed", "event: failed")],
)
async def test_durable_source_state_closes_fresh_progress_stream(
    monkeypatch, state: str, terminal_event: str
) -> None:
    source = SimpleNamespace(operation_id="op_restart", state=state)
    service = SimpleNamespace(
        reconcile_source_for_progress=lambda _course_id, _source_id: source
    )
    manager = KnowledgeTaskStreamManager()
    monkeypatch.setattr(courses_router, "_service", lambda: service)
    monkeypatch.setattr(
        "deeptutor.api.utils.task_log_stream.get_task_stream_manager", lambda: manager
    )

    response = await courses_router.stream_course_source_progress("crs_one", "src_one")
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    assert len(chunks) == 1
    assert terminal_event in chunks[0]
