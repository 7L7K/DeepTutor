from __future__ import annotations

import asyncio
import importlib
import json

import pytest

from deeptutor.services.flashcards.service import FlashcardService
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
flashcards_router_module = importlib.import_module("deeptutor.api.routers.flashcards")
router = flashcards_router_module.router


class _FakeLLM:
    class _Config:
        binding = "openai"
        model = "gpt-5-mini"
        api_key = "test-key"
        base_url = "https://api.openai.com/v1"
        extra_headers = None

    config = _Config()

    async def complete(self, *args, **kwargs):
        prompt = str(kwargs.get("prompt") or (args[0] if args else ""))
        if "likely flashcard focus topics" in prompt:
            return """
            {
              "suggestions": ["Ethics boundaries", "Dual relationships", "Social media contact"]
            }
            """
        if "completed flashcard study pass" in prompt:
            return """
            {
              "summary": "You were solid on direct definition cards but missed more applied ethics prompts.",
              "strengths": ["basic definitions"],
              "weak_spots": ["dual relationships", "social media contact scenarios"],
              "recommended_next_step": "Review the missed cards first, then run a narrower ethics deck.",
              "focus_topics": ["dual relationships", "social media boundaries"]
            }
            """
        return """
        {
          "title": "NCE Ethics Boundaries",
          "cards": [
            {
              "front": "What is the safest boundary rule for counselor self-disclosure?",
              "back": "Use self-disclosure only when it clearly serves the client and stays clinically relevant.",
              "hint": "Think client welfare first.",
              "tag": "Definition",
              "source_ref": "kb-one"
            },
            {
              "front": "What is an early warning sign that social-media contact is becoming ethically risky?",
              "back": "When the contact blurs professional roles or creates dual-relationship pressure, it needs review.",
              "hint": "Look for role confusion.",
              "tag": "Scenario",
              "source_ref": "kb-one"
            }
          ]
        }
        """


class _ProgressiveFakeLLM:
    class _Config:
        binding = "openai"
        model = "gpt-5-mini"
        api_key = "test-key"
        base_url = "https://api.openai.com/v1"
        extra_headers = None

    config = _Config()

    def __init__(self) -> None:
        self.generation_calls = 0
        self.calls: list[dict[str, object]] = []

    async def complete(self, *args, **kwargs):
        prompt = str(kwargs.get("prompt") or (args[0] if args else ""))
        if "completed flashcard study pass" in prompt:
            return """
            {
              "summary": "You reviewed the starter cards and the deck stayed consistent after completion.",
              "strengths": ["starter recall"],
              "weak_spots": ["ethics scenarios"],
              "recommended_next_step": "Review the missed card again after the full deck is ready.",
              "focus_topics": ["ethics boundaries"]
            }
            """

        self.generation_calls += 1
        self.calls.append(kwargs)
        if self.generation_calls == 1:
            card_numbers = [1, 2, 3, 4]
        else:
            card_numbers = [2, 5, 6, 7, 8, 9, 10]

        cards = [
            {
                "front": f"Progressive ethics card {index}",
                "back": f"Answer for progressive ethics card {index}.",
                "hint": "",
                "tag": "Recall",
                "source_ref": "",
            }
            for index in card_numbers
        ]
        return json.dumps({"title": "Progressive Ethics Deck", "cards": cards})


class _FakeRAG:
    async def search(self, query: str, kb_name: str, **kwargs):
        return {
            "query": query,
            "content": f"{kb_name} excerpt about ethics boundaries and social-media contact.",
            "sources": [{"kb": kb_name}],
        }


class _EmptyRAG:
    async def search(self, query: str, kb_name: str, **kwargs):
        return {"query": query, "content": "", "sources": []}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/practice/flashcards")
    return app


@pytest.fixture
def service(tmp_path, monkeypatch) -> FlashcardService:
    monkeypatch.setenv("FLASHCARD_PROGRESSIVE", "false")
    store = SQLiteSessionStore(db_path=tmp_path / "flashcards.db")
    instance = FlashcardService()
    instance._store = store
    instance._llm = _FakeLLM()
    instance._use_responses = False
    instance._rag = _FakeRAG()
    monkeypatch.setattr(
        "deeptutor.api.routers.flashcards.get_flashcard_service",
        lambda: instance,
    )
    return instance


