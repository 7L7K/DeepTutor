from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import historical_migration as router_module
from deeptutor.courses.models import Course
from deeptutor.courses.repository import CourseNotFoundError
from deeptutor.historical_migration.scanner import SOURCE_ENV
from deeptutor.multi_user.context import set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from tests.historical_migration.test_scanner import build_legacy_database


class FakeCourseService:
    def __init__(self) -> None:
        self.courses = {
            "crs_course": Course(
                id="crs_course",
                owner_user_id="target-user",
                title="Course",
                workspace_kind="academic_course",
                state="active",
                revision=1,
                write_epoch=1,
                created_at=1,
                updated_at=1,
            ),
            "crs_general": Course(
                id="crs_general",
                owner_user_id="target-user",
                title="General Study",
                workspace_kind="general_study",
                state="active",
                revision=1,
                write_epoch=1,
                created_at=1,
                updated_at=1,
            ),
        }

    def get(self, course_id: str) -> Course:
        try:
            return self.courses[course_id]
        except KeyError as exc:
            raise CourseNotFoundError(course_id) from exc


def build_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    legacy = build_legacy_database(tmp_path / "legacy.db")
    monkeypatch.setenv(SOURCE_ENV, str(legacy))
    monkeypatch.setattr(router_module, "get_current_course_service", lambda: FakeCourseService())

    async def authenticated_user() -> None:
        set_current_user(
            CurrentUser(
                id="target-user",
                username="target@example.com",
                role="user",
                scope=UserScope(kind="user", user_id="target-user", root=tmp_path / "target"),
            )
        )

    app = FastAPI()
    app.include_router(
        router_module.router,
        prefix="/api/v1/historical-migration",
        dependencies=[Depends(authenticated_user)],
    )
    return TestClient(app)


def test_authenticated_api_returns_zero_write_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = build_client(tmp_path, monkeypatch)
    sources = client.get("/api/v1/historical-migration/sources")
    assert sources.status_code == 200
    source = sources.json()[0]
    owner = next(item for item in source["owners"] if item["practice_attempt_count"] == 2)

    response = client.post(
        "/api/v1/historical-migration/dry-run",
        json={
            "source_id": source["id"],
            "legacy_owner_designation": owner["designation"],
            "practice_course_id": "crs_course",
            "flashcard_workspace_id": "crs_general",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["zero_write"] is True
    assert body["destinations"]["practice_course_id"] == "crs_course"
    assert body["destinations"]["flashcard_workspace_id"] == "crs_general"
    assert "target-user" not in response.text
    assert "target@example.com" not in response.text


def test_foreign_destination_is_indistinguishable_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = build_client(tmp_path, monkeypatch)
    source = client.get("/api/v1/historical-migration/sources").json()[0]
    owner = source["owners"][0]
    response = client.post(
        "/api/v1/historical-migration/dry-run",
        json={
            "source_id": source["id"],
            "legacy_owner_designation": owner["designation"],
            "practice_course_id": "crs_foreign",
        },
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Destination not found"}


def test_client_cannot_supply_a_filesystem_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = build_client(tmp_path, monkeypatch)
    source = client.get("/api/v1/historical-migration/sources").json()[0]
    response = client.post(
        "/api/v1/historical-migration/dry-run",
        json={
            "source_id": source["id"],
            "legacy_owner_designation": source["owners"][0]["designation"],
            "source_path": "/private/other-user.db",
        },
    )
    assert response.status_code == 422
