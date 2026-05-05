from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel


StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)


class StructuredResponseError(RuntimeError):
    """Raised when a Responses structured-output call cannot return parsed JSON."""


@dataclass
class StructuredResponseResult:
    parsed: dict[str, Any]
    raw_text: str
    latency_ms: float
    model: str
    request_id: str | None = None
    usage: dict[str, Any] | None = None

    @property
    def input_tokens(self) -> int | None:
        usage = self.usage or {}
        value = usage.get("input_tokens")
        return int(value) if isinstance(value, int) else None

    @property
    def output_tokens(self) -> int | None:
        usage = self.usage or {}
        value = usage.get("output_tokens")
        return int(value) if isinstance(value, int) else None


def _model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    if isinstance(value, dict):
        return value
    return {}


def _usage_dump(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    return _model_dump(usage)


def _response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    parts: list[str] = []
    for item in getattr(response, "output", None) or []:
        for content in getattr(item, "content", None) or []:
            text = getattr(content, "text", None)
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


async def generate_structured_response(
    *,
    model: str,
    instructions: str,
    input_data: str | list[dict[str, Any]],
    api_key: str | None,
    base_url: str | None = None,
    default_headers: dict[str, str] | None = None,
    pydantic_model: type[StructuredModelT] | None = None,
    json_schema: dict[str, Any] | None = None,
    schema_name: str = "structured_response",
    timeout: float | None = None,
    store: bool = False,
    max_output_tokens: int | None = None,
    reasoning_effort: str | None = None,
    prompt_cache_key: str | None = None,
    temperature: float | None = None,
    client: Any | None = None,
) -> StructuredResponseResult:
    """Call OpenAI Responses and return parsed structured JSON.

    Use `pydantic_model` when the caller already owns a Pydantic schema. Use
    `json_schema` for plain JSON schema callers. Exactly one schema form is
    required.
    """

    if (pydantic_model is None) == (json_schema is None):
        raise ValueError("Pass exactly one of pydantic_model or json_schema")

    if client is None:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=api_key or "no-key",
            base_url=base_url,
            default_headers=default_headers,
            max_retries=0,
        )

    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": instructions,
        "input": input_data,
        "store": store,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    if max_output_tokens is not None:
        kwargs["max_output_tokens"] = max_output_tokens
    if reasoning_effort:
        kwargs["reasoning"] = {"effort": reasoning_effort}
    if prompt_cache_key:
        kwargs["prompt_cache_key"] = prompt_cache_key
    if temperature is not None:
        kwargs["temperature"] = temperature

    started_at = time.perf_counter()
    try:
        if pydantic_model is not None:
            response = await client.responses.parse(
                text_format=pydantic_model,
                **kwargs,
            )
            parsed_obj = getattr(response, "output_parsed", None)
            parsed = _model_dump(parsed_obj)
            raw_text = json.dumps(parsed, ensure_ascii=False) if parsed else _response_text(response)
        else:
            response = await client.responses.create(
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": json_schema,
                        "strict": True,
                    }
                },
                **kwargs,
            )
            raw_text = _response_text(response)
            parsed = json.loads(raw_text) if raw_text.strip() else {}
    except Exception as exc:
        raise StructuredResponseError(str(exc)) from exc

    latency_ms = (time.perf_counter() - started_at) * 1000.0
    if not isinstance(parsed, dict) or not parsed:
        raise StructuredResponseError("Responses structured output returned no parsed JSON")

    return StructuredResponseResult(
        parsed=parsed,
        raw_text=raw_text,
        latency_ms=latency_ms,
        model=model,
        request_id=getattr(response, "_request_id", None),
        usage=_usage_dump(response),
    )