def _build_progressive_service(tmp_path, monkeypatch) -> tuple[FlashcardService, list[str]]:
    monkeypatch.setenv("FLASHCARD_PROGRESSIVE", "true")
    monkeypatch.setenv("FLASHCARD_STARTER_COUNT", "4")
    monkeypatch.setenv("FLASHCARD_GENERATION_REASONING_EFFORT", "low")
    monkeypatch.delenv("FLASHCARD_STARTER_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("FLASHCARD_STARTER_MAX_OUTPUT_TOKENS", raising=False)
    store = SQLiteSessionStore(db_path=tmp_path / "flashcards.db")
    instance = FlashcardService()
    instance._store = store
    instance._llm = _ProgressiveFakeLLM()
    instance._reasoning_effort = FlashcardService._resolve_reasoning_effort(instance._llm.config)
    instance._starter_reasoning_effort = FlashcardService._resolve_starter_reasoning_effort(
        instance._llm.config,
        instance._reasoning_effort,
    )
    instance._starter_max_output_tokens = FlashcardService._resolve_starter_max_output_tokens()
    instance._use_responses = False
    instance._rag = _FakeRAG()
    scheduled: list[str] = []
    instance._schedule_progressive_completion = scheduled.append  # type: ignore[method-assign]
    monkeypatch.setattr(
        "deeptutor.api.routers.flashcards.get_flashcard_service",
        lambda: instance,
    )
    return instance, scheduled


def test_generate_list_review_and_restart_flashcards(service: FlashcardService) -> None:
    with TestClient(_build_app()) as client:
        generate_resp = client.post(
            "/api/v1/practice/flashcards/generate",
            json={
                "source_type": "knowledge",
                "topic": "NCE ethics boundaries",
                "knowledge_base_names": ["kb-one"],
                "card_count": 10,
                "style": "mixed",
            },
        )
        assert generate_resp.status_code == 200
        generated = generate_resp.json()
        deck = generated["deck"]
        assert generated["reused_existing"] is False
        assert deck["source_summary"] == "Grounded in kb-one"
        assert len(deck["cards"]) == 2

        list_resp = client.get("/api/v1/practice/flashcards/decks")
        assert list_resp.status_code == 200
        decks = list_resp.json()["decks"]
        assert decks[0]["id"] == deck["id"]

        review_resp = client.post(
            f"/api/v1/practice/flashcards/decks/{deck['id']}/reviews",
            json={"card_id": deck["cards"][0]["id"], "rating": "missed"},
        )
        assert review_resp.status_code == 200
        reviewed = review_resp.json()["deck"]
        assert reviewed["summary"]["counts"]["missed"] == 1

        restart_resp = client.post(f"/api/v1/practice/flashcards/decks/{deck['id']}/restart")
        assert restart_resp.status_code == 200
        restarted = restart_resp.json()["deck"]
        assert restarted["summary"]["counts"]["missed"] == 0
        assert restarted["summary"]["counts"]["new"] == 2


def test_reuses_existing_deck_for_same_fingerprint(service: FlashcardService) -> None:
    with TestClient(_build_app()) as client:
        payload = {
            "source_type": "topic",
            "topic": "NCE ethics boundaries",
            "knowledge_base_names": [],
            "card_count": 10,
            "style": "definition",
        }
        first = client.post("/api/v1/practice/flashcards/generate", json=payload)
        second = client.post("/api/v1/practice/flashcards/generate", json=payload)
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["reused_existing"] is True
        assert second.json()["deck"]["id"] == first.json()["deck"]["id"]


def test_generate_endpoint_returns_progressive_starter_deck(tmp_path, monkeypatch) -> None:
    _service, scheduled = _build_progressive_service(tmp_path, monkeypatch)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/practice/flashcards/generate",
            json={
                "source_type": "topic",
                "topic": "NCE ethics boundaries",
                "knowledge_base_names": [],
                "card_count": 10,
                "style": "mixed",
            },
        )

    assert response.status_code == 200
    deck = response.json()["deck"]
    assert response.json()["reused_existing"] is False
    assert len(deck["cards"]) == 4
    assert deck["generation_settings"]["status"] == "partial"
    assert deck["generation_settings"]["requested_count"] == 10
    assert deck["generation_settings"]["ready_count"] == 4
    assert scheduled == [deck["id"]]
    assert isinstance(_service._llm, _ProgressiveFakeLLM)
    assert _service._llm.calls[0]["reasoning_effort"] == "minimal"
    assert _service._llm.calls[0]["max_completion_tokens"] == 900

    scheduled.clear()
    refreshed = asyncio.run(_service.get_deck(deck["id"]))
    assert refreshed is not None
    assert refreshed["generation_settings"]["status"] == "partial"
    assert scheduled == [deck["id"]]


