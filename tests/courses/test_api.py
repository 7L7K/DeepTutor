from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from io import BytesIO
import threading

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.datastructures import FormData, UploadFile


@pytest.fixture
def course_client(tmp_path, monkeypatch):
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import courses as course_router
    from deeptutor.courses import service as course_service
    from deeptutor.multi_user import grants, identity, paths
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
    monkeypatch.setattr(grants, "GRANTS_DIR", system_root / "grants")
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


def test_granted_learner_course_upload_keeps_cross_owner_no_oracle(
    course_client,
) -> None:
    from deeptutor.multi_user.grants import save_grant
    from deeptutor.multi_user.identity import get_user

    bob = get_user("bob")
    assert bob is not None
    save_grant(str(bob["id"]), {"course_source_uploads": True})
    foreign = course_client.post(
        "/api/v1/courses",
        headers=_auth("alice"),
        json={"title": "Private calculus"},
    ).json()

    response = course_client.post(
        f"/api/v1/courses/{foreign['id']}/sources",
        headers={**_auth("bob"), "Idempotency-Key": "foreign-source-no-oracle"},
        data={"kind": "notes", "display_name": "notes.txt"},
        files={"files": ("notes.txt", b"private", "text/plain")},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Course resource not found"


def test_general_study_api_is_lazy_private_permanent_and_has_no_mastery(
    course_client,
) -> None:
    """General Study cannot be repurposed as an academic Course aggregate."""

    first = course_client.post("/api/v1/courses/general-study", headers=_auth("bob"))
    second = course_client.post("/api/v1/courses/general-study", headers=_auth("bob"))
    alice = course_client.post("/api/v1/courses/general-study", headers=_auth("alice"))

    assert first.status_code == second.status_code == alice.status_code == 200
    general = first.json()
    assert second.json()["id"] == general["id"]
    assert general["id"] != alice.json()["id"]
    assert general["workspace_kind"] == "general_study"
    assert general["title"] == "General Study"
    assert general["state"] == "active"
    assert course_client.get(
        f"/api/v1/courses/{general['id']}", headers=_auth("alice")
    ).status_code == 404

    courses = course_client.get("/api/v1/courses", headers=_auth("bob")).json()["courses"]
    assert [course["id"] for course in courses if course["workspace_kind"] == "general_study"] == [
        general["id"]
    ]

    academic = course_client.post(
        "/api/v1/courses", headers=_auth("bob"), json={"title": "Biology"}
    )
    assert academic.status_code == 200
    assert academic.json()["workspace_kind"] == "academic_course"

    renamed = course_client.patch(
        f"/api/v1/courses/{general['id']}",
        headers=_auth("bob"),
        json={"title": "My notes", "expected_revision": general["revision"]},
    )
    archived = course_client.post(
        f"/api/v1/courses/{general['id']}/archive",
        headers=_auth("bob"),
        json={"expected_revision": general["revision"]},
    )
    assert renamed.status_code == archived.status_code == 409
    assert renamed.json()["detail"] == "General Study cannot be renamed"
    assert archived.json()["detail"] == "General Study cannot be archived"

    # Keep this isolated from TestClient's exception re-raise behavior: the
    # public contract is a safe conflict, never a server error or a new
    # learning-path record for General Study.
    with TestClient(course_client.app, raise_server_exceptions=False) as client:
        learning = client.get(
            f"/api/v1/courses/{general['id']}/learning", headers=_auth("bob")
        )
    assert learning.status_code == 409
    assert learning.json()["detail"] == "General Study does not have Course mastery"

    practice = course_client.post(
        f"/api/v1/courses/{general['id']}/practice",
        headers=_auth("bob"),
        json={
            "title": "Must not exist",
            "expected_course_write_epoch": general["write_epoch"],
        },
    )
    assert practice.status_code == 409
    assert practice.json()["detail"] == (
        "General Study does not support Course Practice or mastery"
    )

    learner_source = course_client.post(
        f"/api/v1/courses/{general['id']}/sources",
        headers={**_auth("bob"), "Idempotency-Key": "general-source-denied"},
        data={"kind": "notes", "display_name": "must-not-exist.txt"},
        files={"files": ("must-not-exist.txt", b"private", "text/plain")},
    )
    assert learner_source.status_code == 403
    assert learner_source.json()["detail"] == "Course material upload access required"

    admin_general = alice.json()
    admin_source = course_client.post(
        f"/api/v1/courses/{admin_general['id']}/sources",
        headers={**_auth("alice"), "Idempotency-Key": "general-source-admin-denied"},
        data={"kind": "notes", "display_name": "must-not-exist.txt"},
        files={"files": ("must-not-exist.txt", b"private", "text/plain")},
    )
    assert admin_source.status_code == 409
    assert admin_source.json()["detail"] == (
        "General Study cannot accept Course sources or Knowledge"
    )


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
        "flashcard_generation_reason": (
            "Flashcard generation is not enabled on this server"
        ),
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
        "flashcard_generation_reason": None,
        "grounded_generation_reason": None,
    }


