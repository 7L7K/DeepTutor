from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import sessions as sessions_router
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    primary = SQLiteSessionStore(tmp_path / "admin" / "chat_history.db")
    personal = SQLiteSessionStore(tmp_path / "personal" / "chat_history.db")
    monkeypatch.setattr(sessions_router, "get_session_store", lambda: primary)
    monkeypatch.setattr(sessions_router, "get_sqlite_session_store", lambda: primary)
    monkeypatch.setattr(sessions_router, "get_personal_sqlite_session_store", lambda: personal)
    course_state = {"value": "active"}
    monkeypatch.setattr(
        sessions_router,
        "_assert_course_session_write_allowed",
        lambda session: (
            None
            if not session.get("course_id") or course_state["value"] == "active"
            else (_ for _ in ()).throw(
                sessions_router.HTTPException(
                    status_code=409, detail="Archived Course sessions are read-only"
                )
            )
        ),
    )

    import asyncio

    generic = asyncio.run(primary.create_session(title="General"))
    course = asyncio.run(personal.create_session(title="Course", course_id="crs_one"))
    app = FastAPI()
    app.include_router(sessions_router.router, prefix="/api/v1/sessions")
    return TestClient(app), generic, course, course_state


def test_session_api_combines_same_identity_admin_and_personal_course_stores(client) -> None:
    http, generic, course, _course_state = client
    listed = http.get("/api/v1/sessions")
    assert listed.status_code == 200
    assert {item["session_id"] for item in listed.json()["sessions"]} == {
        generic["id"],
        course["id"],
    }
    detail = http.get(f"/api/v1/sessions/{course['id']}")
    assert detail.status_code == 200
    assert detail.json()["course_id"] == "crs_one"


def test_course_session_has_no_permanent_delete_path(client) -> None:
    http, generic, course, _course_state = client
    assert http.delete(f"/api/v1/sessions/{course['id']}").status_code == 409
    assert http.delete(f"/api/v1/sessions/{generic['id']}").status_code == 200
    assert http.get(f"/api/v1/sessions/{course['id']}").status_code == 200


def test_archived_course_session_blocks_generic_metadata_writes(client) -> None:
    http, _generic, course, course_state = client
    course_state["value"] = "archived"

    rename = http.patch(
        f"/api/v1/sessions/{course['id']}",
        json={"title": "Mutated after archive"},
    )
    branch = http.put(
        f"/api/v1/sessions/{course['id']}/branch-selection",
        json={"selected_branches": {"1": 2}},
    )

    assert rename.status_code == 409
    assert branch.status_code == 409
    detail = http.get(f"/api/v1/sessions/{course['id']}").json()
    assert detail["title"] == "Course"
    assert detail["preferences"] == {}