def test_progressive_completion_appends_without_duplicates_and_preserves_reviews(tmp_path, monkeypatch) -> None:
    service, _scheduled = _build_progressive_service(tmp_path, monkeypatch)

    deck, reused_existing = asyncio.run(
        service.generate_deck(
            source_type="topic",
            topic="NCE ethics boundaries",
            knowledge_base_names=[],
            card_count=10,
            style="mixed",
        )
    )
    assert reused_existing is False
    assert len(deck["cards"]) == 4
    assert deck["generation_settings"]["status"] == "partial"

    reviewed = asyncio.run(
        service.record_review(deck_id=deck["id"], card_id=deck["cards"][0]["id"], rating="missed")
    )
    assert reviewed["summary"]["counts"]["missed"] == 1

    completed = asyncio.run(service.complete_progressive_deck(deck["id"]))
    assert completed is not None
    assert completed["generation_settings"]["status"] == "complete"
    assert completed["generation_settings"]["requested_count"] == 10
    assert completed["generation_settings"]["ready_count"] == 10
    assert len(completed["cards"]) == 10
    fronts = [card["front"] for card in completed["cards"]]
    assert len(fronts) == len(set(fronts))
    assert "Progressive ethics card 2" in fronts
    assert completed["summary"]["counts"]["missed"] == 1
    assert completed["summary"]["counts"]["new"] == 9
    assert isinstance(service._llm, _ProgressiveFakeLLM)
    assert service._llm.calls[0]["reasoning_effort"] == "minimal"
    assert service._llm.calls[1]["reasoning_effort"] == "low"


def test_complete_pass_and_topic_suggestions(service: FlashcardService) -> None:
    with TestClient(_build_app()) as client:
        generated = client.post(
            "/api/v1/practice/flashcards/generate",
            json={
                "source_type": "knowledge",
                "topic": "NCE ethics boundaries",
                "knowledge_base_names": ["kb-one"],
                "card_count": 10,
                "style": "mixed",
            },
        ).json()["deck"]

        for card in generated["cards"]:
            client.post(
                f"/api/v1/practice/flashcards/decks/{generated['id']}/reviews",
                json={"card_id": card["id"], "rating": "missed" if card == generated["cards"][0] else "got_it"},
            )

        complete_resp = client.post(
            f"/api/v1/practice/flashcards/decks/{generated['id']}/complete",
            json={
                "review_mode": "full_deck",
                "card_ids": [card["id"] for card in generated["cards"]],
            },
        )
        assert complete_resp.status_code == 200
        complete_payload = complete_resp.json()
        assert complete_payload["session_review"]["review_mode"] == "full_deck"
        assert complete_payload["session_review"]["analysis_summary"]
        assert complete_payload["deck"]["latest_session_review"]["analysis_recommended_next_step"]

        suggestions_resp = client.post(
            "/api/v1/practice/flashcards/topic-suggestions",
            json={"knowledge_base_names": ["kb-one"], "hint": "ethics"},
        )
        assert suggestions_resp.status_code == 200
        assert "Dual relationships" in suggestions_resp.json()["suggestions"]


