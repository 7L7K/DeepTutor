from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.courses.generation_models import (
    GenerationSourceText,
    PracticeGenerationInput,
)
from deeptutor.courses.generation_provider import (
    OpenAIPracticeGenerationProvider,
    PracticeGenerationProviderError,
    _provider_request_diagnostic,
)
from deeptutor.courses.practice_models import PracticeSourceReceipt
from deeptutor.courses.provider_usage import (
    ProviderUsageError,
    ProviderUsageLedger,
    ProviderUsagePolicy,
)
from deeptutor.services.config.text_generation_registry import (
    TextGenerationRegistry,
    default_text_generation_catalog,
)


def _request(
    source_text: str = "ATP stores cellular energy for the cell.",
) -> PracticeGenerationInput:
    receipt = PracticeSourceReceipt(
        source_id="src_" + ("a" * 32),
        source_revision=2,
        content_sha256="b" * 64,
    )
    return PracticeGenerationInput(
        operation_id="opg_" + ("c" * 32),
        owner_user_id="u_alice",
        course_id="crs_" + ("d" * 32),
        practice_set_id="prs_" + ("e" * 32),
        practice_set_revision_id="prv_" + ("f" * 32),
        source_material=[GenerationSourceText(receipt=receipt, text=source_text)],
        objective_ids=["obj_energy"],
        item_limit=1,
        context_char_limit=12_000,
        focus="Understand cellular energy",
        difficulty="mixed",
        timing_mode="practice_timer",
    )


def _payload(
    *,
    question_type: object = "short_answer",
    objective_ids: object = None,
    quote: str = "ATP stores cellular energy for the cell.",
) -> dict:
    return {
        "questions": [
            {
                "question_type": question_type,
                "prompt": "What does ATP store?",
                "answer": "Cellular energy.",
                "explanation": "ATP is an energy carrier.",
                "objective_ids": ["obj_energy"] if objective_ids is None else objective_ids,
                "citations": [
                    {
                        "source_id": "src_" + ("a" * 32),
                        "source_revision": 2,
                        "content_sha256": "b" * 64,
                        "evidence_quote": quote,
                    }
                ],
            }
        ]
    }


class _Responses:
    def __init__(self, payload: dict, captured: dict, *, usage: object | None = None) -> None:
        self.payload = payload
        self.captured = captured
        self.usage = usage or SimpleNamespace(
            input_tokens=120,
            input_tokens_details=SimpleNamespace(cached_tokens=20),
            output_tokens=60,
            output_tokens_details=SimpleNamespace(reasoning_tokens=5),
        )

    def create(self, **kwargs):
        self.captured.update(kwargs)
        return SimpleNamespace(
            id="resp_practice_test",
            model=self.captured.get("_actual_model", "gpt-5-mini-2026-07-01"),
            status="completed",
            output_text=json.dumps(self.payload),
            usage=self.usage,
        )


class _FailingResponses:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def create(self, **kwargs):
        del kwargs
        raise self.error


def _provider(
    tmp_path: Path,
    payload: dict,
    captured: dict,
    *,
    usage: object | None = None,
) -> OpenAIPracticeGenerationProvider:
    ledger = ProviderUsageLedger(tmp_path / "usage" / "provider_usage.db")
    ledger.configure(
        ProviderUsagePolicy(
            enabled=True,
            pricing_version=OpenAIPracticeGenerationProvider.PRICING_VERSION,
        )
    )

    def client_factory(**kwargs):
        captured["client"] = kwargs
        return SimpleNamespace(responses=_Responses(payload, captured, usage=usage))

    return OpenAIPracticeGenerationProvider(
        api_key="sk-test-only",
        model="gpt-5-mini",
        ledger=ledger,
        client_factory=client_factory,
    )


def test_practice_provider_is_strict_grounded_tool_free_and_accounted(
    tmp_path: Path,
) -> None:
    captured: dict = {}
    provider = _provider(tmp_path, _payload(), captured)

    output = provider.generate(_request())

    assert output.provider_label == "openai"
    assert output.actual_model == "gpt-5-mini-2026-07-01"
    assert output.pricing_version == OpenAIPracticeGenerationProvider.PRICING_VERSION
    assert output.reasoning_effort == "minimal"
    assert output.questions[0].question_type == "short_answer"
    assert output.questions[0].citations[0].locator == {
        "evidence_quote": "ATP stores cellular energy for the cell."
    }
    assert captured["model"] == "gpt-5-mini"
    assert captured["store"] is False
    assert captured["tools"] == []
    assert captured["reasoning"] == {"effort": "minimal"}
    assert captured["text"]["format"]["strict"] is True
    assert captured["client"]["max_retries"] == 0
    assert captured["client"]["timeout"] == 25.0
    assert captured["safety_identifier"] == (
        "3e1b0f95738760354f3f2855f28e1f120cdd247e11172712292a01ed9a59d5a2"
    )
    assert "untrusted study data" in captured["instructions"]
    assert "grammatically complete, direct, standalone question" in captured["instructions"]
    assert "Do not invert or splice source clauses" in captured["instructions"]
    assert "sk-test-only" not in captured["input"]
    with provider.ledger._connect() as connection:
        row = connection.execute(
            "SELECT state,settled_input_tokens,settled_output_tokens "
            "FROM provider_usage_reservations"
        ).fetchone()
    assert row is not None
    assert tuple(row) == ("settled", 120, 60)


