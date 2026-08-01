from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
import stat

import pytest

from deeptutor.services.path_service import PathService
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def test_sqlite_store_defaults_to_data_user_chat_history_db(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"

        store = SQLiteSessionStore()

        assert store.db_path == tmp_path / "data" / "user" / "chat_history.db"
        assert store.db_path.exists()
    finally:
        service._project_root = original_root
        service._user_data_dir = original_user_dir


def test_sqlite_store_migrates_legacy_chat_history_db(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"
        legacy_db = tmp_path / "data" / "chat_history.db"
        legacy_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(legacy_db) as conn:
            conn.execute("CREATE TABLE legacy (id INTEGER PRIMARY KEY)")
            conn.commit()

        store = SQLiteSessionStore()

        assert store.db_path.exists()
        assert not legacy_db.exists()
    finally:
        service._project_root = original_root
        service._user_data_dir = original_user_dir


def test_notebook_rebuild_preserves_extended_fields_and_categories(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-notebook.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New conversation',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE notebook_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                question_id TEXT NOT NULL,
                question TEXT NOT NULL,
                question_type TEXT DEFAULT '',
                options_json TEXT DEFAULT '{}',
                correct_answer TEXT DEFAULT '',
                explanation TEXT DEFAULT '',
                difficulty TEXT DEFAULT '',
                user_answer TEXT DEFAULT '',
                user_answer_images_json TEXT DEFAULT '[]',
                is_correct INTEGER DEFAULT 0,
                bookmarked INTEGER DEFAULT 0,
                followup_session_id TEXT DEFAULT '',
                ai_judgment TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(session_id, question_id)
            );
            CREATE TABLE notebook_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at REAL NOT NULL
            );
            CREATE TABLE notebook_entry_categories (
                entry_id INTEGER NOT NULL REFERENCES notebook_entries(id) ON DELETE CASCADE,
                category_id INTEGER NOT NULL REFERENCES notebook_categories(id) ON DELETE CASCADE,
                PRIMARY KEY (entry_id, category_id)
            );
            INSERT INTO sessions (id, title, created_at, updated_at)
                VALUES ('s1', 'Legacy', 1, 1);
            INSERT INTO notebook_entries (
                id, session_id, question_id, question, user_answer_images_json,
                ai_judgment, created_at, updated_at
            ) VALUES (1, 's1', 'q1', 'Question?', '[{"id":"img1"}]', 'careful', 1, 1);
            INSERT INTO notebook_categories (id, name, created_at)
                VALUES (1, 'Review', 1);
            INSERT INTO notebook_entry_categories (entry_id, category_id) VALUES (1, 1);
            """
        )

    store = SQLiteSessionStore(db_path=db_path)

    with sqlite3.connect(store.db_path) as conn:
        entry = conn.execute(
            "SELECT turn_id, user_answer_images_json, ai_judgment FROM notebook_entries"
        ).fetchone()
        link = conn.execute(
            "SELECT entry_id, category_id FROM notebook_entry_categories"
        ).fetchone()
    assert entry == ("", '[{"id":"img1"}]', "careful")
    assert link == (1, 1)


@pytest.fixture
def store(tmp_path: Path) -> SQLiteSessionStore:
    instance = SQLiteSessionStore(db_path=tmp_path / "test.db")
    assert stat.S_IMODE(instance.db_path.stat().st_mode) == 0o600
    return instance


def _make_items(*specs):
    """Build notebook entry dicts from (qid, question, is_correct) tuples."""
    items = []
    for qid, question, is_correct in specs:
        items.append(
            {
                "question_id": qid,
                "question": question,
                "question_type": "choice",
                "options": {"A": "opt_a", "B": "opt_b"},
                "user_answer": "A",
                "correct_answer": "B",
                "explanation": "expl",
                "difficulty": "medium",
                "is_correct": is_correct,
            }
        )
    return items


def test_course_session_binding_is_immutable_and_unknown_ids_do_not_autocreate(
    store: SQLiteSessionStore,
) -> None:
    course_session = asyncio.run(store.create_session(course_id="crs_one"))
    assert course_session["course_id"] == "crs_one"
    assert asyncio.run(
        store.ensure_session(
            course_session["id"], course_id="crs_one", require_existing=True
        )
    )["id"] == course_session["id"]

    with pytest.raises(RuntimeError, match="Session not found"):
        asyncio.run(
            store.ensure_session(
                "missing", course_id="crs_one", require_existing=True
            )
        )
    with pytest.raises(RuntimeError, match="Session not found"):
        asyncio.run(
            store.ensure_session(
                course_session["id"], course_id="crs_two", require_existing=True
            )
        )
    sessions = asyncio.run(store.list_sessions())
    assert [item["session_id"] for item in sessions] == [course_session["id"]]


# ── Notebook entries ──────────────────────────────────────────────


def test_upsert_notebook_entries_persists_all(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session(title="Test"))
    items = _make_items(("q1", "2+2?", False), ("q2", "3+3?", True), ("q3", "5+5?", False))
    upserted = asyncio.run(store.upsert_notebook_entries(session["id"], items))
    assert upserted == 3
    result = asyncio.run(store.list_notebook_entries())
    assert result["total"] == 3
    assert all(e["session_title"] == "Test" for e in result["items"])


def test_upsert_notebook_entries_updates_on_conflict(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    sid = session["id"]
    asyncio.run(store.upsert_notebook_entries(sid, _make_items(("q1", "Q?", False))))
    result = asyncio.run(store.list_notebook_entries())
    assert result["items"][0]["is_correct"] is False

    asyncio.run(
        store.upsert_notebook_entries(
            sid,
            [
                {
                    "question_id": "q1",
                    "question": "Q?",
                    "user_answer": "B",
                    "correct_answer": "B",
                    "is_correct": True,
                }
            ],
        )
    )
    result = asyncio.run(store.list_notebook_entries())
    assert result["total"] == 1
    assert result["items"][0]["is_correct"] is True
    assert result["items"][0]["user_answer"] == "B"


def test_upsert_skips_blank_questions(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    items = [
        {"question_id": "q1", "question": "", "is_correct": False},
        {"question_id": "", "question": "Valid?", "is_correct": False},
        {"question_id": "q3", "question": "OK?", "is_correct": False},
    ]
    upserted = asyncio.run(store.upsert_notebook_entries(session["id"], items))
    assert upserted == 1


def test_upsert_unknown_session_raises(store: SQLiteSessionStore) -> None:
    with pytest.raises(ValueError, match="Session not found"):
        asyncio.run(store.upsert_notebook_entries("nope", _make_items(("q1", "Q?", False))))


def test_list_entries_filters_bookmarked(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(
        store.upsert_notebook_entries(
            session["id"],
            _make_items(
                ("q1", "Q1?", False),
                ("q2", "Q2?", True),
            ),
        )
    )
    entries = asyncio.run(store.list_notebook_entries())["items"]
    asyncio.run(store.update_notebook_entry(entries[0]["id"], {"bookmarked": True}))
    bm = asyncio.run(store.list_notebook_entries(bookmarked=True))
    assert bm["total"] == 1
    assert bm["items"][0]["bookmarked"] is True


def test_list_entries_filters_is_correct(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(
        store.upsert_notebook_entries(
            session["id"],
            _make_items(
                ("q1", "Q1?", False),
                ("q2", "Q2?", True),
            ),
        )
    )
    wrong = asyncio.run(store.list_notebook_entries(is_correct=False))
    assert wrong["total"] == 1
    assert wrong["items"][0]["question_id"] == "q1"


def test_update_notebook_entry_bookmark_roundtrip(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], _make_items(("q1", "Q?", False))))
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]
    assert asyncio.run(store.update_notebook_entry(eid, {"bookmarked": True})) is True
    assert asyncio.run(store.get_notebook_entry(eid))["bookmarked"] is True
    assert asyncio.run(store.update_notebook_entry(eid, {"bookmarked": False})) is True
    assert asyncio.run(store.get_notebook_entry(eid))["bookmarked"] is False
    assert asyncio.run(store.update_notebook_entry(99999, {"bookmarked": True})) is False


def test_update_followup_session_id(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], _make_items(("q1", "Q?", False))))
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]
    asyncio.run(store.update_notebook_entry(eid, {"followup_session_id": "sess_fu"}))
    entry = asyncio.run(store.get_notebook_entry(eid))
    assert entry["followup_session_id"] == "sess_fu"


def test_find_notebook_entry(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], _make_items(("q1", "Q?", False))))
    found = asyncio.run(store.find_notebook_entry(session["id"], "q1"))
    assert found is not None
    assert found["question_id"] == "q1"
    assert asyncio.run(store.find_notebook_entry(session["id"], "nope")) is None


def test_delete_notebook_entry(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(
        store.upsert_notebook_entries(
            session["id"],
            _make_items(
                ("q1", "Q1?", False),
                ("q2", "Q2?", False),
            ),
        )
    )
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]
    assert asyncio.run(store.delete_notebook_entry(eid)) is True
    assert asyncio.run(store.list_notebook_entries())["total"] == 1
    assert asyncio.run(store.delete_notebook_entry(99999)) is False


def test_entries_cascade_on_session_delete(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], _make_items(("q1", "Q?", False))))
    assert asyncio.run(store.list_notebook_entries())["total"] == 1
    asyncio.run(store.delete_session(session["id"]))
    assert asyncio.run(store.list_notebook_entries())["total"] == 0


# ── Categories ────────────────────────────────────────────────────


def test_category_crud(store: SQLiteSessionStore) -> None:
    cat = asyncio.run(store.create_category("Math"))
    assert cat["name"] == "Math"
    cats = asyncio.run(store.list_categories())
    assert len(cats) == 1
    assert cats[0]["entry_count"] == 0

    asyncio.run(store.rename_category(cat["id"], "Algebra"))
    cats = asyncio.run(store.list_categories())
    assert cats[0]["name"] == "Algebra"

    asyncio.run(store.delete_category(cat["id"]))
    assert asyncio.run(store.list_categories()) == []


def test_entry_category_association(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], _make_items(("q1", "Q?", False))))
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]
    cat = asyncio.run(store.create_category("Physics"))

    assert asyncio.run(store.add_entry_to_category(eid, cat["id"])) is True
    entry = asyncio.run(store.get_notebook_entry(eid))
    assert len(entry["categories"]) == 1
    assert entry["categories"][0]["name"] == "Physics"

    by_cat = asyncio.run(store.list_notebook_entries(category_id=cat["id"]))
    assert by_cat["total"] == 1

    asyncio.run(store.remove_entry_from_category(eid, cat["id"]))
    assert asyncio.run(store.get_entry_categories(eid)) == []


def test_category_cascade_on_entry_delete(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], _make_items(("q1", "Q?", False))))
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]
    cat = asyncio.run(store.create_category("History"))
    asyncio.run(store.add_entry_to_category(eid, cat["id"]))
    asyncio.run(store.delete_notebook_entry(eid))
    cats = asyncio.run(store.list_categories())
    assert cats[0]["entry_count"] == 0