def test_missed_only_completion_persists_latest_coach_review(service: FlashcardService) -> None:
    with TestClient(_build_app()) as client:
        generated = client.post(
            "/api/v1/practice/flashcards/generate",
            json={
                "source_type": "knowledge",
                "topic": "NCE ethics boundaries",
                "knowledge_base_names": ["kb-one"],
                "card_count": 10,
                "style": "mixed",
            },
        ).json()["deck"]
        missed_card_id = generated["cards"][0]["id"]

        client.post(
            f"/api/v1/practice/flashcards/decks/{generated['id']}/reviews",
            json={"card_id": missed_card_id, "rating": "missed"},
        )
        complete_resp = client.post(
            f"/api/v1/practice/flashcards/decks/{generated['id']}/complete",
            json={"review_mode": "missed_only", "card_ids": [missed_card_id]},
        )

        assert complete_resp.status_code == 200
        payload = complete_resp.json()
        assert payload["session_review"]["review_mode"] == "missed_only"
        assert payload["session_review"]["cards_reviewed"] == 1
        assert payload["deck"]["latest_session_review"]["review_mode"] == "missed_only"
        assert payload["deck"]["latest_session_review"]["analysis_summary"]


def test_empty_kb_context_fails_before_llm(service: FlashcardService) -> None:
    service._rag = _EmptyRAG()

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/practice/flashcards/generate",
            json={
                "source_type": "knowledge",
                "topic": "no matching context",
                "knowledge_base_names": ["kb-empty"],
                "card_count": 10,
                "style": "mixed",
            },
        )

    assert response.status_code == 400
    assert "did not return usable study context" in response.json()["detail"]


def test_flashcard_generation_can_use_responses_path(service: FlashcardService, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    async def fake_responses_generation(**kwargs):
        calls.append(kwargs)
        return {
            "title": "Responses Deck",
            "cards": [
                {
                    "front": f"Responses card {index}",
                    "back": "A concise generated answer.",
                    "hint": "",
                    "tag": "Recall",
                    "source_ref": "",
                }
                for index in range(1, 4)
            ],
        }

    service._use_responses = True
    monkeypatch.setattr(service, "_generate_cards_with_responses", fake_responses_generation)

    deck, reused_existing = asyncio.run(
        service.generate_deck(
            source_type="topic",
            topic="NCE ethics boundaries",
            knowledge_base_names=[],
            card_count=10,
            style="mixed",
        )
    )

    assert reused_existing is False
    assert len(deck["cards"]) == 3
    assert calls
    assert calls[0]["source_type"] == "topic"
    assert calls[0]["candidate_count"] == 10


def test_flashcard_generation_defaults_responses_and_low_reasoning_for_openai_gpt5(monkeypatch) -> None:
    class Config:
        binding = "openai"
        model = "gpt-5-mini"
        api_key = "test-key"

    monkeypatch.delenv("FLASHCARD_USE_RESPONSES", raising=False)

    assert FlashcardService._resolve_use_responses(Config()) is True
    assert FlashcardService._resolve_reasoning_effort(Config()) == "low"


def test_flashcard_generation_does_not_overgenerate_small_decks_by_default(service: FlashcardService, monkeypatch) -> None:
    monkeypatch.delenv("FLASHCARD_EXTRA_CANDIDATES", raising=False)

    _system_prompt, user_prompt, candidate_count = service._build_generation_prompts(
        source_type="topic",
        topic="NCE ethics boundaries",
        knowledge_base_names=[],
        card_count=10,
        style="mixed",
        source_context=[],
    )

    assert candidate_count == 10
    assert "Generate 10 flashcards." in user_prompt


def test_flashcard_generation_candidate_overage_can_be_configured(service: FlashcardService, monkeypatch) -> None:
    monkeypatch.setenv("FLASHCARD_EXTRA_CANDIDATES", "3")

    _system_prompt, user_prompt, candidate_count = service._build_generation_prompts(
        source_type="topic",
        topic="NCE ethics boundaries",
        knowledge_base_names=[],
        card_count=10,
        style="mixed",
        source_context=[],
    )

    assert candidate_count == 13
    assert "Generate 13 flashcards." in user_prompt
