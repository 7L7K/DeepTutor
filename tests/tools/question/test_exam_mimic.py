from __future__ import annotations

import asyncio
from types import SimpleNamespace


def test_mimic_wrapper_preserves_positional_callback_compatibility(monkeypatch) -> None:
    from deeptutor.tools.question import exam_mimic

    captured: dict[str, object] = {}

    class FakeCoordinator:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def set_ws_callback(self, callback) -> None:
            captured["callback"] = callback

        async def generate_from_exam(self, **_kwargs):
            return {"success": True, "results": [], "template_count": 0}

    async def callback(_event_type: str, _payload: dict) -> None:
        return None

    monkeypatch.setattr(exam_mimic, "AgentCoordinator", FakeCoordinator)
    monkeypatch.setattr(
        exam_mimic,
        "get_llm_config",
        lambda: SimpleNamespace(api_key="key", base_url="https://example.test", api_version=None),
    )

    result = asyncio.run(
        exam_mimic.mimic_exam_questions("paper.pdf", None, "kb", "out", 3, callback)
    )

    assert result["success"] is True
    assert captured["allowed_builtin_tools"] is None
    assert "callback" in captured
