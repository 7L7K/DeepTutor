from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.courses.ingestion import _current_personal_user, run_source_operation


@pytest.mark.asyncio
async def test_revoked_owner_prevents_background_provider_and_course_commit(monkeypatch) -> None:
    called = {"provider": False}
    statuses: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "deeptutor.courses.ingestion._current_personal_user", lambda _owner: None
    )

    async def should_not_run(*_args, **_kwargs):
        called["provider"] = True

    monkeypatch.setattr(
        "deeptutor.api.routers.knowledge.run_initialization_task", should_not_run
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.TaskIDManager.get_instance",
        lambda: type(
            "Tasks",
            (),
            {
                "update_task_status": lambda _self, task_id, status, **_kwargs: statuses.append(
                    (task_id, status)
                )
            },
        )(),
    )
    await run_source_operation(
        {
            "owner_user_id": "u_revoked",
            "operation_id": "op_revoked",
            "initialize": True,
        }
    )
    assert called["provider"] is False
    assert statuses == [("op_revoked", "cancelled")]


@pytest.mark.asyncio
async def test_revocation_after_provider_work_still_prevents_course_commit(
    monkeypatch, tmp_path
) -> None:
    from deeptutor.multi_user.models import CurrentUser
    from deeptutor.multi_user.paths import UserScope

    user = CurrentUser(
        id="u_owner",
        username="owner",
        role="user",
        scope=UserScope(kind="user", user_id="u_owner", root=tmp_path),
    )
    identities = iter([user, None])
    called = {"provider": False, "repository": False}
    statuses: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "deeptutor.courses.ingestion._current_personal_user",
        lambda _owner: next(identities),
    )

    async def provider(*_args, **_kwargs):
        called["provider"] = True

    class ForbiddenRepository:
        def __init__(self, *_args, **_kwargs):
            called["repository"] = True

    monkeypatch.setattr(
        "deeptutor.api.routers.knowledge.run_initialization_task", provider
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.CourseRepository", ForbiddenRepository
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.TaskIDManager.get_instance",
        lambda: type(
            "Tasks",
            (),
            {
                "get_task_metadata": lambda _self, _task_id: {"status": "completed"},
                "update_task_status": lambda _self, task_id, status, **_kwargs: statuses.append(
                    (task_id, status)
                ),
            },
        )(),
    )

    await run_source_operation(
        {
            "owner_user_id": "u_owner",
            "operation_id": "op_revoked_after_provider",
            "initialize": True,
            "kb_name": "course_crs_one_src_one",
            "base_dir": "/tmp/not-used",
            "rag_provider": "llamaindex",
        }
    )

    assert called == {"provider": True, "repository": False}
    assert statuses == [("op_revoked_after_provider", "cancelled")]


def test_bootstrap_env_admin_is_revalidated_for_background_course_work(monkeypatch) -> None:
    monkeypatch.setattr("deeptutor.courses.ingestion.get_user_by_id", lambda _uid: None)
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.load_auth_settings",
        lambda: {"username": "bootstrap", "password_hash": "configured"},
    )

    user = _current_personal_user("env-admin")

    assert user is not None
    assert user.id == "env-admin"
    assert user.username == "bootstrap"
    assert user.role == "admin"


