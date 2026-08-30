from __future__ import annotations

import asyncio
import base64
import importlib
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
notebook_router = importlib.import_module("deeptutor.api.routers.question_notebook").router
sessions_router = importlib.import_module("deeptutor.api.routers.sessions").router

from deeptutor.services.config.runtime_settings import ChatAttachmentLimits
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


class _MemoryAttachmentStore:
    def __init__(self) -> None:
        self.files: dict[tuple[str, str], bytes] = {}
        self.put_calls = 0

    async def put(self, *, session_id, attachment_id, filename, data, mime_type="") -> str:
        self.put_calls += 1
        self.files[(session_id, attachment_id)] = data
        return f"/api/attachments/{session_id}/{attachment_id}/{filename}"

    async def delete_attachment(self, session_id: str, attachment_id: str) -> None:
        self.files.pop((session_id, attachment_id), None)


def _build_app(store: SQLiteSessionStore) -> FastAPI:
    app = FastAPI()
    app.include_router(notebook_router, prefix="/api/v1/question-notebook")
    app.include_router(sessions_router, prefix="/api/v1/sessions")
    return app


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> SQLiteSessionStore:
    instance = SQLiteSessionStore(db_path=tmp_path / "router-test.db")
    monkeypatch.setattr(
        "deeptutor.api.routers.question_notebook.get_sqlite_session_store",
        lambda: instance,
    )
    monkeypatch.setattr(
        "deeptutor.api.routers.sessions.get_sqlite_session_store",
        lambda: instance,
    )
    return instance


def _quiz_answers():
    return [
        {
            "question_id": "q1",
            "question": "Capital of France?",
            "question_type": "choice",
            "options": {"A": "Berlin", "B": "Paris"},
            "user_answer": "A",
            "correct_answer": "B",
            "explanation": "Paris is the capital.",
            "difficulty": "easy",
            "is_correct": False,
        },
        {
            "question_id": "q2",
            "question": "2+2?",
            "question_type": "choice",
            "options": {"A": "3", "B": "4"},
            "user_answer": "B",
            "correct_answer": "B",
            "is_correct": True,
        },
    ]


def _answer_image_payload(session_id: str, **overrides):
    return {
        "session_id": session_id,
        "question_id": "q-image",
        "question": "Show your work",
        "user_answer_images": [
            {
                "filename": "answer.png",
                "mime_type": "image/png",
                "base64": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode(),
            }
        ],
        **overrides,
    }


def test_list_entries_empty(store: SQLiteSessionStore) -> None:
    with TestClient(_build_app(store)) as client:
        resp = client.get("/api/v1/question-notebook/entries")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}


