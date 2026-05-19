from __future__ import annotations

import asyncio
import importlib

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
router = importlib.import_module("deeptutor.api.routers.practice").router


def _build_app(store: SQLiteSessionStore) -> FastAPI:
    app = FastAPI()
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


def test_create_attempt_truncates_long_title_before_validation(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session(title="Source Chat"))
    long_title = "NBCC NCE professional orientation ethics confidentiality duty to warn " * 3

    with TestClient(_build_app(store)) as client:
        create_resp = client.post(
            "/api/v1/practice/attempts",
            json={
                "session_id": session["id"],
                "title": long_title,
                "topic": "Ethics",
                "quiz_snapshot": {
                    "questions": [
                        {
                            "question_id": "q1",
                            "question": "What is the best ethical response?",
                            "question_type": "choice",
                            "options": {"A": "Ignore", "B": "Consult"},
                        }
                    ]
                },
            },
        )

    assert create_resp.status_code == 200
    assert len(create_resp.json()["attempt"]["title"]) == 100


def test_list_attempts_hides_malformed_quiz_snapshots(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session(title="Source Chat"))
    valid_attempt = asyncio.run(
        store.create_quiz_attempt(
            {
                "session_id": session["id"],
                "title": "Valid Practice Quiz",
                "quiz_snapshot": {
                    "settings": {"num_questions": 1},
                    "questions": [
                        {
                            "question_id": "q1",
                            "question": "What is the best ethical response?",
                            "question_type": "choice",
                            "options": {
                                "A": "Ignore it",
                                "B": "Consult and document",
                                "C": "Promise secrecy",
                                "D": "Avoid the topic",
                            },
                            "correct_answer": "B",
                        }
                    ],
                },
            }
        )
    )
    asyncio.run(
        store.create_quiz_attempt(
            {
                "session_id": session["id"],
                "title": "Malformed Practice Quiz",
                "quiz_snapshot": {
                    "settings": {"num_questions": 6},
                    "questions": [
                        {
                            "question_id": "q1",
                            "question": "Malformed choice item",
                            "question_type": "choice",
                            "options": None,
                            "correct_answer": "N/A",
                        }
                    ],
                },
            }
        )
    )

    with TestClient(_build_app(store)) as client:
        response = client.get("/api/v1/practice/attempts?limit=10&offset=0")

    assert response.status_code == 200
    attempts = response.json()["attempts"]
    assert [attempt["attempt_id"] for attempt in attempts] == [valid_attempt["attempt_id"]]


def test_save_results_and_get_progress(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session(title="Source Chat"))
    attempt = asyncio.run(
        store.create_quiz_attempt(
            {
                "session_id": session["id"],
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