@pytest.mark.asyncio
async def test_success_is_published_only_after_course_source_commit(
    monkeypatch, tmp_path
) -> None:
    from deeptutor.multi_user.models import CurrentUser, UserScope

    events: list[str] = []
    user = CurrentUser(
        id="u_owner",
        username="owner",
        role="user",
        scope=UserScope(kind="user", user_id="u_owner", root=tmp_path),
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion._current_personal_user", lambda _owner: user
    )

    async def provider(*_args, **kwargs):
        assert kwargs["finalize_task"] is False
        events.append("provider")
        return True

    def build_exact_text_index(_kb_dir, _uploaded_paths, *, source_content_sha256):
        assert source_content_sha256 == "b" * 64
        events.append("exact-text-index")
        return True

    class Repository:
        def __init__(self, *_args, **_kwargs):
            pass

        def transition_source(self, *_args, **kwargs):
            assert kwargs["state"] == "ready"
            events.append("db:ready")

    class Tasks:
        def get_task_metadata(self, _task_id):
            return {"status": "running"}

        def update_task_status(self, _task_id, status, **_kwargs):
            events.append(f"status:{status}")

    class Stream:
        def emit_complete(self, _task_id, _message):
            events.append("event:complete")

        def emit_failed(self, _task_id, _message):
            events.append("event:failed")

    monkeypatch.setattr(
        "deeptutor.api.routers.knowledge.run_initialization_task", provider
    )
    monkeypatch.setattr(
        "deeptutor.courses.deterministic_provider.build_index",
        build_exact_text_index,
    )
    monkeypatch.setattr("deeptutor.courses.ingestion.CourseRepository", Repository)
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.get_personal_path_service",
        lambda _owner: SimpleNamespace(get_courses_db=lambda: tmp_path / "courses.db"),
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.TaskIDManager.get_instance", lambda: Tasks()
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.get_task_stream_manager", lambda: Stream()
    )

    await run_source_operation(
        {
            "owner_user_id": "u_owner",
            "course_id": "crs_one",
            "course_revision": 1,
            "course_write_epoch": 0,
            "source_id": "src_one",
            "source_revision": 1,
            "operation_id": "op_one",
            "kb_name": "course_crs_one_src_one",
            "base_dir": str(tmp_path),
            "uploaded_paths": [],
            "source_content_sha256": "b" * 64,
            "rag_provider": "local-test",
            "initialize": True,
        }
    )

    assert events == [
        "provider",
        "exact-text-index",
        "db:ready",
        "status:completed",
        "event:complete",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked_after_provider", [False, True])
async def test_owner_revocation_terminalizes_source_row_and_unblocks_archive(
    monkeypatch, tmp_path, revoked_after_provider: bool
) -> None:
    from deeptutor.courses.repository import CourseRepository
    from deeptutor.multi_user.models import CurrentUser, UserScope

    owner = "u_owner"
    db_path = tmp_path / "courses.db"
    repo = CourseRepository(db_path, owner)
    course = repo.create_course("Physics")
    source = repo.create_source(
        course.id,
        kind="notes",
        display_name="week-one.pdf",
        manifest=[],
        content_sha256="a" * 64,
        operation_id="op_revoked",
    )
    user = CurrentUser(
        id=owner,
        username="owner",
        role="user",
        scope=UserScope(kind="user", user_id=owner, root=tmp_path),
    )
    identities = iter([user, None]) if revoked_after_provider else iter([None])
    monkeypatch.setattr(
        "deeptutor.courses.ingestion._current_personal_user",
        lambda _owner: next(identities),
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.get_personal_path_service",
        lambda _owner: SimpleNamespace(get_courses_db=lambda: db_path),
    )

    async def provider(*_args, **_kwargs):
        return True

    monkeypatch.setattr(
        "deeptutor.api.routers.knowledge.run_initialization_task", provider
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.TaskIDManager.get_instance",
        lambda: SimpleNamespace(
            get_task_metadata=lambda _task_id: {"status": "running"},
            update_task_status=lambda *_args, **_kwargs: None,
        ),
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.get_task_stream_manager",
        lambda: SimpleNamespace(emit_failed=lambda *_args, **_kwargs: None),
    )

    await run_source_operation(
        {
            "owner_user_id": owner,
            "course_id": course.id,
            "course_revision": course.revision,
            "course_write_epoch": course.write_epoch,
            "source_id": source.id,
            "source_revision": source.revision,
            "operation_id": "op_revoked",
            "kb_name": "course_test",
            "base_dir": str(tmp_path),
            "uploaded_paths": [],
            "rag_provider": "local-test",
            "initialize": True,
        }
    )

    failed = repo.get_source(course.id, source.id)
    assert failed.state == "failed"
    assert repo.archive_course(course.id, course.revision).state == "archived"


@pytest.mark.asyncio
async def test_provider_exception_terminalizes_source_row(monkeypatch, tmp_path) -> None:
    from deeptutor.courses.repository import CourseRepository
    from deeptutor.multi_user.models import CurrentUser, UserScope

    owner = "u_owner"
    db_path = tmp_path / "courses.db"
    repo = CourseRepository(db_path, owner)
    course = repo.create_course("Physics")
    source = repo.create_source(
        course.id,
        kind="notes",
        display_name="week-one.pdf",
        manifest=[],
        content_sha256="a" * 64,
        operation_id="op_error",
    )
    user = CurrentUser(
        id=owner,
        username="owner",
        role="user",
        scope=UserScope(kind="user", user_id=owner, root=tmp_path),
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion._current_personal_user", lambda _owner: user
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.get_personal_path_service",
        lambda _owner: SimpleNamespace(get_courses_db=lambda: db_path),
    )

    async def provider(*_args, **_kwargs):
        raise RuntimeError("provider failed")

    monkeypatch.setattr(
        "deeptutor.api.routers.knowledge.run_initialization_task", provider
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.TaskIDManager.get_instance",
        lambda: SimpleNamespace(update_task_status=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.get_task_stream_manager",
        lambda: SimpleNamespace(emit_failed=lambda *_args, **_kwargs: None),
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        await run_source_operation(
            {
                "owner_user_id": owner,
                "course_id": course.id,
                "course_revision": course.revision,
                "course_write_epoch": course.write_epoch,
                "source_id": source.id,
                "source_revision": source.revision,
                "operation_id": "op_error",
                "kb_name": "course_test",
                "base_dir": str(tmp_path),
                "uploaded_paths": [],
                "rag_provider": "local-test",
                "initialize": True,
            }
        )

    assert repo.get_source(course.id, source.id).state == "failed"
    assert repo.archive_course(course.id, course.revision).state == "archived"


@pytest.mark.asyncio
async def test_index_written_before_stale_commit_never_becomes_course_authority(
    monkeypatch, tmp_path
) -> None:
    from deeptutor.courses.repository import CourseRepository
    from deeptutor.courses.service import (
        CourseService,
        CourseUnavailableError,
        resolve_course_turn_payload,
    )
    from deeptutor.multi_user.models import CurrentUser, UserScope

    owner = "u_owner"
    db_path = tmp_path / "courses.db"
    kb_root = tmp_path / "knowledge_bases"
    repo = CourseRepository(db_path, owner)
    course = repo.create_course("Physics")
    source = repo.create_source(
        course.id,
        kind="notes",
        display_name="week-one.txt",
        manifest=[],
        content_sha256="a" * 64,
        operation_id="op_stale_after_index",
    )
    user = CurrentUser(
        id=owner,
        username="owner",
        role="user",
        scope=UserScope(kind="user", user_id=owner, root=tmp_path),
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion._current_personal_user", lambda _owner: user
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.get_personal_path_service",
        lambda _owner: SimpleNamespace(get_courses_db=lambda: db_path),
    )

    async def provider(initializer, *_args, **_kwargs):
        initializer.kb_dir.mkdir(parents=True, exist_ok=True)
        (initializer.kb_dir / "provider-index.bin").write_bytes(b"complete-index")
        repo.update_course_title(course.id, "Physics renamed", course.revision)
        return True

    monkeypatch.setattr(
        "deeptutor.api.routers.knowledge.run_initialization_task", provider
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.TaskIDManager.get_instance",
        lambda: SimpleNamespace(
            get_task_metadata=lambda _task_id: {"status": "running"},
            update_task_status=lambda *_args, **_kwargs: None,
        ),
    )
    monkeypatch.setattr(
        "deeptutor.courses.ingestion.get_task_stream_manager",
        lambda: SimpleNamespace(emit_failed=lambda *_args, **_kwargs: None),
    )

    await run_source_operation(
        {
            "owner_user_id": owner,
            "course_id": course.id,
            "course_revision": course.revision,
            "course_write_epoch": course.write_epoch,
            "source_id": source.id,
            "source_revision": source.revision,
            "operation_id": "op_stale_after_index",
            "kb_name": "course_test_stale",
            "base_dir": str(kb_root),
            "uploaded_paths": [],
            "rag_provider": "llamaindex",
            "initialize": True,
        }
    )

    assert (kb_root / "course_test_stale" / "provider-index.bin").exists()
    assert repo.get_source(course.id, source.id).state == "failed"
    monkeypatch.setattr(
        "deeptutor.courses.service.get_current_course_service",
        lambda: CourseService(repo),
    )
    with pytest.raises(CourseUnavailableError, match="could not be prepared"):
        resolve_course_turn_payload(course.id, {"knowledge_bases": []})