def test_luna_shaped_practice_response_is_supported_but_not_default(
    tmp_path: Path,
) -> None:
    catalog = {"text_generation": default_text_generation_catalog()}
    section = catalog["text_generation"]
    section["features"]["practice_generation"] = {
        "model": "gpt-5.6-luna",
        "mode": "qualified",
        "reasoning_effort": "low",
    }
    resolved = TextGenerationRegistry.from_catalog(catalog).resolve(
        "practice_generation",
        required_capabilities={"responses", "structured_outputs"},
    )
    captured = {"_actual_model": "gpt-5.6-luna-2026-07-30"}
    ledger = ProviderUsageLedger(tmp_path / "luna-usage" / "provider_usage.db")
    ledger.configure(
        ProviderUsagePolicy(
            enabled=True,
            pricing_version=resolved.model.pricing.version,
        )
    )
    provider = OpenAIPracticeGenerationProvider(
        api_key="sk-test-only",
        model="gpt-5.6-luna",
        ledger=ledger,
        resolved_generation=resolved,
        client_factory=lambda **_kwargs: SimpleNamespace(
            responses=_Responses(_payload(), captured)
        ),
    )

    output = provider.generate(_request())

    assert output.requested_model == "gpt-5.6-luna"
    assert output.actual_model == "gpt-5.6-luna-2026-07-30"
    assert output.pricing_version == "openai-gpt-5.6-luna-2026-08-01"
    assert output.reasoning_effort == "low"
    assert output.cached_input_tokens == 20
    assert output.reasoning_output_tokens == 5
    assert captured["model"] == "gpt-5.6-luna"
    assert captured["reasoning"] == {"effort": "low"}


def test_practice_provider_rejects_unexpected_actual_model(tmp_path: Path) -> None:
    captured = {"_actual_model": "gpt-5.6-luna"}
    provider = _provider(tmp_path, _payload(), captured)

    with pytest.raises(
        PracticeGenerationProviderError,
        match="unexpected model",
    ):
        provider.generate(_request())


def test_c3_provider_requires_and_normalizes_bounded_answer_variants(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["questions"][0]["accepted_answers"] = ["energy"]
    captured: dict = {}
    provider = _provider(tmp_path, payload, captured)
    request = _request().model_copy(update={"quality_profile": "c3-biology-v1"})

    output = provider.generate(request)

    assert output.prompt_version == "course-practice-c3-v1"
    assert output.schema_version == "course-practice-c3-schema-v1"
    assert output.store is False
    assert output.questions[0].answer_contract.accepted_answers == ["energy"]
    question_schema = captured["text"]["format"]["schema"]["properties"]["questions"]["items"]
    assert "accepted_answers" in question_schema["required"]


@pytest.mark.parametrize(
    "payload",
    [
        _payload(question_type="multiple_choice"),
        _payload(objective_ids="obj_energy"),
        _payload(objective_ids=["obj_foreign"]),
        _payload(quote="This quote was never in the Course source."),
    ],
)
def test_practice_provider_rejects_schema_bypass_payloads(tmp_path: Path, payload: dict) -> None:
    provider = _provider(tmp_path, payload, {})

    with pytest.raises(PracticeGenerationProviderError):
        provider.generate(_request())


def test_practice_provider_rejects_duplicate_objectives_after_schema_validation(
    tmp_path: Path,
) -> None:
    provider = _provider(
        tmp_path,
        _payload(objective_ids=["obj_energy", "obj_energy"]),
        {},
    )

    with pytest.raises(PracticeGenerationProviderError, match="provider output is invalid"):
        provider.generate(_request())


def test_practice_provider_rejects_duplicate_question_prompts(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["questions"] = [
        payload["questions"][0],
        {
            **payload["questions"][0],
            "prompt": "  WHAT does ATP store?  ",
        },
    ]
    provider = _provider(tmp_path, payload, {})
    request = _request().model_copy(update={"item_limit": 2})

    with pytest.raises(PracticeGenerationProviderError, match="provider output is invalid"):
        provider.generate(request)


@pytest.mark.parametrize(
    ("status", "output_text", "message"),
    [
        ("incomplete", json.dumps(_payload()), "did not complete"),
        ("completed", "", "provider output is invalid"),
        ("completed", "{malformed", "provider output is invalid"),
    ],
)
def test_practice_provider_fails_closed_on_incomplete_refusal_or_malformed_output(
    tmp_path: Path,
    status: str,
    output_text: str,
    message: str,
) -> None:
    provider = _provider(tmp_path, _payload(), {})

    class _Response:
        def create(self, **_kwargs):
            return SimpleNamespace(
                id="resp_provider_failure_shape",
                model="gpt-5-mini",
                status=status,
                output_text=output_text,
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="refusal", refusal="declined")],
                    )
                ],
                usage=SimpleNamespace(input_tokens=10, output_tokens=0),
            )

    provider._client_factory = lambda **_kwargs: SimpleNamespace(responses=_Response())

    with pytest.raises(PracticeGenerationProviderError, match=message):
        provider.generate(_request())


