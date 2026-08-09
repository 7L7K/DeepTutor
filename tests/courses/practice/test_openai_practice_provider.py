from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.courses.generation_models import (
    GenerationSourceText,
    PracticeGenerationInput,
    PracticeObjectiveContextEvidence,
    PracticeObjectiveEvidenceBinding,
    PracticeObjectiveSupportEvidence,
    build_practice_generation_request_contract,
)
from deeptutor.courses.generation_provider import (
    OpenAIPracticeGenerationProvider,
    PracticeGenerationProviderError,
    PracticeGenerationProviderUnavailable,
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


def _as_c3(
    request: PracticeGenerationInput,
    *,
    requested_objective_ids: list[str] | None = None,
    bindings: list[PracticeObjectiveEvidenceBinding] | None = None,
    required_claim_ids_by_objective: dict[str, list[str]] | None = None,
    required_accepted_answers_by_objective: dict[str, list[str]] | None = None,
) -> PracticeGenerationInput:
    objective_id = request.objective_ids[0]
    resolved_bindings = bindings
    if resolved_bindings is None:
        resolved_bindings = [
            _binding(
                objective_id,
                request.source_material[0].receipt,
                request.source_material[0].text,
                support_quotes=[request.source_material[0].text],
            )
        ]
    resolved_required_claims = required_claim_ids_by_objective
    if resolved_required_claims is None:
        requested = (
            [objective_id]
            if requested_objective_ids is None
            else requested_objective_ids
        )
        resolved_required_claims = {
            requested_objective_id: sorted(
                {
                    claim_id
                    for binding in resolved_bindings
                    if binding.objective_id == requested_objective_id
                    for evidence in binding.support_evidence
                    for claim_id in evidence.claim_ids
                }
            )
            for requested_objective_id in requested
        }
    return request.model_copy(
        update={
            "quality_profile": "c3-biology-v1",
            "requested_objective_ids": (
                [objective_id]
                if requested_objective_ids is None
                else requested_objective_ids
            ),
            "objective_evidence_bindings": resolved_bindings,
            "required_claim_ids_by_objective": resolved_required_claims,
            "required_accepted_answers_by_objective": (
                required_accepted_answers_by_objective or {}
            ),
        }
    )


def _binding(
    objective_id: str,
    receipt: PracticeSourceReceipt,
    source_text: str,
    *,
    support_quotes: list[str],
    context_quotes: list[str] | None = None,
    claim_ids_by_quote: dict[str, list[str]] | None = None,
    supports_by_quote: dict[str, list[str]] | None = None,
) -> PracticeObjectiveEvidenceBinding:
    def evidence_id(kind: str, quote: str) -> str:
        return "ev_" + hashlib.sha256(
            f"{objective_id}:{kind}:{quote}".encode("utf-8")
        ).hexdigest()[:24]

    contexts = []
    for quote in context_quotes or []:
        start = source_text.find(quote)
        assert start >= 0
        contexts.append(
            PracticeObjectiveContextEvidence(
                evidence_id=evidence_id("context", quote),
                quote=quote,
                start_char=start,
                end_char=start + len(quote),
            )
        )
    support = []
    for quote in support_quotes:
        start = source_text.find(quote)
        assert start >= 0
        digest = hashlib.sha256(quote.encode("utf-8")).hexdigest()[:16]
        support.append(
            PracticeObjectiveSupportEvidence(
                evidence_id=evidence_id("support", quote),
                quote=quote,
                start_char=start,
                end_char=start + len(quote),
                supports=(supports_by_quote or {}).get(
                    quote, ["answer", "explanation"]
                ),
                claim_ids=(claim_ids_by_quote or {}).get(
                    quote, [f"claim_{digest}"]
                ),
            )
        )
    return PracticeObjectiveEvidenceBinding(
        objective_id=objective_id,
        receipt=receipt,
        context_evidence=contexts,
        support_evidence=support,
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


def _luna_provider(
    tmp_path: Path,
    payload: dict,
    captured: dict,
) -> OpenAIPracticeGenerationProvider:
    catalog = {"text_generation": default_text_generation_catalog()}
    section = catalog["text_generation"]
    section["features"]["practice_generation"] = {
        "model": "gpt-5.6-luna",
        "mode": "qualified",
        "reasoning_effort": "medium",
    }
    resolved = TextGenerationRegistry.from_catalog(catalog).resolve(
        "practice_generation",
        required_capabilities={"responses", "structured_outputs"},
    )
    captured["_actual_model"] = "gpt-5.6-luna-2026-07-30"
    ledger = ProviderUsageLedger(tmp_path / "luna-usage" / "provider_usage.db")
    ledger.configure(
        ProviderUsagePolicy(
            enabled=True,
            pricing_version=resolved.model.pricing.version,
        )
    )

    def client_factory(**kwargs):
        captured["client"] = kwargs
        return SimpleNamespace(responses=_Responses(payload, captured))

    return OpenAIPracticeGenerationProvider(
        api_key="sk-test-only",
        model="gpt-5.6-luna",
        ledger=ledger,
        resolved_generation=resolved,
        client_factory=client_factory,
    )


def _c3_payload(request: PracticeGenerationInput, payload: dict) -> dict:
    questions = []
    evidence_by_quote = {
        evidence.quote: evidence.evidence_id
        for binding in request.effective_objective_evidence_bindings()
        for evidence in binding.support_evidence
    }
    for question in payload["questions"]:
        citations = question.get("citations", [])
        questions.append(
            {
                key: value
                for key, value in question.items()
                if key != "citations"
            }
            | {
                "citation_evidence_ids": [
                    evidence_by_quote.get(
                        str(citation.get("evidence_quote")), "ev_unbound"
                    )
                    for citation in citations
                ]
            }
        )
    return {
        "request_contract": build_practice_generation_request_contract(
            request
        ).model_dump(mode="json"),
        "outcome": "generated",
        "abstain_reason": None,
        "questions": questions,
    }


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
    request = _as_c3(_request())
    question_payload = _payload()
    question_payload["questions"][0]["accepted_answers"] = ["energy"]
    captured: dict = {}
    provider = _luna_provider(
        tmp_path, _c3_payload(request, question_payload), captured
    )

    output = provider.generate(request)

    assert output.prompt_version == "course-practice-c3-v5"
    assert output.schema_version == "course-practice-c3-schema-v6"
    assert output.store is False
    assert output.outcome == "generated"
    assert output.request_contract == build_practice_generation_request_contract(
        request
    )
    assert output.questions[0].answer_contract.accepted_answers == ["energy"]
    question_schema = captured["text"]["format"]["schema"]["properties"]["questions"]["items"]
    assert "accepted_answers" in question_schema["required"]


def test_c3_evidence_preserves_exact_lines_and_excludes_headings() -> None:
    text = (
        "# Lecture 6\n\n"
        "**[00:13:05] Instructor:** Oxygen is the terminal electron acceptor\n"
        "at the end of the aerobic electron transport chain. Oxygen accepts\n"
        "electrons and protons to form water.\n\n"
        "## Review heading\n"
    )

    quotes = OpenAIPracticeGenerationProvider._c3_evidence_quotes(text)

    assert quotes == [
        "**[00:13:05] Instructor:** Oxygen is the terminal electron acceptor",
        "at the end of the aerobic electron transport chain. Oxygen accepts",
        "electrons and protons to form water.",
    ]
    assert all(quote in text and "\n" not in quote for quote in quotes)


def test_c3_reference_fixture_binds_obj_resp_02_to_only_oxygen_evidence() -> None:
    reference_root = Path(__file__).resolve().parents[3] / "evals/reference_course"
    fixture = json.loads(
        (reference_root / "objective_evidence_roles_v2.json").read_text(encoding="utf-8")
    )
    bindings = [
        PracticeObjectiveEvidenceBinding.model_validate(binding)
        for binding in fixture["bindings"]
    ]
    oxygen = [
        binding for binding in bindings if binding.objective_id == "OBJ-RESP-02"
    ]
    transcript = (
        reference_root / "sources/lecture_06_transcript.md"
    ).read_text(encoding="utf-8")

    assert len(oxygen) == 1
    support_quotes = [item.quote for item in oxygen[0].support_evidence]
    assert all(quote in transcript for quote in support_quotes)
    assert any("terminal electron acceptor" in quote for quote in support_quotes)
    assert all("four teaching stages" not in quote for quote in support_quotes)
    assert all("[00:00:00]" not in quote for quote in support_quotes)


def test_c3_provider_abstains_before_cost_or_network_for_unapproved_request(
    tmp_path: Path,
) -> None:
    captured: dict = {}
    request = _as_c3(
        _request(), requested_objective_ids=["OBJ-PHOTO-01"]
    )
    provider = _luna_provider(tmp_path, {}, captured)

    output = provider.generate(request)

    assert output.outcome == "abstain"
    assert output.abstain_reason == "unsupported_by_allowed_sources"
    assert output.questions == []
    assert output.provider_label == "policy-local"
    assert output.response_status == "not_called"
    assert "client" not in captured
    with provider.ledger._connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM provider_usage_reservations"
            ).fetchone()[0]
            == 0
        )


