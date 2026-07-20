from __future__ import annotations

from deeptutor.services.llm.provider_core.openai_responses.converters import (
    adapt_chat_kwargs_to_responses,
)


def test_responses_adapter_translates_json_object_response_format() -> None:
    adapted = adapt_chat_kwargs_to_responses(
        {
            "response_format": {"type": "json_object"},
            "max_completion_tokens": 250,
            "temperature": None,
        }
    )

    assert adapted["max_output_tokens"] == 250
    assert adapted["text"] == {"format": {"type": "json_object"}}
    assert "response_format" not in adapted
    assert "max_completion_tokens" not in adapted