def test_quiz_results_populates_notebook(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session(title="Quiz Session"))
    sid = session["id"]

    with TestClient(_build_app(store)) as client:
        resp = client.post(
            f"/api/v1/sessions/{sid}/quiz-results",
            json={"answers": _quiz_answers()},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["recorded"] is True
        assert body["notebook_count"] == 2
        assert "[Quiz Performance]" in body["content"]

        listing = client.get("/api/v1/question-notebook/entries")
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert len(items) == 2


def test_quiz_results_upserts_on_retry(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    sid = session["id"]

    with TestClient(_build_app(store)) as client:
        client.post(f"/api/v1/sessions/{sid}/quiz-results", json={"answers": _quiz_answers()})
        updated = _quiz_answers()
        updated[0]["user_answer"] = "B"
        updated[0]["is_correct"] = True
        client.post(f"/api/v1/sessions/{sid}/quiz-results", json={"answers": updated})

        listing = client.get("/api/v1/question-notebook/entries").json()
        assert listing["total"] == 2
        q1 = next(e for e in listing["items"] if e["question_id"] == "q1")
        assert q1["is_correct"] is True
        assert q1["user_answer"] == "B"


def test_bookmark_toggle(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(
        store.upsert_notebook_entries(
            session["id"],
            [
                {
                    "question_id": "q1",
                    "question": "Q?",
                    "is_correct": False,
                }
            ],
        )
    )
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]

    with TestClient(_build_app(store)) as client:
        resp = client.patch(
            f"/api/v1/question-notebook/entries/{eid}",
            json={"bookmarked": True},
        )
        assert resp.status_code == 200

        bm = client.get("/api/v1/question-notebook/entries?bookmarked=true").json()
        assert bm["total"] == 1

        client.patch(f"/api/v1/question-notebook/entries/{eid}", json={"bookmarked": False})
        bm2 = client.get("/api/v1/question-notebook/entries?bookmarked=true").json()
        assert bm2["total"] == 0


def test_delete_entry(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(
        store.upsert_notebook_entries(
            session["id"],
            [
                {
                    "question_id": "q1",
                    "question": "Q?",
                    "is_correct": False,
                }
            ],
        )
    )
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]

    with TestClient(_build_app(store)) as client:
        assert client.delete(f"/api/v1/question-notebook/entries/{eid}").status_code == 200
        assert client.delete(f"/api/v1/question-notebook/entries/{eid}").status_code == 404


def test_category_crud_and_association(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(
        store.upsert_notebook_entries(
            session["id"],
            [
                {
                    "question_id": "q1",
                    "question": "Q?",
                    "is_correct": False,
                }
            ],
        )
    )
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]

    with TestClient(_build_app(store)) as client:
        cat_resp = client.post(
            "/api/v1/question-notebook/categories",
            json={"name": "Math"},
        )
        assert cat_resp.status_code == 201
        cat_id = cat_resp.json()["id"]

        cats = client.get("/api/v1/question-notebook/categories").json()
        assert len(cats) == 1
        assert cats[0]["name"] == "Math"

        add_resp = client.post(
            f"/api/v1/question-notebook/entries/{eid}/categories",
            json={"category_id": cat_id},
        )
        assert add_resp.status_code == 200

        by_cat = client.get(f"/api/v1/question-notebook/entries?category_id={cat_id}").json()
        assert by_cat["total"] == 1

        rm_resp = client.delete(f"/api/v1/question-notebook/entries/{eid}/categories/{cat_id}")
        assert rm_resp.status_code == 200
        by_cat2 = client.get(f"/api/v1/question-notebook/entries?category_id={cat_id}").json()
        assert by_cat2["total"] == 0

        client.patch(f"/api/v1/question-notebook/categories/{cat_id}", json={"name": "Algebra"})
        cats2 = client.get("/api/v1/question-notebook/categories").json()
        assert cats2[0]["name"] == "Algebra"

        client.delete(f"/api/v1/question-notebook/categories/{cat_id}")
        assert client.get("/api/v1/question-notebook/categories").json() == []


def test_lookup_entry_by_question(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(
        store.upsert_notebook_entries(
            session["id"],
            [
                {
                    "question_id": "q1",
                    "question": "Q?",
                    "is_correct": False,
                }
            ],
        )
    )

    with TestClient(_build_app(store)) as client:
        resp = client.get(
            "/api/v1/question-notebook/entries/lookup/by-question",
            params={"session_id": session["id"], "question_id": "q1"},
        )
        assert resp.status_code == 200
        assert resp.json()["question_id"] == "q1"

        resp404 = client.get(
            "/api/v1/question-notebook/entries/lookup/by-question",
            params={"session_id": session["id"], "question_id": "nope"},
        )
        assert resp404.status_code == 404


def test_quiz_state_isolated_per_turn(store: SQLiteSessionStore) -> None:
    """Regression test for #487 — two quizzes in the same chat session must
    not share answer state, even when the positional ``question_id`` (e.g.
    ``q_1``) collides. The producing turn_id scopes notebook entries.
    """
    session = asyncio.run(store.create_session())
    sid = session["id"]

    with TestClient(_build_app(store)) as client:
        first = _quiz_answers()
        resp1 = client.post(
            f"/api/v1/sessions/{sid}/quiz-results",
            json={"answers": first, "turn_id": "turn_A"},
        )
        assert resp1.status_code == 200
        assert resp1.json()["notebook_count"] == 2

        second = _quiz_answers()
        second[0]["user_answer"] = ""
        second[0]["is_correct"] = False
        resp2 = client.post(
            f"/api/v1/sessions/{sid}/quiz-results",
            json={"answers": second, "turn_id": "turn_B"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["notebook_count"] == 2

        listing = client.get("/api/v1/question-notebook/entries").json()
        assert listing["total"] == 4

        # Looking up q1 scoped to the first turn returns the first quiz's
        # answer, not the second.
        scoped_a = client.get(
            "/api/v1/question-notebook/entries/lookup/by-question",
            params={"session_id": sid, "question_id": "q1", "turn_id": "turn_A"},
        )
        assert scoped_a.status_code == 200
        assert scoped_a.json()["user_answer"] == "A"
        assert scoped_a.json()["turn_id"] == "turn_A"

        # The second turn has no recorded answer for q1.
        scoped_b = client.get(
            "/api/v1/question-notebook/entries/lookup/by-question",
            params={"session_id": sid, "question_id": "q1", "turn_id": "turn_B"},
        )
        assert scoped_b.status_code == 200
        assert scoped_b.json()["user_answer"] == ""
        assert scoped_b.json()["turn_id"] == "turn_B"


def test_lookup_without_turn_id_only_matches_legacy_namespace(
    store: SQLiteSessionStore,
) -> None:
    """Regression test for #677 — a lookup that doesn't pass turn_id must
    never see turn-scoped rows (positional ids like ``q_1`` repeat across
    quizzes, so a cross-turn fallback leaks the previous quiz's answers into
    a new quiz). It only matches the legacy namespace (turn_id='')."""
    session = asyncio.run(store.create_session())
    sid = session["id"]

    asyncio.run(
        store.upsert_notebook_entries(
            sid,
            [
                {
                    "turn_id": "turn_A",
                    "question_id": "q1",
                    "question": "Q?",
                    "user_answer": "A",
                    "is_correct": False,
                }
            ],
        )
    )

    with TestClient(_build_app(store)) as client:
        # Turn-scoped rows are invisible without their turn_id.
        resp = client.get(
            "/api/v1/question-notebook/entries/lookup/by-question",
            params={"session_id": sid, "question_id": "q1"},
        )
        assert resp.status_code == 404

        # Pre-turn-scoping rows (migrated with turn_id='') stay reachable.
        asyncio.run(
            store.upsert_notebook_entries(
                sid,
                [
                    {
                        "turn_id": "",
                        "question_id": "q1",
                        "question": "Q?",
                        "user_answer": "B",
                        "is_correct": True,
                    }
                ],
            )
        )
        legacy = client.get(
            "/api/v1/question-notebook/entries/lookup/by-question",
            params={"session_id": sid, "question_id": "q1"},
        )
        assert legacy.status_code == 200
        assert legacy.json()["turn_id"] == ""
        assert legacy.json()["user_answer"] == "B"


def test_lookup_missing_entry_returns_404_by_default(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    sid = session["id"]
    with TestClient(_build_app(store)) as client:
        resp = client.get(
            "/api/v1/question-notebook/entries/lookup/by-question",
            params={"session_id": sid, "question_id": "absent"},
        )
        assert resp.status_code == 404


def test_lookup_missing_entry_returns_204_when_missing_ok(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    sid = session["id"]
    with TestClient(_build_app(store)) as client:
        resp = client.get(
            "/api/v1/question-notebook/entries/lookup/by-question",
            params={"session_id": sid, "question_id": "absent", "missing_ok": "true"},
        )
        assert resp.status_code == 204
        assert resp.content == b""


def test_answer_images_are_validated_before_missing_session_writes(store, monkeypatch) -> None:
    attachment_store = _MemoryAttachmentStore()
    monkeypatch.setattr(
        "deeptutor.api.routers.question_notebook.get_attachment_store", lambda: attachment_store
    )

    with TestClient(_build_app(store)) as client:
        response = client.post(
            "/api/v1/question-notebook/entries/upsert",
            json=_answer_image_payload("missing-session"),
        )

    assert response.status_code == 404
    assert attachment_store.put_calls == 0


def test_answer_images_reject_invalid_base64_without_writing(store, monkeypatch) -> None:
    attachment_store = _MemoryAttachmentStore()
    monkeypatch.setattr(
        "deeptutor.api.routers.question_notebook.get_attachment_store", lambda: attachment_store
    )
    sid = asyncio.run(store.create_session())["id"]

    with TestClient(_build_app(store)) as client:
        response = client.post(
            "/api/v1/question-notebook/entries/upsert",
            json=_answer_image_payload(
                sid,
                user_answer_images=[
                    {"filename": "answer.png", "mime_type": "image/png", "base64": "bad base64!"}
                ],
            ),
        )

    assert response.status_code == 400
    assert attachment_store.put_calls == 0


def test_replacing_or_deleting_answer_images_cleans_the_old_file(store, monkeypatch) -> None:
    attachment_store = _MemoryAttachmentStore()
    monkeypatch.setattr(
        "deeptutor.api.routers.question_notebook.get_attachment_store", lambda: attachment_store
    )
    sid = asyncio.run(store.create_session())["id"]

    with TestClient(_build_app(store)) as client:
        created = client.post(
            "/api/v1/question-notebook/entries/upsert", json=_answer_image_payload(sid)
        )
        assert created.status_code == 200
        image_id = created.json()["user_answer_images"][0]["id"]
        assert (sid, image_id) in attachment_store.files

        replaced = client.post(
            "/api/v1/question-notebook/entries/upsert",
            json=_answer_image_payload(sid, user_answer_images=[]),
        )
        assert replaced.status_code == 200
        assert (sid, image_id) not in attachment_store.files

        entry_id = replaced.json()["id"]
        assert client.delete(f"/api/v1/question-notebook/entries/{entry_id}").status_code == 200


def test_answer_images_are_cleaned_when_database_upsert_fails(store, monkeypatch) -> None:
    attachment_store = _MemoryAttachmentStore()
    monkeypatch.setattr(
        "deeptutor.api.routers.question_notebook.get_attachment_store", lambda: attachment_store
    )
    sid = asyncio.run(store.create_session())["id"]

    async def fail_upsert(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(store, "upsert_notebook_entries", fail_upsert)

    with TestClient(_build_app(store)) as client:
        response = client.post(
            "/api/v1/question-notebook/entries/upsert",
            json=_answer_image_payload(sid),
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Could not save notebook entry"
    assert attachment_store.files == {}


def test_answer_image_encoded_size_is_rejected_before_storage(store, monkeypatch) -> None:
    """Pydantic rejects oversize base64 before the route can decode or write it."""
    attachment_store = _MemoryAttachmentStore()
    monkeypatch.setattr(
        "deeptutor.api.routers.question_notebook.get_attachment_store", lambda: attachment_store
    )
    monkeypatch.setattr(
        "deeptutor.services.config.runtime_settings.get_chat_attachment_limits",
        lambda: ChatAttachmentLimits(
            max_file_bytes=4,
            max_total_bytes=4,
            max_chars_per_doc=10_000,
            max_chars_total=10_000,
        ),
    )
    sid = asyncio.run(store.create_session())["id"]

    with TestClient(_build_app(store)) as client:
        response = client.post(
            "/api/v1/question-notebook/entries/upsert",
            json=_answer_image_payload(
                sid,
                user_answer_images=[
                    {
                        "filename": "answer.png",
                        "mime_type": "image/png",
                        "base64": base64.b64encode(b"too-large").decode(),
                    }
                ],
            ),
        )

    assert response.status_code == 422
    assert attachment_store.put_calls == 0