def test_c3_provider_rejects_mini_policy_before_cost_or_network(
    tmp_path: Path,
) -> None:
    captured: dict = {}
    provider = _provider(tmp_path, _payload(), captured)
    request = _as_c3(_request())

    with pytest.raises(
        PracticeGenerationProviderUnavailable,
        match="C3 publication model is unavailable",
    ):
        provider.generate(request)

    assert "client" not in captured
    with provider.ledger._connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM provider_usage_reservations"
            ).fetchone()[0]
            == 0
        )


def test_c3_provider_rejects_neighboring_objective_substitution(
    tmp_path: Path,
) -> None:
    base = _request().model_copy(
        update={"objective_ids": ["obj_energy", "obj_neighbor"]}
    )
    request = _as_c3(base)
    question_payload = _payload(objective_ids=["obj_neighbor"])
    question_payload["questions"][0]["accepted_answers"] = []
    provider = _luna_provider(
        tmp_path,
        _c3_payload(request, question_payload),
        {},
    )

    with pytest.raises(
        PracticeGenerationProviderError, match="provider output is invalid"
    ):
        provider.generate(request)


def test_c3_provider_exposes_only_objective_bound_evidence(
    tmp_path: Path,
) -> None:
    oxygen_line = "Oxygen is the terminal electron acceptor and forms water."
    opening_line = "The pathway has four teaching stages."
    base = _request(f"{opening_line}\n{oxygen_line}")
    request = _as_c3(
        base,
        bindings=[
            _binding(
                "obj_energy",
                base.source_material[0].receipt,
                base.source_material[0].text,
                support_quotes=[oxygen_line],
                context_quotes=[opening_line],
            )
        ],
    )
    payload = _payload(quote=oxygen_line)
    payload["questions"][0]["accepted_answers"] = []
    payload["questions"][0]["answer"] = "Oxygen"
    captured: dict = {}
    provider = _luna_provider(tmp_path, _c3_payload(request, payload), captured)

    provider.generate(request)

    provider_input = json.loads(captured["input"])
    exposed = provider_input["objective_evidence"]
    assert len(exposed) == 1
    assert exposed[0]["objective_id"] == "obj_energy"
    assert exposed[0]["required_claim_ids"] == [
        request.objective_evidence_bindings[0].support_evidence[0].claim_ids[0]
    ]
    assert exposed[0]["context_evidence"][0]["quote"] == opening_line
    assert exposed[0]["context_evidence"][0]["citation_eligible"] is False
    assert exposed[0]["support_evidence"][0]["quote"] == oxygen_line
    assert exposed[0]["support_evidence"][0]["citation_eligible"] is True
    assert opening_line in captured["input"]
    citation_enum = captured["text"]["format"]["schema"]["properties"][
        "questions"
    ]["items"]["properties"]["citation_evidence_ids"]["items"]["enum"]
    assert citation_enum == [
        request.objective_evidence_bindings[0].support_evidence[0].evidence_id
    ]
    assert (
        request.objective_evidence_bindings[0].context_evidence[0].evidence_id
        not in citation_enum
    )


