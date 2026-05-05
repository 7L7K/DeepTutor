from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.services.llm.executors import sdk_complete, sdk_stream


class _FakeCompletions:
    def __init__(self, capture: dict[str, object], stream_chunks=None):
        self.capture = capture
        self.stream_chunks = stream_chunks or []

    async def create(self, **payload):
        self.capture.update(payload)
        if payload.get("stream"):
            async def _gen():
                for chunk in self.stream_chunks:
                    yield chunk
            return _gen()
        return SimpleNamespace(
            choices=[SimpleNamespace(message={"content": "OK"})]
        )


class _FakeChat:
    def __init__(self, capture: dict[str, object], stream_chunks=None):
        self.completions = _FakeCompletions(capture, stream_chunks=stream_chunks)


class _FakeAsyncOpenAI:
    def __init__(self, *, capture: dict[str, object], stream_chunks=None, **kwargs):
        self.chat = _FakeChat(capture, stream_chunks=stream_chunks)


@pytest.mark.asyncio
async def test_sdk_complete_forces_temperature_for_gpt5(monkeypatch) -> None:
    capture: dict[str, object] = {}

    monkeypatch.setattr(
        "deeptutor.services.llm.executors.AsyncOpenAI",
        lambda **kwargs: _FakeAsyncOpenAI(capture=capture, **kwargs),
    )

    result = await sdk_complete(
        prompt="hello",
        system_prompt="system",
        provider_name="openai",
        model="gpt-5-mini",
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        temperature=0.2,
    )

    assert result == "OK"
    assert capture["temperature"] == 1.0


@pytest.mark.asyncio
async def test_sdk_stream_forces_temperature_for_gpt5(monkeypatch) -> None:
    capture: dict[str, object] = {}
    stream_chunks = [
        SimpleNamespace(
            choices=[SimpleNamespace(delta={"content": "OK"})]
        )
    ]

    monkeypatch.setattr(
        "deeptutor.services.llm.executors.AsyncOpenAI",
        lambda **kwargs: _FakeAsyncOpenAI(capture=capture, stream_chunks=stream_chunks, **kwargs),
    )

    chunks = []
    async for chunk in sdk_stream(
        prompt="hello",
        system_prompt="system",
        provider_name="openai",
        model="gpt-5-mini",
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        temperature=0.5,
    ):
        chunks.append(chunk)

    assert chunks == ["OK"]
    assert capture["temperature"] == 1.0
