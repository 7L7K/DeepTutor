from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def course_client(tmp_path, monkeypatch):
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import courses as course_router
    from deeptutor.courses import service as course_service
    from deeptutor.multi_user import identity, paths
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.auth import TokenPayload

    admin_root = (tmp_path / "data").resolve()
    users_root = admin_root / "users"
    system_root = admin_root / "system"
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "USERS_ROOT", users_root)
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "missing-users.json")
    monkeypatch.setattr(identity, "LEGACY_SECRET_FILE", tmp_path / "missing-secret")

    alice = save_user("alice", "$2b$12$placeholder", role="admin")
    bob = save_user("bob", "$2b$12$placeholder", role="user")
    other_admin = save_user("carol", "$2b$12$placeholder", role="admin")
    tokens = {
        "alice": TokenPayload("alice", "admin", alice["id"]),
        "bob": TokenPayload("bob", "user", bob["id"]),
        "carol": TokenPayload("carol", "admin", other_admin["id"]),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    monkeypatch.setattr(course_service, "is_pocketbase_enabled", lambda: False)
    course_service._repository_for.cache_clear()

    app = FastAPI()
    auth_dep = [Depends(auth_router.require_auth)]
    app.include_router(course_router.router, prefix="/api/v1/courses", dependencies=auth_dep)
    return TestClient(app)


def _auth(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {name}"}


def test_course_api_isolates_users_and_admin_personal_profiles(course_client) -> None:
    alice = course_client.post(
        "/api/v1/courses", headers=_auth("alice"), json={"title": "Calculus"}
    )
    bob = course_client.post(
        "/api/v1/courses", headers=_auth("bob"), json={"title": "Calculus"}
    )
    carol = course_client.post(
        "/api/v1/courses", headers=_auth("carol"), json={"title": "Calculus"}
    )
    assert alice.status_code == bob.status_code == carol.status_code == 200
    assert len({alice.json()["id"], bob.json()["id"], carol.json()["id"]}) == 3

    foreign = course_client.get(
        f"/api/v1/courses/{alice.json()['id']}", headers=_auth("bob")
    )
    assert foreign.status_code == 404
    assert [item["id"] for item in course_client.get(
        "/api/v1/courses", headers=_auth("alice")
    ).json()["courses"]] == [alice.json()["id"]]
    assert [item["id"] for item in course_client.get(
        "/api/v1/courses", headers=_auth("carol")
    ).json()["courses"]] == [carol.json()["id"]]


def test_course_api_reports_generation_capability_truthfully(
    course_client, monkeypatch
) -> None:
    monkeypatch.delenv("TEEECHR_TEST_DETERMINISTIC_PROVIDER", raising=False)
    unavailable = course_client.get("/api/v1/courses", headers=_auth("bob"))
    assert unavailable.status_code == 200
    assert unavailable.json()["capabilities"] == {
        "grounded_generation": False,
        "practice_generation": False,
        "flashcard_generation": False,
        "grounded_generation_reason": (
            "Grounded generation is not enabled on this server"
        ),
    }

    monkeypatch.setenv("TEEECHR_TEST_DETERMINISTIC_PROVIDER", "1")
    deterministic = course_client.get("/api/v1/courses", headers=_auth("bob"))
    assert deterministic.status_code == 200
    assert deterministic.json()["capabilities"] == {
        "grounded_generation": True,
        "practice_generation": True,
        "flashcard_generation": True,
        "grounded_generation_reason": None,
    }


def test_course_api_revision_archive_restore_and_no_delete(course_client) -> None:
    created = course_client.post(
        "/api/v1/courses", headers=_auth("bob"), json={"title": "Physics"}
    ).json()
    renamed = course_client.patch(
        f"/api/v1/courses/{created['id']}",
        headers=_auth("bob"),
        json={"title": "Physics I", "expected_revision": created["revision"]},
    )
    assert renamed.status_code == 200
    assert renamed.json()["revision"] == 2

    stale = course_client.patch(
        f"/api/v1/courses/{created['id']}",
        headers=_auth("bob"),
        json={"title": "Stale", "expected_revision": 1},
    )
    assert stale.status_code == 409

    archived = course_client.post(
        f"/api/v1/courses/{created['id']}/archive",
        headers=_auth("bob"),
        json={"expected_revision": 2},
    )
    assert archived.status_code == 200
    assert archived.json()["state"] == "archived"
    restored = course_client.post(
        f"/api/v1/courses/{created['id']}/restore",
        headers=_auth("bob"),
        json={"expected_revision": 3},
    )
    assert restored.status_code == 200
    assert restored.json()["state"] == "active"
    assert course_client.delete(
        f"/api/v1/courses/{created['id']}", headers=_auth("bob")
    ).status_code == 405


def test_course_api_explicitly_rejects_pocketbase(course_client, monkeypatch) -> None:
    from deeptutor.courses import service as course_service

    monkeypatch.setattr(course_service, "is_pocketbase_enabled", lambda: True)
    response = course_client.get("/api/v1/courses", headers=_auth("bob"))
    assert response.status_code == 503
    assert "local JSON/SQLite" in response.json()["detail"]


def test_course_learning_is_explicit_private_and_resettable(course_client) -> None:
    created = course_client.post(
        "/api/v1/courses", headers=_auth("bob"), json={"title": "Biology"}
    ).json()
    module = {
        "id": "bio_m1",
        "name": "Cells",
        "order": 0,
        "knowledge_points": [
            {"id": "bio_kp1", "name": "Explain ATP", "type": "concept", "module_id": "bio_m1"}
        ],
    }
    initialized = course_client.post(
        f"/api/v1/courses/{created['id']}/learning/init",
        headers=_auth("bob"),
        json={"modules": [module]},
    )
    assert initialized.status_code == 200
    assert initialized.json()["learning_path_id"] == f"lp_{created['id']}"

    learning = course_client.get(
        f"/api/v1/courses/{created['id']}/learning", headers=_auth("bob")
    )
    assert learning.status_code == 200
    assert learning.json()["initialized"] is True
    assert learning.json()["progress"]["modules"][0]["name"] == "Cells"
    assert course_client.get(
        f"/api/v1/courses/{created['id']}/learning", headers=_auth("alice")
    ).status_code == 404

    reset = course_client.post(
        f"/api/v1/courses/{created['id']}/learning/reset",
        headers=_auth("bob"),
        json={},
    )
    assert reset.status_code == 200
    after = course_client.get(
        f"/api/v1/courses/{created['id']}/learning", headers=_auth("bob")
    ).json()["progress"]
    assert after["modules"][0]["name"] == "Cells"
    assert after["mastery_levels"] == {}


def test_course_learning_reset_rejects_authoritative_grading_history(
    course_client, monkeypatch
) -> None:
    from deeptutor.courses.grading_repository import CourseGradingRepository

    created = course_client.post(
        "/api/v1/courses", headers=_auth("bob"), json={"title": "Biology"}
    ).json()
    module = {
        "id": "bio_m1",
        "name": "Cells",
        "order": 0,
        "knowledge_points": [
            {
                "id": "bio_kp1",
                "name": "Explain ATP",
                "type": "concept",
                "module_id": "bio_m1",
            }
        ],
    }
    assert course_client.post(
        f"/api/v1/courses/{created['id']}/learning/init",
        headers=_auth("bob"),
        json={"modules": [module]},
    ).status_code == 200
    monkeypatch.setattr(
        CourseGradingRepository,
        "has_course_evidence",
        lambda self, course_id: course_id == created["id"],
    )

    response = course_client.post(
        f"/api/v1/courses/{created['id']}/learning/reset",
        headers=_auth("bob"),
        json={},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Course learning with grading evidence cannot be reset"
    )


def test_course_learning_reinit_rejects_plan_change_with_grading_history_but_allows_identity(
    course_client, monkeypatch
) -> None:
    from deeptutor.api.routers import courses as course_router
    from deeptutor.courses.grading_repository import CourseGradingRepository

    created = course_client.post(
        "/api/v1/courses", headers=_auth("bob"), json={"title": "Biology"}
    ).json()
    module = {
        "id": "bio_m1",
        "name": "Cells",
        "order": 0,
        "knowledge_points": [
            {
                "id": "bio_kp1",
                "name": "Explain ATP",
                "type": "concept",
                "module_id": "bio_m1",
            }
        ],
    }
    endpoint = f"/api/v1/courses/{created['id']}/learning/init"
    assert course_client.post(
        endpoint,
        headers=_auth("bob"),
        json={"modules": [module]},
    ).status_code == 200
    monkeypatch.setattr(
        CourseGradingRepository,
        "has_course_evidence",
        lambda self, course_id: course_id == created["id"],
    )
    cancellations: list[tuple[str, str | None]] = []

    async def record_cancellation(course_id: str, session_id: str | None) -> None:
        cancellations.append((course_id, session_id))

    monkeypatch.setattr(
        course_router,
        "_cancel_owned_course_session",
        record_cancellation,
    )

    identity_replay = course_client.post(
        endpoint,
        headers=_auth("bob"),
        json={"modules": [module]},
    )
    assert identity_replay.status_code == 200
    assert cancellations == []

    changed = {
        **module,
        "knowledge_points": [
            {
                "id": "bio_kp2",
                "name": "Explain DNA",
                "type": "concept",
                "module_id": "bio_m1",
            }
        ],
    }
    rejected = course_client.post(
        endpoint,
        headers=_auth("bob"),
        json={"modules": [changed]},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == (
        "Course learning plan with grading evidence cannot be replaced"
    )
    assert cancellations == []
    progress = course_client.get(
        f"/api/v1/courses/{created['id']}/learning",
        headers=_auth("bob"),
    ).json()["progress"]
    assert [item["id"] for item in progress["modules"][0]["knowledge_points"]] == [
        "bio_kp1"
    ]


def test_course_source_api_accepts_only_prepared_owned_operation(
    course_client, monkeypatch
) -> None:
    from deeptutor.courses import ingestion
    from deeptutor.courses.models import CourseSource

    created = course_client.post(
        "/api/v1/courses", headers=_auth("bob"), json={"title": "Writing"}
    ).json()
    seen = {}

    def fake_prepare(**kwargs):
        seen.update(kwargs)
        return (
            CourseSource(
                id="src_test",
                course_id=kwargs["course_id"],
                kind=kwargs["kind"],
                display_name=kwargs["display_name"],
                manifest=[],
                content_sha256="a" * 64,
                operation_id="op_test",
                created_at=1,
                updated_at=1,
            ),
            {"operation_id": "op_test"},
        )

    async def fake_run(_task):
        return None

    monkeypatch.setattr(ingestion, "prepare_source_upload", fake_prepare)
    monkeypatch.setattr(ingestion, "run_source_operation", fake_run)
    response = course_client.post(
        f"/api/v1/courses/{created['id']}/sources",
        headers={**_auth("bob"), "Idempotency-Key": "test-source-request-1"},
        files={"files": ("notes.txt", b"hello", "text/plain")},
        data={"kind": "notes", "display_name": "notes.txt"},
    )
    assert response.status_code == 202, response.text
    assert response.json()["state"] == "processing"
    assert seen["course_id"] == created["id"]


@pytest.mark.asyncio
async def test_learning_change_without_session_rejects_any_active_course_turn(
    monkeypatch,
) -> None:
    from deeptutor.api.routers import courses as course_router
    from deeptutor.courses.repository import CourseConflictError

    class Store:
        async def has_active_course_turn(self, course_id: str) -> bool:
            assert course_id == "crs_one"
            return True

    class Runtime:
        async def recover_orphan_course_turns(self, _course_id: str) -> int:
            return 0

    monkeypatch.setattr(
        "deeptutor.services.session.get_personal_sqlite_session_store",
        lambda: Store(),
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_turn_runtime_manager",
        lambda **_kwargs: Runtime(),
    )
    with pytest.raises(CourseConflictError, match="turn is active"):
        await course_router._cancel_owned_course_session("crs_one", None)


@pytest.mark.asyncio
async def test_learning_cancellation_uses_owned_session_and_real_turn_id(monkeypatch) -> None:
    from deeptutor.api.routers import courses as course_router

    cancelled: list[str] = []

    class Store:
        async def has_active_course_turn(self, _course_id: str) -> bool:
            return False

        async def get_session(self, session_id: str):
            assert session_id == "session_one"
            return {"id": session_id, "course_id": "crs_one"}

        async def get_active_turn(self, session_id: str):
            assert session_id == "session_one"
            return {"id": "turn_one"}

    class Runtime:
        async def recover_orphan_course_turns(self, _course_id: str) -> int:
            return 0

        async def cancel_turn(self, turn_id: str) -> bool:
            cancelled.append(turn_id)
            return True

    monkeypatch.setattr(
        "deeptutor.services.session.get_personal_sqlite_session_store",
        lambda: Store(),
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_turn_runtime_manager",
        lambda **_kwargs: Runtime(),
    )

    await course_router._cancel_owned_course_session("crs_one", "session_one")

    assert cancelled == ["turn_one"]


@pytest.mark.asyncio
async def test_learning_change_rechecks_for_other_active_course_sessions(monkeypatch) -> None:
    from deeptutor.api.routers import courses as course_router
    from deeptutor.courses.repository import CourseConflictError

    class Store:
        async def get_session(self, _session_id: str):
            return {"id": "idle_session", "course_id": "crs_one"}

        async def get_active_turn(self, _session_id: str):
            return None

        async def has_active_course_turn(self, _course_id: str) -> bool:
            return True

    class Runtime:
        async def recover_orphan_course_turns(self, _course_id: str) -> int:
            return 0

    monkeypatch.setattr(
        "deeptutor.services.session.get_personal_sqlite_session_store",
        lambda: Store(),
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_turn_runtime_manager",
        lambda **_kwargs: Runtime(),
    )

    with pytest.raises(CourseConflictError, match="turn is active"):
        await course_router._cancel_owned_course_session("crs_one", "idle_session")