def test_c3_provider_rejects_context_only_evidence_id_from_provider(
    tmp_path: Path,
) -> None:
    context = "The pathway has four teaching stages."
    support = "Pyruvate is converted to acetyl-CoA."
    base = _request(f"{context}\n{support}")
    binding = _binding(
        "obj_energy",
        base.source_material[0].receipt,
        base.source_material[0].text,
        context_quotes=[context],
        support_quotes=[support],
    )
    request = _as_c3(base, bindings=[binding])
    payload = _payload(quote=support)
    payload["questions"][0]["accepted_answers"] = []
    c3_payload = _c3_payload(request, payload)
    c3_payload["questions"][0]["citation_evidence_ids"] = [
        binding.context_evidence[0].evidence_id
    ]

    with pytest.raises(
        PracticeGenerationProviderError,
        match="provider citation evidence is invalid",
    ):
        _luna_provider(tmp_path, c3_payload, {}).generate(request)


def test_c3_provider_enforces_required_claim_coverage(
    tmp_path: Path,
) -> None:
    overview = "Pyruvate oxidation occurs before the citric acid cycle."
    conversion = "Pyruvate is converted to acetyl-CoA."
    base = _request(f"{overview}\n{conversion}")
    binding = _binding(
        "obj_energy",
        base.source_material[0].receipt,
        base.source_material[0].text,
        support_quotes=[overview, conversion],
        claim_ids_by_quote={
            overview: ["stage_order"],
            conversion: ["pyruvate_to_acetyl_coa"],
        },
    )
    request = _as_c3(
        base,
        bindings=[binding],
        required_claim_ids_by_objective={
            "obj_energy": ["pyruvate_to_acetyl_coa"]
        },
    )
    payload = _payload(quote=overview)
    payload["questions"][0]["accepted_answers"] = []

    with pytest.raises(
        PracticeGenerationProviderError,
        match="provider citation claim coverage is invalid",
    ):
        _luna_provider(
            tmp_path, _c3_payload(request, payload), {}
        ).generate(request)


