from __future__ import annotations

import importlib

import pytest

from deeptutor.services.flashcards.service import FlashcardService
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
router = importlib.import_module("deeptutor.api.routers.flashcards").router


class _FakeLLM:
    class _Config:
        binding = "openai"
        model = "gpt-5-mini"

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


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/practice/flashcards")
    return app


@pytest.fixture
def service(tmp_path, monkeypatch) -> FlashcardService:
    store = SQLiteSessionStore(db_path=tmp_path / "flashcards.db")
    instance = FlashcardService()
    instance._store = store
    instance._llm = _FakeLLM()
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
