from __future__ import annotations

import asyncio
import importlib

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
    app.dependency_overrides[flashcards_router_module.get_current_tester] = lambda: {
        "id": "local-default",
        "tester_id": "local-default",
        "display_name": "Local Tester",
    }
    app.include_router(router, prefix="/api/v1/practice/flashcards")
    return app


@pytest.fixture
def service(tmp_path, monkeypatch) -> FlashcardService:
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

    deck, reused_existing, should_continue = asyncio.run(
        service.generate_progressive_deck(
            source_type="topic",
            topic="NCE ethics boundaries",
            knowledge_base_names=[],
            card_count=10,
            style="mixed",
            tester_id="local-default",
        )
    )

    assert reused_existing is False
    assert should_continue is True
    assert len(deck["cards"]) == 3
    assert calls
    assert calls[0]["source_type"] == "topic"


def test_flashcard_generation_defaults_chat_and_low_reasoning_for_openai_gpt5(monkeypatch) -> None:
    class Config:
        binding = "openai"
        model = "gpt-5-mini"

    monkeypatch.delenv("FLASHCARD_USE_RESPONSES", raising=False)

    assert FlashcardService._resolve_use_responses(Config()) is False
    assert FlashcardService._resolve_reasoning_effort(Config()) == "low"