def test_c3_provider_does_not_credit_same_named_claim_across_objectives(
    tmp_path: Path,
) -> None:
    objective_a_line = "Objective A has its own supporting fact."
    objective_b_line = "Objective B has a different supporting fact."
    base = _request(f"{objective_a_line}\n{objective_b_line}").model_copy(
        update={"objective_ids": ["obj_a", "obj_b"]}
    )
    binding_a = _binding(
        "obj_a",
        base.source_material[0].receipt,
        base.source_material[0].text,
        support_quotes=[objective_a_line],
        claim_ids_by_quote={objective_a_line: ["shared_claim_name"]},
    )
    binding_b = _binding(
        "obj_b",
        base.source_material[0].receipt,
        base.source_material[0].text,
        support_quotes=[objective_b_line],
        claim_ids_by_quote={objective_b_line: ["shared_claim_name"]},
    )
    request = _as_c3(
        base,
        requested_objective_ids=["obj_a", "obj_b"],
        bindings=[binding_a, binding_b],
        required_claim_ids_by_objective={
            "obj_a": ["shared_claim_name"],
            "obj_b": ["shared_claim_name"],
        },
    )
    payload = _payload(objective_ids=["obj_a", "obj_b"], quote=objective_a_line)
    payload["questions"][0]["answer"] = "Objective A has its own supporting fact."
    payload["questions"][0]["accepted_answers"] = []

    with pytest.raises(
        PracticeGenerationProviderError,
        match="provider citation claim coverage is invalid",
    ):
        _luna_provider(
            tmp_path, _c3_payload(request, payload), {}
        ).generate(request)


def test_c3_provider_requires_aggregate_requested_objective_coverage(
    tmp_path: Path,
) -> None:
    objective_a_line = "Objective A has its own supporting fact."
    objective_b_line = "Objective B has a different supporting fact."
    base = _request(f"{objective_a_line}\n{objective_b_line}").model_copy(
        update={"objective_ids": ["obj_a", "obj_b"]}
    )
    binding_a = _binding(
        "obj_a",
        base.source_material[0].receipt,
        base.source_material[0].text,
        support_quotes=[objective_a_line],
        claim_ids_by_quote={objective_a_line: ["claim_a"]},
    )
    binding_b = _binding(
        "obj_b",
        base.source_material[0].receipt,
        base.source_material[0].text,
        support_quotes=[objective_b_line],
        claim_ids_by_quote={objective_b_line: ["claim_b"]},
    )
    request = _as_c3(
        base,
        requested_objective_ids=["obj_a", "obj_b"],
        bindings=[binding_a, binding_b],
        required_claim_ids_by_objective={
            "obj_a": ["claim_a"],
            "obj_b": ["claim_b"],
        },
    )
    payload = _payload(objective_ids=["obj_a"], quote=objective_a_line)
    payload["questions"][0]["answer"] = "Objective A has its own supporting fact."
    payload["questions"][0]["accepted_answers"] = []

    with pytest.raises(
        PracticeGenerationProviderError,
        match="provider requested objective coverage is incomplete",
    ):
        _luna_provider(
            tmp_path, _c3_payload(request, payload), {}
        ).generate(request)


