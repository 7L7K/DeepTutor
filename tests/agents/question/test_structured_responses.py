from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from deeptutor.services.llm.structured_responses import (
    StructuredResponseError,
    generate_structured_response,
)


class _Item(BaseModel):
    name: str


class _Usage:
    def model_dump(self):
        return {"input_tokens": 12, "output_tokens": 7}


class _ParsedResponse:
    _request_id = "resp_123"
    usage = _Usage()

    def __init__(self, parsed):
        self.output_parsed = parsed


class _TextResponse:
    _request_id = "resp_json"
    usage = _Usage()
    output_text = '{"name":"schema item"}'


class _FakeResponses:
    def __init__(self, *, parsed=None, error: Exception | None = None):
        self.parsed = parsed
        self.error = error
        self.parse_calls: list[dict] = []
        self.create_calls: list[dict] = []

    async def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        if self.error:
            raise self.error
        return _ParsedResponse(self.parsed)

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if self.error:
            raise self.error
        return _TextResponse()


class _FakeClient:
    def __init__(self, responses):
        self.responses = responses


def test_responses_adapter_returns_parsed_pydantic_output() -> None:
    responses = _FakeResponses(parsed=_Item(name="quiz item"))

    result = asyncio.run(
        generate_structured_response(
            model="gpt-5-mini",
            instructions="Return an item.",
            input_data="make one",
            api_key="test-key",
            pydantic_model=_Item,
            timeout=9,
            store=False,
            client=_FakeClient(responses),
        )
    )

    assert result.parsed == {"name": "quiz item"}
    assert result.request_id == "resp_123"
    assert result.input_tokens == 12
    assert result.output_tokens == 7
    assert responses.parse_calls[0]["store"] is False
    assert responses.parse_calls[0]["timeout"] == 9


def test_responses_adapter_supports_json_schema_output() -> None:
    responses = _FakeResponses()

    result = asyncio.run(
        generate_structured_response(
            model="gpt-5-mini",
            instructions="Return an item.",
            input_data="make one",
            api_key="test-key",
            json_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            schema_name="item",
            client=_FakeClient(responses),
        )
    )

    assert result.parsed == {"name": "schema item"}
    assert responses.create_calls[0]["text"]["format"]["type"] == "json_schema"
    assert responses.create_calls[0]["text"]["format"]["strict"] is True


def test_responses_adapter_raises_clean_error_on_parse_failure() -> None:
    responses = _FakeResponses(error=TimeoutError("too slow"))

    with pytest.raises(StructuredResponseError, match="too slow"):
        asyncio.run(
            generate_structured_response(
                model="gpt-5-mini",
                instructions="Return an item.",
                input_data="make one",
                api_key="test-key",
                pydantic_model=_Item,
                client=_FakeClient(responses),
            )
        )
