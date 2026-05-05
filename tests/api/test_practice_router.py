from __future__ import annotations

import asyncio
import importlib

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
practice_router_module = importlib.import_module("deeptutor.api.routers.practice")
router = practice_router_module.router


def _build_app(store: SQLiteSessionStore) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[practice_router_module.get_current_tester] = lambda: {
        "id": "tester-1",
        "tester_id": "tester-1",
        "display_name": "Tester One",
    }
    app.include_router(router, prefix="/api/v1/practice")
    return app


@pytest.fixture
def store(tmp_path, monkeypatch) -> SQLiteSessionStore:
    instance = SQLiteSessionStore(db_path=tmp_path / "practice.db")
    monkeypatch.setattr(
        "deeptutor.api.routers.practice.get_sqlite_session_store",
        lambda: instance,
    )
    return instance


def test_create_and_fetch_attempt(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session(title="Source Chat"))

    with TestClient(_build_app(store)) as client:
        create_resp = client.post(
            "/api/v1/practice/attempts",
            json={
                "session_id": session["id"],
                "title": "Practice Quiz",
                "topic": "Ethics",
                "knowledge_base": "nbcc",
                "mode": "untimed",
                "quiz_snapshot": {
                    "questions": [
                        {
                            "question_id": "q1",
                            "question": "What is empathy?",
                            "question_type": "choice",
                            "options": {"A": "Pity", "B": "Reflection"},
                        }
                    ]
                },
            },
        )
        assert create_resp.status_code == 200
        attempt = create_resp.json()["attempt"]
        assert attempt["question_count"] == 1

        fetch_resp = client.get(f"/api/v1/practice/attempts/{attempt['attempt_id']}")
        assert fetch_resp.status_code == 200
        fetched = fetch_resp.json()["attempt"]
        assert fetched["attempt_id"] == attempt["attempt_id"]
        assert fetched["items"] == []


def test_create_attempt_requires_session_id(store: SQLiteSessionStore) -> None:
    with TestClient(_build_app(store)) as client:
        create_resp = client.post(
            "/api/v1/practice/attempts",
            json={
                "title": "Practice Quiz",
                "topic": "Ethics",
                "quiz_snapshot": {"questions": []},
            },
        )
        assert create_resp.status_code == 400
        assert create_resp.json()["detail"] == "session_id is required"


def test_save_results_and_get_progress(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session(title="Source Chat"))
    attempt = asyncio.run(
        store.create_quiz_attempt(
            {
                "session_id": session["id"],
                "tester_id": "tester-1",
                "title": "Practice Quiz",
                "quiz_snapshot": {
                    "questions": [
                        {
                            "question_id": "q1",
                            "question": "What is empathy?",
                            "question_type": "choice",
                            "options": {"A": "Pity", "B": "Reflection"},
                            "correct_answer": "B",
                            "domain": "Helping Relationships",
                        }
                    ]
                },
            }
        )
    )

    with TestClient(_build_app(store)) as client:
        save_resp = client.post(
            f"/api/v1/practice/attempts/{attempt['attempt_id']}/results",
            json={
                "submitted_at": 123.0,
                "duration_seconds": 12.0,
                "timed_out": False,
                "structured_result": {
                    "score": {"correct": 1, "total": 1, "percent": 100},
                    "question_results": [
                        {
                            "question_id": "q1",
                            "domain": "Helping Relationships",
                            "user_answer": "B",
                            "correct_answer": "B",
                            "is_correct": True,
                            "is_answered": True,
                            "explanation": "Reflection names the feeling.",
                        }
                    ],
                },
            },
        )
        assert save_resp.status_code == 200
        saved = save_resp.json()["attempt"]
        assert saved["status"] == "submitted"
        assert saved["items"][0]["question_id"] == "q1"

        progress_resp = client.get("/api/v1/practice/progress")
        assert progress_resp.status_code == 200
        body = progress_resp.json()
        assert body["domains"][0]["domain"] == "Helping Relationships"


def test_progress_normalizes_domain_variants(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session(title="Source Chat"))
    attempt = asyncio.run(
        store.create_quiz_attempt(
            {
                "session_id": session["id"],
                "tester_id": "tester-1",
                "title": "Practice Quiz",
                "quiz_snapshot": {
                    "questions": [
                        {
                            "question_id": "q1",
                            "question": "What is empathy?",
                            "question_type": "choice",
                            "options": {"A": "Pity", "B": "Reflection"},
                        },
                        {
                            "question_id": "q2",
                            "question": "What is informed consent?",
                            "question_type": "choice",
                            "options": {"A": "Ignore it", "B": "Review it"},
                        },
                    ]
                },
            }
        )
    )

    with TestClient(_build_app(store)) as client:
        save_resp = client.post(
            f"/api/v1/practice/attempts/{attempt['attempt_id']}/results",
            json={
                "submitted_at": 123.0,
                "duration_seconds": 15.0,
                "timed_out": False,
                "structured_result": {
                    "score": {"correct": 1, "total": 2, "percent": 50},
                    "question_results": [
                        {
                            "question_id": "q1",
                            "domain": "helping relationship",
                            "user_answer": "B",
                            "correct_answer": "B",
                            "is_correct": True,
                            "is_answered": True,
                            "explanation": "Reflection names the feeling.",
                        },
                        {
                            "question_id": "q2",
                            "domain": "professional orientation and ethical practice",
                            "user_answer": "A",
                            "correct_answer": "B",
                            "is_correct": False,
                            "is_answered": True,
                            "explanation": "Informed consent must be reviewed.",
                        },
                    ],
                },
            },
        )
        assert save_resp.status_code == 200
        saved = save_resp.json()["attempt"]
        assert saved["items"][0]["domain"] == "Helping Relationships"
        assert saved["items"][1]["domain"] == "Professional Orientation and Ethical Practice"

        progress_resp = client.get("/api/v1/practice/progress")
        assert progress_resp.status_code == 200
        domains = {item["domain"] for item in progress_resp.json()["domains"]}
        assert "Helping Relationships" in domains
        assert "Professional Orientation and Ethical Practice" in domains