def test_general_chat_flashcard_plan_is_private_bounded_and_not_course_grounded(
    course_client,
) -> None:
    from deeptutor.multi_user.identity import get_user
    from deeptutor.multi_user.paths import get_personal_path_service
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    bob = get_user("bob")
    assert bob is not None
    store = SQLiteSessionStore(
        db_path=get_personal_path_service(str(bob["id"])).get_chat_history_db()
    )

    async def seed_bob_general_chat() -> tuple[int, int]:
        await store.create_session(
            title="Linear equations",
            session_id="unified_general",
            course_id=None,
        )
        user_message_id = await store.add_message(
            "unified_general", "user", "Explain linear equations"
        )
        assistant_message_id = await store.add_message(
            "unified_general",
            "assistant",
            "Slope is the rate of change in y for a change in x.",
            parent_message_id=user_message_id,
        )
        return user_message_id, assistant_message_id

    user_message_id, assistant_message_id = asyncio.run(seed_bob_general_chat())
    response = course_client.post(
        "/api/v1/courses/general-study/learner-actions",
        headers=_auth("bob"),
        json={
            "action": "make_flashcards",
            "session_id": "unified_general",
            "assistant_message_id": assistant_message_id,
            "desired_count": 5,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["destination"] == "flashcards"
    assert payload["generation_brief"]["brief"]["desired_count"] == 5
    assert payload["generation_brief"]["source_snapshot"] == []
    origin = payload["generation_brief"]["origin"]
    assert origin["kind"] == "general_chat"
    assert origin["selected_message_ids"] == [
        user_message_id,
        assistant_message_id,
    ]
    assert len(origin["context_sha256"]) == 64
    assert origin["context_summary"] == "Linear Equations"
    assert origin["context_title"] == "Understanding Linear Equations"
    assert origin["context_topics"] == ["Linear Equations"]
    assert origin["session_scope"] == "personal"
    assert payload["generation_brief"]["brief"]["focus"] == (
        "Understand Linear Equations through Linear Equations."
    )

    alice_general = course_client.post(
        "/api/v1/courses/general-study", headers=_auth("alice")
    ).json()
    assert alice_general["id"] != payload["course_id"]

    destination = course_client.post(
        "/api/v1/courses",
        headers=_auth("bob"),
        json={"title": "Algebra"},
    ).json()
    saved_to_course = course_client.post(
        "/api/v1/courses/general-study/learner-actions",
        headers=_auth("bob"),
        json={
            "action": "make_flashcards",
            "session_id": "unified_general",
            "assistant_message_id": assistant_message_id,
            "desired_count": 3,
            "destination_course_id": destination["id"],
        },
    )
    assert saved_to_course.status_code == 200
    course_payload = saved_to_course.json()
    assert course_payload["course_id"] == destination["id"]
    assert course_payload["generation_brief"]["source_snapshot"] == []
    assert course_payload["generation_brief"]["objective_ids"] == []
    assert course_payload["generation_brief"]["origin"]["kind"] == "general_chat"

    foreign_destination = course_client.post(
        "/api/v1/courses/general-study/learner-actions",
        headers=_auth("alice"),
        json={
            "action": "make_flashcards",
            "session_id": "unified_general",
            "assistant_message_id": assistant_message_id,
            "destination_course_id": destination["id"],
        },
    )
    # Alice does not own Bob's session or Course; neither identifier is exposed.
    assert foreign_destination.status_code == 404


def test_general_chat_flashcard_plan_resolves_admin_chat_without_sharing_courses(
    course_client,
) -> None:
    from deeptutor.multi_user.paths import get_admin_path_service
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    store = SQLiteSessionStore(
        db_path=get_admin_path_service().get_chat_history_db()
    )

    async def seed_admin_general_chat() -> tuple[int, int]:
        await store.create_session(
            title="Cellular respiration",
            session_id="unified_admin_general",
            course_id=None,
        )
        user_message_id = await store.add_message(
            "unified_admin_general",
            "user",
            "Explain how mitochondria make usable cellular energy.",
        )
        assistant_message_id = await store.add_message(
            "unified_admin_general",
            "assistant",
            (
                "Mitochondria use cellular respiration to convert energy stored "
                "in nutrients into ATP, a form cells can use."
            ),
            parent_message_id=user_message_id,
        )
        return user_message_id, assistant_message_id

    user_message_id, assistant_message_id = asyncio.run(seed_admin_general_chat())
    response = course_client.post(
        "/api/v1/courses/general-study/learner-actions",
        headers=_auth("alice"),
        json={
            "action": "make_flashcards",
            "session_id": "unified_admin_general",
            "assistant_message_id": assistant_message_id,
            "desired_count": 3,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["generation_brief"]["origin"]["session_scope"] == "admin"
    assert payload["generation_brief"]["origin"]["selected_message_ids"] == [
        user_message_id,
        assistant_message_id,
    ]
    assert payload["generation_brief"]["source_snapshot"] == []

    # Bob's personal request cannot resolve the administrator's generic Chat.
    foreign = course_client.post(
        "/api/v1/courses/general-study/learner-actions",
        headers=_auth("bob"),
        json={
            "action": "make_flashcards",
            "session_id": "unified_admin_general",
            "assistant_message_id": assistant_message_id,
        },
    )
    assert foreign.status_code == 404


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
        "/api/v1/courses", headers=_auth("alice"), json={"title": "Writing"}
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
        headers={**_auth("alice"), "Idempotency-Key": "test-source-request-1"},
        files={"files": ("notes.txt", b"hello", "text/plain")},
        data={"kind": "notes", "display_name": "notes.txt"},
    )
    assert response.status_code == 202, response.text
    assert response.json()["state"] == "processing"
    assert seen["course_id"] == created["id"]


@pytest.mark.asyncio
async def test_course_source_background_failure_releases_user_and_global_permits(
    monkeypatch,
) -> None:
    from deeptutor.api.routers.courses import _run_course_source_background
    from deeptutor.services.sandbox.quota import UserExecQuota

    user_quota = UserExecQuota(max_concurrent=1, max_per_minute=6)
    global_quota = UserExecQuota(max_concurrent=1, max_per_minute=6)
    stack = AsyncExitStack()
    await stack.enter_async_context(await user_quota.acquire("user-one"))
    await stack.enter_async_context(await global_quota.acquire("global"))

    async def fail(_task):
        raise RuntimeError("background failed")

    monkeypatch.setattr(
        "deeptutor.courses.ingestion.run_source_operation",
        fail,
    )
    with pytest.raises(RuntimeError, match="background failed"):
        await _run_course_source_background({"operation_id": "op_one"}, stack)

    async with await user_quota.acquire("user-one"):
        async with await global_quota.acquire("global"):
            pass


class _CourseSourceFormContext:
    def __init__(self, form: FormData) -> None:
        self.form = form

    async def __aenter__(self) -> FormData:
        return self.form

    async def __aexit__(self, *_exc: object) -> None:
        await self.form.close()


class _CourseSourceRequest:
    def __init__(self, form: FormData) -> None:
        self.form_data = form

    def form(self, **_limits: int) -> _CourseSourceFormContext:
        return _CourseSourceFormContext(self.form_data)


@pytest.mark.asyncio
async def test_course_source_intake_cancellation_releases_both_permits(
    monkeypatch,
) -> None:
    from deeptutor.api.routers import courses as course_router
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.sandbox.quota import UserExecQuota

    user_quota = UserExecQuota(max_concurrent=1, max_per_minute=6)
    global_quota = UserExecQuota(max_concurrent=1, max_per_minute=6)
    monkeypatch.setattr(course_router, "_course_source_user_quota", user_quota)
    monkeypatch.setattr(course_router, "_course_source_global_quota", global_quota)
    entered = asyncio.Event()

    class BlockingRequest:
        def form(self, **_limits: int):
            class Context:
                async def __aenter__(self):
                    entered.set()
                    await asyncio.Event().wait()

                async def __aexit__(self, *_exc: object) -> None:
                    return None

            return Context()

    principal = TokenPayload("learner", "user", "user-one")
    intake = asyncio.create_task(
        course_router.create_course_source(
            "crs_one",
            BlockingRequest(),
            principal,
            "course-source-cancel-intake",
        )
    )
    await entered.wait()
    intake.cancel()
    with pytest.raises(asyncio.CancelledError):
        await intake

    async with await user_quota.acquire("user-one"):
        async with await global_quota.acquire("course-source-global"):
            pass


@pytest.mark.asyncio
async def test_course_source_prepare_cancellation_drains_and_terminalizes_staging(
    monkeypatch,
) -> None:
    from deeptutor.api.routers import courses as course_router
    from deeptutor.courses.models import CourseSource
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.sandbox.quota import UserExecQuota

    user_quota = UserExecQuota(max_concurrent=1, max_per_minute=6)
    global_quota = UserExecQuota(max_concurrent=1, max_per_minute=6)
    monkeypatch.setattr(course_router, "_course_source_user_quota", user_quota)
    monkeypatch.setattr(course_router, "_course_source_global_quota", global_quota)
    started = threading.Event()
    release = threading.Event()
    terminalized: list[tuple[dict, str]] = []
    staged = {"operation_id": "course_source_cancelled_prepare"}

    def prepare(**kwargs):
        started.set()
        assert release.wait(timeout=5)
        return (
            CourseSource(
                id="src_one",
                course_id=kwargs["course_id"],
                kind=kwargs["kind"],
                display_name=kwargs["display_name"],
                manifest=[],
                content_sha256="a" * 64,
                operation_id=staged["operation_id"],
                created_at=1,
                updated_at=1,
            ),
            staged,
        )

    async def cancel(task, message):
        terminalized.append((task, message))

    monkeypatch.setattr(
        "deeptutor.courses.ingestion.prepare_source_upload",
        prepare,
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.cancel_source_operation",
        cancel,
    )
    form = FormData(
        [
            ("files", UploadFile(BytesIO(b"notes"), filename="notes.txt")),
            ("display_name", "notes.txt"),
        ]
    )
    principal = TokenPayload("learner", "user", "user-one")
    intake = asyncio.create_task(
        course_router.create_course_source(
            "crs_one",
            _CourseSourceRequest(form),
            principal,
            "course-source-cancel-prepare",
        )
    )
    assert await asyncio.to_thread(started.wait, 2)
    intake.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await intake

    assert terminalized == [(staged, "Course source request was cancelled")]
    async with await user_quota.acquire("user-one"):
        async with await global_quota.acquire("course-source-global"):
            pass


@pytest.mark.asyncio
async def test_course_source_dispatch_failure_terminalizes_and_releases_permits(
    monkeypatch,
) -> None:
    from deeptutor.api.routers import courses as course_router
    from deeptutor.courses.models import CourseSource
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.sandbox.quota import UserExecQuota

    user_quota = UserExecQuota(max_concurrent=1, max_per_minute=6)
    global_quota = UserExecQuota(max_concurrent=1, max_per_minute=6)
    monkeypatch.setattr(course_router, "_course_source_user_quota", user_quota)
    monkeypatch.setattr(course_router, "_course_source_global_quota", global_quota)
    staged = {"operation_id": "course_source_dispatch_failed"}
    terminalized: list[tuple[dict, str]] = []

    def prepare(**kwargs):
        return (
            CourseSource(
                id="src_one",
                course_id=kwargs["course_id"],
                kind=kwargs["kind"],
                display_name=kwargs["display_name"],
                manifest=[],
                content_sha256="a" * 64,
                operation_id=staged["operation_id"],
                created_at=1,
                updated_at=1,
            ),
            staged,
        )

    async def cancel(task, message):
        terminalized.append((task, message))

    monkeypatch.setattr(
        "deeptutor.courses.ingestion.prepare_source_upload",
        prepare,
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.cancel_source_operation",
        cancel,
    )
    monkeypatch.setattr(
        course_router,
        "_dispatch_course_source_background",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("dispatch unavailable")
        ),
    )
    form = FormData(
        [
            ("files", UploadFile(BytesIO(b"notes"), filename="notes.txt")),
            ("display_name", "notes.txt"),
        ]
    )
    principal = TokenPayload("learner", "user", "user-one")

    with pytest.raises(RuntimeError, match="dispatch unavailable"):
        await course_router.create_course_source(
            "crs_one",
            _CourseSourceRequest(form),
            principal,
            "course-source-dispatch-failed",
        )

    assert terminalized == [
        (staged, "Course source processing could not be started")
    ]
    async with await user_quota.acquire("user-one"):
        async with await global_quota.acquire("course-source-global"):
            pass


@pytest.mark.asyncio
async def test_owned_course_source_task_releases_permits_when_cancelled(
    monkeypatch,
) -> None:
    from deeptutor.api.routers import courses as course_router
    from deeptutor.services.sandbox.quota import UserExecQuota

    user_quota = UserExecQuota(max_concurrent=1, max_per_minute=6)
    global_quota = UserExecQuota(max_concurrent=1, max_per_minute=6)
    stack = AsyncExitStack()
    await stack.enter_async_context(await user_quota.acquire("user-one"))
    await stack.enter_async_context(await global_quota.acquire("global"))
    started = asyncio.Event()

    async def wait_forever(_task):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "deeptutor.courses.ingestion.run_source_operation",
        wait_forever,
    )
    background = course_router._dispatch_course_source_background(
        {"operation_id": "op_owned"},
        stack,
    )
    await started.wait()
    assert background in course_router._course_source_background_tasks
    await course_router.shutdown_course_source_background_tasks()
    await asyncio.sleep(0)

    assert background.cancelled()
    assert background not in course_router._course_source_background_tasks
    async with await user_quota.acquire("user-one"):
        async with await global_quota.acquire("global"):
            pass


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