def test_c3_provider_requires_bounded_assessment_answer_variants(
    tmp_path: Path,
) -> None:
    line = "Pyruvate is converted to acetyl-CoA."
    base = _request(line)
    request = _as_c3(
        base,
        bindings=[
            _binding(
                "obj_energy",
                base.source_material[0].receipt,
                base.source_material[0].text,
                support_quotes=[line],
            )
        ],
        required_accepted_answers_by_objective={
            "obj_energy": [
                "Pyruvate is converted to acetyl CoA.",
                "Pyruvate is converted to acetyl coenzyme A.",
            ]
        },
    )
    payload = _payload(quote=line)
    payload["questions"][0]["answer"] = "Pyruvate is converted to acetyl-CoA."
    payload["questions"][0]["accepted_answers"] = [
        "Pyruvate is converted to acetyl CoA."
    ]

    with pytest.raises(
        PracticeGenerationProviderError,
        match="provider accepted answers are incomplete",
    ):
        _luna_provider(
            tmp_path, _c3_payload(request, payload), {}
        ).generate(request)


def test_c3_provider_abstains_before_cost_or_network_when_objective_evidence_missing(
    tmp_path: Path,
) -> None:
    request = _as_c3(_request(), bindings=[])
    captured: dict = {}
    provider = _luna_provider(tmp_path, {}, captured)

    output = provider.generate(request)

    assert output.outcome == "abstain"
    assert output.questions == []
    assert output.response_status == "not_called"
    assert "client" not in captured
    with provider.ledger._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM provider_usage_reservations"
        ).fetchone()[0] == 0


def test_c3_provider_abstains_before_cost_or_network_for_stale_bound_receipt(
    tmp_path: Path,
) -> None:
    base = _request()
    stale_receipt = PracticeSourceReceipt(
            source_id=base.source_material[0].receipt.source_id,
            source_revision=base.source_material[0].receipt.source_revision,
            content_sha256="c" * 64,
    )
    stale_binding = _binding(
        "obj_energy",
        stale_receipt,
        base.source_material[0].text,
        support_quotes=[base.source_material[0].text],
    )
    request = _as_c3(base, bindings=[stale_binding])
    captured: dict = {}
    provider = _luna_provider(tmp_path, {}, captured)

    output = provider.generate(request)

    assert output.outcome == "abstain"
    assert output.response_status == "not_called"
    assert "client" not in captured
    with provider.ledger._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM provider_usage_reservations"
        ).fetchone()[0] == 0


def test_c3_request_contract_hash_changes_with_bound_evidence() -> None:
    base = _request("ATP stores cellular energy. Mitochondria produce ATP.")
    first = _as_c3(
        base,
        bindings=[
            _binding(
                "obj_energy",
                base.source_material[0].receipt,
                base.source_material[0].text,
                support_quotes=["ATP stores cellular energy."],
            )
        ],
    )
    second = _as_c3(
        base,
        bindings=[
            _binding(
                "obj_energy",
                base.source_material[0].receipt,
                base.source_material[0].text,
                support_quotes=["Mitochondria produce ATP."],
            )
        ],
    )

    assert (
        build_practice_generation_request_contract(first).source_scope_hash
        != build_practice_generation_request_contract(second).source_scope_hash
    )


def test_c3_provider_rejects_citation_bound_only_to_another_objective(
    tmp_path: Path,
) -> None:
    energy_line = "ATP stores cellular energy for the cell."
    neighbor_line = "Mitochondria produce ATP for the cell."
    base = _request(f"{energy_line}\n{neighbor_line}").model_copy(
        update={"objective_ids": ["obj_energy", "obj_neighbor"]}
    )
    request = _as_c3(
        base,
        bindings=[
            _binding(
                "obj_energy",
                base.source_material[0].receipt,
                base.source_material[0].text,
                support_quotes=[energy_line],
            ),
            _binding(
                "obj_neighbor",
                base.source_material[0].receipt,
                base.source_material[0].text,
                support_quotes=[neighbor_line],
            ),
        ],
    )
    payload = _payload(quote=neighbor_line)
    payload["questions"][0]["accepted_answers"] = []
    provider = _luna_provider(
        tmp_path,
        _c3_payload(request, payload),
        {},
    )

    with pytest.raises(
        PracticeGenerationProviderError,
        match="provider citation evidence is invalid",
    ):
        provider.generate(request)


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