def test_practice_provider_rejects_missing_evidence_before_cost_or_network(
    tmp_path: Path,
) -> None:
    captured: dict = {}
    provider = _provider(tmp_path, _payload(), captured)

    with pytest.raises(PracticeGenerationProviderError, match="source evidence is unavailable"):
        provider.generate(_request("x"))

    assert captured == {}
    with provider.ledger._connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM provider_usage_reservations").fetchone()[0]
            == 0
        )


def test_practice_provider_marks_invalid_usage_uncertain(tmp_path: Path) -> None:
    provider = _provider(
        tmp_path,
        _payload(),
        {},
        usage=SimpleNamespace(input_tokens=10, output_tokens=-1),
    )

    with pytest.raises(
        PracticeGenerationProviderError,
        match="usage metadata is unavailable",
    ):
        provider.generate(_request())

    with provider.ledger._connect() as connection:
        row = connection.execute("SELECT state FROM provider_usage_reservations").fetchone()
    assert row is not None and row["state"] == "uncertain"


def test_practice_provider_marks_settlement_failure_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, _payload(), {})
    monkeypatch.setattr(
        provider.ledger,
        "settle",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ProviderUsageError("synthetic settlement failure")
        ),
    )

    with pytest.raises(
        PracticeGenerationProviderError,
        match="usage settlement failed",
    ):
        provider.generate(_request())

    with provider.ledger._connect() as connection:
        row = connection.execute("SELECT state FROM provider_usage_reservations").fetchone()
    assert row is not None and row["state"] == "uncertain"


def test_practice_provider_logs_only_bounded_request_diagnostics(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class SyntheticRateLimitError(RuntimeError):
        status_code = 429
        request_id = "req_safe_123"

    secret_message = "credential-never-log private learner source text"
    provider = _provider(tmp_path, _payload(), {})
    provider._client_factory = lambda **kwargs: SimpleNamespace(
        responses=_FailingResponses(SyntheticRateLimitError(secret_message))
    )

    with caplog.at_level(logging.WARNING, logger="deeptutor.courses.generation_provider"):
        with pytest.raises(PracticeGenerationProviderError, match="provider request failed"):
            provider.generate(_request())

    rendered = "\n".join(caplog.messages)
    assert "category=rate_limit" in rendered
    assert "status_code=429" in rendered
    assert "request_id=req_safe_123" in rendered
    assert secret_message not in rendered
    with provider.ledger._connect() as connection:
        row = connection.execute("SELECT state FROM provider_usage_reservations").fetchone()
    assert row is not None and row["state"] == "uncertain"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            type("SyntheticInvalidRequest", (RuntimeError,), {"status_code": 400})(
                "private"
            ),
            ("invalid_request", 400, None),
        ),
        (
            type("SyntheticAuthentication", (RuntimeError,), {"status_code": 401})(
                "private"
            ),
            ("authentication", 401, None),
        ),
        (
            type("SyntheticRateLimit", (RuntimeError,), {"status_code": 429})(
                "private"
            ),
            ("rate_limit", 429, None),
        ),
        (TimeoutError("private"), ("timeout", None, None)),
    ],
)
def test_practice_provider_classifies_required_http_and_timeout_failures(
    error: Exception,
    expected: tuple[str, int | None, str | None],
) -> None:
    assert _provider_request_diagnostic(error) == expected


def test_practice_provider_schema_uses_supported_array_constraints(
    tmp_path: Path,
) -> None:
    captured: dict = {}
    provider = _provider(tmp_path, _payload(), captured)
    provider.generate(_request())

    schema = captured["text"]["format"]["schema"]
    objective_schema = schema["properties"]["questions"]["items"]["properties"]["objective_ids"]
    assert objective_schema["maxItems"] == 1
    assert objective_schema["items"]["enum"] == ["obj_energy"]
    assert "uniqueItems" not in json.dumps(schema, sort_keys=True)

    empty_objectives = _request().model_copy(update={"objective_ids": []})
    evidence = provider._evidence_by_receipt(empty_objectives)
    empty_schema = provider._schema(empty_objectives, evidence)
    empty_objective_schema = empty_schema["properties"]["questions"]["items"]["properties"][
        "objective_ids"
    ]
    assert empty_objective_schema["maxItems"] == 0
    assert "enum" not in empty_objective_schema["items"]
    assert "uniqueItems" not in json.dumps(empty_schema, sort_keys=True)
