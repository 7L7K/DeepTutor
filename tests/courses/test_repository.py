from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import stat
from types import SimpleNamespace

import pytest

from deeptutor.courses.practice_repository import CoursePracticeRepository
from deeptutor.courses.repository import (
    CourseConflictError,
    CourseNotFoundError,
    CourseRepository,
)
from deeptutor.courses.service import CourseService, course_operation_lock


def test_course_lifecycle_is_persistent_and_revision_guarded(tmp_path) -> None:
    db_path = tmp_path / "courses.db"
    repo = CourseRepository(db_path, "u_alice")
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o600

    created = repo.create_course("  General   Biology  ")
    assert created.id.startswith("crs_")
    assert created.title == "General Biology"
    assert created.owner_user_id == "u_alice"
    assert created.revision == 1

    renamed = repo.update_course_title(created.id, "Biology I", expected_revision=1)
    assert renamed.title == "Biology I"
    assert renamed.revision == 2
    with pytest.raises(CourseConflictError, match="stale"):
        repo.update_course_title(created.id, "Lost update", expected_revision=1)

    archived = repo.archive_course(created.id, expected_revision=2)
    assert archived.state == "archived"
    assert archived.write_epoch == 2
    restored = repo.restore_course(created.id, expected_revision=3)
    assert restored.state == "active"
    assert restored.write_epoch == 3

    reopened = CourseRepository(db_path, "u_alice")
    assert reopened.get_course(created.id) == restored


def test_course_term_is_projected_only_from_one_unambiguous_mapping(tmp_path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Biology")
    assert course.term is None

    with repo._connect() as conn:
        conn.execute(
            """INSERT INTO blueway_connections
               (id, owner_user_id, external_subject, state, scope_version,
                revision, grant_generation, credential_ref, credential_status,
                created_at, updated_at)
               VALUES ('conn_one', 'u_alice', 'subject_one', 'active', 'v1',
                       1, 1, NULL, 'healthy', 1, 1)"""
        )
        conn.execute(
            """INSERT INTO blueway_course_maps
               (connection_id, external_course_id, external_term_id, course_id,
                remote_title, remote_state, remote_hash, first_seen_snapshot_id,
                last_seen_snapshot_id, created_at, updated_at)
               VALUES ('conn_one', 'bio', 'fall-2026', ?, 'Biology', 'active',
                       'a', 'snap_one', 'snap_one', 1, 1)""",
            (course.id,),
        )

    assert repo.get_course(course.id).term == "fall-2026"

    with repo._connect() as conn:
        conn.execute(
            """INSERT INTO blueway_connections
               (id, owner_user_id, external_subject, state, scope_version,
                revision, grant_generation, credential_ref, credential_status,
                created_at, updated_at)
               VALUES ('conn_two', 'u_alice', 'subject_two', 'disconnected', 'v1',
                       1, 1, NULL, 'healthy', 1, 1)"""
        )
        conn.execute(
            """INSERT INTO blueway_course_maps
               (connection_id, external_course_id, external_term_id, course_id,
                remote_title, remote_state, remote_hash, first_seen_snapshot_id,
                last_seen_snapshot_id, created_at, updated_at)
               VALUES ('conn_two', 'bio', 'spring-2027', ?, 'Biology', 'active',
                       'b', 'snap_two', 'snap_two', 1, 1)""",
            (course.id,),
        )

    assert repo.get_course(course.id).term is None


def test_course_sources_are_parent_bound_and_archive_fences_processing(tmp_path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("History")
    source = repo.create_source(
        course.id,
        kind="syllabus",
        display_name="Syllabus.pdf",
        manifest=[{"path": "Syllabus.pdf", "size": 10, "sha256": "a" * 64}],
        content_sha256="a" * 64,
    )
    assert source.state == "processing"
    assert source.operation_id and source.operation_id.startswith("op_")

    with pytest.raises(CourseConflictError, match="active source"):
        repo.archive_course(course.id, expected_revision=course.revision)

    ready = repo.transition_source(
        course.id,
        source.id,
        operation_id=source.operation_id,
        expected_source_revision=source.revision,
        expected_course_revision=course.revision,
        expected_write_epoch=course.write_epoch,
        state="ready",
    )
    assert ready.state == "ready"
    assert ready.revision == 2

    archived_source = repo.archive_source(course.id, source.id, expected_revision=2)
    assert archived_source.state == "archived"
    archived_course = repo.archive_course(course.id, expected_revision=course.revision)
    assert archived_course.state == "archived"
    with pytest.raises(CourseConflictError, match="archived"):
        repo.update_course_title(
            course.id, "History II", expected_revision=archived_course.revision
        )
    with pytest.raises(CourseConflictError, match="Archived"):
        repo.archive_source(
            course.id, source.id, expected_revision=archived_source.revision
        )


def test_source_idempotency_key_returns_one_owned_source_identity(tmp_path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Chemistry")
    source = repo.create_source(
        course.id,
        kind="document",
        display_name="notes.txt",
        manifest=[],
        content_sha256="0" * 64,
        operation_id="op_one",
        idempotency_key="upload-request-one",
    )

    assert repo.get_source_by_idempotency_key(course.id, "upload-request-one") == source
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_source(
            course.id,
            kind="document",
            display_name="notes.txt",
            manifest=[],
            content_sha256="0" * 64,
            operation_id="op_two",
            idempotency_key="upload-request-one",
        )


def test_restart_reconciliation_immediately_fails_orphan_source(
    tmp_path, monkeypatch
) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Physics")
    source = repo.create_source(
        course.id,
        kind="document",
        display_name="notes.txt",
        manifest=[],
        content_sha256="0" * 64,
        operation_id="op_lost_on_restart",
    )
    monkeypatch.setattr(
        "deeptutor.api.utils.task_id_manager.TaskIDManager.get_instance",
        lambda: SimpleNamespace(get_task_metadata=lambda _operation: None),
    )

    reconciled = CourseService(repo).reconcile_source_for_progress(course.id, source.id)

    assert reconciled.state == "failed"


def test_progress_reconciliation_preserves_another_live_source_in_same_course(
    tmp_path, monkeypatch
) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Physics")
    live = repo.create_source(
        course.id,
        kind="document",
        display_name="live.txt",
        manifest=[],
        content_sha256="a" * 64,
        operation_id="op_live",
    )
    orphan = repo.create_source(
        course.id,
        kind="document",
        display_name="orphan.txt",
        manifest=[],
        content_sha256="b" * 64,
        operation_id="op_orphan",
    )
    monkeypatch.setattr(
        "deeptutor.api.utils.task_id_manager.TaskIDManager.get_instance",
        lambda: SimpleNamespace(
            get_task_metadata=lambda operation: (
                {"status": "running"} if operation == "op_live" else None
            )
        ),
    )

    reconciled = CourseService(repo).reconcile_source_for_progress(
        course.id, orphan.id
    )

    assert reconciled.state == "failed"
    assert repo.get_source(course.id, live.id).state == "processing"


def test_reconciliation_snapshot_does_not_fail_source_created_during_update(
    tmp_path, monkeypatch
) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Physics")
    orphan = repo.create_source(
        course.id,
        kind="document",
        display_name="orphan.txt",
        manifest=[],
        content_sha256="a" * 64,
        operation_id="op_orphan",
    )
    statuses: dict[str, dict[str, str] | None] = {"op_orphan": None}
    monkeypatch.setattr(
        "deeptutor.api.utils.task_id_manager.TaskIDManager.get_instance",
        lambda: SimpleNamespace(get_task_metadata=lambda operation: statuses.get(operation)),
    )
    original_reconcile = repo.reconcile_abandoned_sources
    created = []

    def insert_live_source_before_update(**kwargs):
        live = repo.create_source(
            course.id,
            kind="document",
            display_name="live.txt",
            manifest=[],
            content_sha256="b" * 64,
            operation_id="op_live",
        )
        statuses["op_live"] = {"status": "running"}
        created.append(live)
        return original_reconcile(**kwargs)

    monkeypatch.setattr(repo, "reconcile_abandoned_sources", insert_live_source_before_update)

    reconciled = CourseService(repo).reconcile_source_for_progress(
        course.id, orphan.id
    )

    assert reconciled.state == "failed"
    assert len(created) == 1
    assert repo.get_source(course.id, created[0].id).state == "processing"


def test_source_completion_rejects_stale_course_revision(tmp_path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Chemistry")
    source = repo.create_source(
        course.id,
        kind="notes",
        display_name="Lab notes",
        manifest=[],
        content_sha256="b" * 64,
    )

    repo.update_course_title(course.id, "Chemistry Lab", expected_revision=course.revision)
    with pytest.raises(CourseConflictError, match="stale"):
        repo.transition_source(
            course.id,
            source.id,
            operation_id=source.operation_id or "",
            expected_source_revision=source.revision,
            expected_course_revision=course.revision,
            expected_write_epoch=course.write_epoch,
            state="ready",
        )


def test_same_titles_in_separate_owner_databases_never_collide(tmp_path) -> None:
    alice = CourseRepository(tmp_path / "alice" / "courses.db", "u_alice")
    bob = CourseRepository(tmp_path / "bob" / "courses.db", "u_bob")
    a = alice.create_course("Calculus")
    b = bob.create_course("Calculus")

    assert a.id != b.id
    assert alice.list_courses()[0].owner_user_id == "u_alice"
    assert bob.list_courses()[0].owner_user_id == "u_bob"


@pytest.mark.asyncio
async def test_general_study_is_lazy_singleton_private_and_permanent(tmp_path) -> None:
    """General Study is one durable non-academic workspace per owner."""

    db_path = tmp_path / "courses.db"
    alice = CourseRepository(db_path, "u_alice")
    bob = CourseRepository(db_path, "u_bob")

    assert alice.list_courses() == []
    first = CourseService(alice).general_study()
    second = CourseService(alice).general_study()
    bobs = CourseService(bob).general_study()

    assert first == second
    assert first.id != bobs.id
    assert first.owner_user_id == "u_alice"
    assert first.title == "General Study"
    assert first.workspace_kind == "general_study"
    assert first.state == "active"
    assert bobs.owner_user_id == "u_bob"
    assert bobs.workspace_kind == "general_study"
    assert [
        course.id
        for course in alice.list_courses()
        if course.workspace_kind == "general_study"
    ] == [first.id]

    academic = alice.create_course("Biology")
    assert academic.workspace_kind == "academic_course"
    with pytest.raises(CourseNotFoundError):
        bob.get_course(first.id)
    with pytest.raises(CourseConflictError, match="cannot be renamed"):
        CourseService(alice).rename(first.id, "My notes", first.revision)
    with pytest.raises(CourseConflictError, match="cannot be archived"):
        await CourseService(alice).archive(first.id, first.revision)

    persisted = CourseRepository(db_path, "u_alice").get_or_create_general_study()
    assert persisted == first

    practice = CoursePracticeRepository(alice)
    with pytest.raises(CourseConflictError, match="does not support Course Practice"):
        practice.create_practice_set(
            first.id,
            title="Must not exist",
            expected_course_write_epoch=first.write_epoch,
        )
    with pytest.raises(CourseConflictError, match="cannot accept Course sources"):
        alice.create_source(
            first.id,
            kind="notes",
            display_name="must-not-exist.txt",
            manifest=[],
            content_sha256="0" * 64,
        )
    with pytest.raises(CourseConflictError, match="cannot accept Course sources"):
        alice.ensure_managed_kb_ref(first.id, "personal:kb:forbidden")

    academic_source = alice.create_source(
        academic.id,
        kind="notes",
        display_name="biology.txt",
        manifest=[],
        content_sha256="1" * 64,
    )
    academic_practice = practice.create_practice_set(
        academic.id,
        title="Biology review",
        expected_course_write_epoch=academic.write_epoch,
    )

    # The database itself enforces the boundary if a caller bypasses services.
    with sqlite3.connect(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="system-managed identity"):
            conn.execute(
                """INSERT INTO courses
                   (id, owner_user_id, title, state, revision, write_epoch,
                    managed_kb_ref, workspace_kind, created_at, updated_at,
                    archived_at)
                   VALUES ('crs_forged_general', 'u_mallory', 'Forged notes',
                           'active', 1, 1, 'forbidden', 'general_study',
                           1.0, 1.0, NULL)"""
            )
        with pytest.raises(sqlite3.IntegrityError, match="academic Course"):
            conn.execute(
                """INSERT INTO course_sources
                   (id, course_id, kind, display_name, state, manifest_json,
                    content_sha256, revision, created_at, updated_at)
                   VALUES ('src_forbidden', ?, 'notes', 'forbidden', 'processing',
                           '[]', ?, 1, 1.0, 1.0)""",
                (first.id, "0" * 64),
            )
        with pytest.raises(sqlite3.IntegrityError, match="academic Course"):
            conn.execute(
                """INSERT INTO practice_sets
                   (id, owner_user_id, course_id, title, mode, state,
                    current_revision_id, revision, write_epoch, created_at,
                    updated_at, archived_at)
                   VALUES ('prc_forbidden', 'u_alice', ?, 'forbidden', 'manual',
                           'draft', NULL, 1, 1, 1.0, 1.0, NULL)""",
                (first.id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="academic Course"):
            conn.execute(
                "UPDATE course_sources SET course_id=? WHERE id=?",
                (first.id, academic_source.id),
            )
        with pytest.raises(sqlite3.IntegrityError, match="academic Course"):
            conn.execute(
                "UPDATE practice_sets SET course_id=? WHERE id=?",
                (first.id, academic_practice.id),
            )
        with pytest.raises(sqlite3.IntegrityError, match="Course Knowledge"):
            conn.execute(
                "UPDATE courses SET managed_kb_ref='forbidden' WHERE id=?",
                (first.id,),
            )

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM course_sources WHERE course_id=?", (first.id,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM practice_sets WHERE course_id=?", (first.id,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT managed_kb_ref FROM courses WHERE id=?", (first.id,)
        ).fetchone()[0] is None


def test_source_manifest_revision_and_crash_reconciliation(tmp_path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Writing")
    source = repo.create_source(
        course.id,
        kind="notes",
        display_name="draft.txt",
        manifest=[],
        content_sha256="0" * 64,
    )
    updated = repo.update_processing_source_manifest(
        course.id,
        source.id,
        operation_id=source.operation_id or "",
        expected_revision=source.revision,
        manifest=[{"path": "draft.txt", "size": 5, "sha256": "a" * 64}],
        content_sha256="b" * 64,
    )
    assert updated.revision == 2
    assert updated.manifest[0]["path"] == "draft.txt"
    assert repo.reconcile_abandoned_sources(
        active_operation_ids=set(), older_than_seconds=0
    ) == 1
    assert repo.get_source(course.id, source.id).state == "failed"


def test_course_scoped_reconciliation_never_fails_another_courses_live_source(
    tmp_path,
) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course_a = repo.create_course("Course A")
    course_b = repo.create_course("Course B")
    source_a = repo.create_source(
        course_a.id,
        kind="notes",
        display_name="a.txt",
        manifest=[],
        content_sha256="a" * 64,
    )
    source_b = repo.create_source(
        course_b.id,
        kind="notes",
        display_name="b.txt",
        manifest=[],
        content_sha256="b" * 64,
    )

    assert repo.reconcile_abandoned_sources(
        active_operation_ids=set(),
        course_id=course_a.id,
        older_than_seconds=0,
    ) == 1
    assert repo.get_source(course_a.id, source_a.id).state == "failed"
    assert repo.get_source(course_b.id, source_b.id).state == "processing"


def test_fifty_private_profiles_and_ten_concurrent_operations(tmp_path) -> None:
    def create_for(index: int) -> tuple[str, str]:
        owner = f"u_{index:02d}"
        repo = CourseRepository(tmp_path / owner / "courses.db", owner)
        course = repo.create_course("Shared title")
        return owner, course.owner_user_id

    with ThreadPoolExecutor(max_workers=10) as pool:
        owners = list(pool.map(create_for, range(50)))

    assert len(owners) == 50
    assert all(expected == actual for expected, actual in owners)
    assert len(
        {
            CourseRepository(tmp_path / owner / "courses.db", owner).list_courses()[0].id
            for owner, _ in owners
        }
    ) == 50


def test_managed_kb_reference_is_idempotent_but_cannot_be_reassigned(tmp_path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_admin")
    course = repo.create_course("Private Admin Course")
    first = repo.ensure_managed_kb_ref(course.id, "personal:kb:course_one")
    second = repo.ensure_managed_kb_ref(course.id, "personal:kb:course_one")
    assert first.managed_kb_ref == second.managed_kb_ref
    with pytest.raises(CourseConflictError, match="already assigned"):
        repo.ensure_managed_kb_ref(course.id, "personal:kb:other")


def test_source_replacement_preserves_prior_fingerprint_and_lineage(tmp_path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Literature")
    original = repo.create_source(
        course.id,
        kind="reading",
        display_name="week-one.pdf",
        manifest=[],
        content_sha256="a" * 64,
    )
    original = repo.transition_source(
        course.id,
        original.id,
        operation_id=original.operation_id or "",
        expected_source_revision=original.revision,
        expected_course_revision=course.revision,
        expected_write_epoch=course.write_epoch,
        state="ready",
    )
    replacement = repo.create_source(
        course.id,
        kind="reading",
        display_name="week-one.pdf",
        manifest=[],
        content_sha256="b" * 64,
        supersedes_source_id=original.id,
    )
    assert replacement.supersedes_source_id == original.id
    assert repo.get_source(course.id, original.id).content_sha256 == "a" * 64


def test_failed_source_can_be_replaced_without_rewriting_failed_history(tmp_path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Biology")
    failed = repo.create_source(
        course.id,
        kind="document",
        display_name="broken.pdf",
        manifest=[],
        content_sha256="a" * 64,
    )
    failed = repo.transition_source(
        course.id,
        failed.id,
        operation_id=failed.operation_id or "",
        expected_source_revision=failed.revision,
        expected_course_revision=course.revision,
        expected_write_epoch=course.write_epoch,
        state="failed",
    )

    replacement = repo.create_source(
        course.id,
        kind="document",
        display_name="fixed.pdf",
        manifest=[],
        content_sha256="b" * 64,
        supersedes_source_id=failed.id,
    )

    assert replacement.supersedes_source_id == failed.id
    assert replacement.state == "processing"
    retained = repo.get_source(course.id, failed.id)
    assert retained.state == "failed"
    assert retained.content_sha256 == "a" * 64


def test_source_lineage_allows_only_one_live_replacement(tmp_path) -> None:
    db_path = tmp_path / "courses.db"
    repo = CourseRepository(db_path, "u_alice")
    course = repo.create_course("Literature")
    original = repo.create_source(
        course.id,
        kind="reading",
        display_name="week-one.pdf",
        manifest=[],
        content_sha256="a" * 64,
    )
    original = repo.transition_source(
        course.id,
        original.id,
        operation_id=original.operation_id or "",
        expected_source_revision=original.revision,
        expected_course_revision=course.revision,
        expected_write_epoch=course.write_epoch,
        state="ready",
    )
    first = repo.create_source(
        course.id,
        kind="reading",
        display_name="week-one-v2.pdf",
        manifest=[],
        content_sha256="b" * 64,
        supersedes_source_id=original.id,
    )

    # Separate wrappers share one path-keyed process lock; the SQLite constraint
    # remains the final authority for direct and cross-process callers.
    contender = CourseRepository(db_path, "u_alice")
    assert contender._write_lock is repo._write_lock  # noqa: SLF001
    with pytest.raises(CourseConflictError, match="active replacement"):
        contender.create_source(
            course.id,
            kind="reading",
            display_name="week-one-other.pdf",
            manifest=[],
            content_sha256="c" * 64,
            supersedes_source_id=original.id,
        )

    first = repo.transition_source(
        course.id,
        first.id,
        operation_id=first.operation_id or "",
        expected_source_revision=first.revision,
        expected_course_revision=course.revision,
        expected_write_epoch=course.write_epoch,
        state="failed",
    )
    retry = contender.create_source(
        course.id,
        kind="reading",
        display_name="week-one-v3.pdf",
        manifest=[],
        content_sha256="d" * 64,
        supersedes_source_id=original.id,
    )
    assert first.state == "failed"
    assert retry.state == "processing"


def test_archive_source_rechecks_course_state_inside_write(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "courses.db"
    repo = CourseRepository(db_path, "u_alice")
    contender = CourseRepository(db_path, "u_alice")
    course = repo.create_course("Literature")
    source = repo.create_source(
        course.id,
        kind="reading",
        display_name="week-one.pdf",
        manifest=[],
        content_sha256="a" * 64,
    )
    source = repo.transition_source(
        course.id,
        source.id,
        operation_id=source.operation_id or "",
        expected_source_revision=source.revision,
        expected_course_revision=course.revision,
        expected_write_epoch=course.write_epoch,
        state="ready",
    )
    original_get = repo.get_course

    def archive_after_precheck(course_id: str):
        result = original_get(course_id)
        contender.archive_course(course_id, expected_revision=result.revision)
        return result

    monkeypatch.setattr(repo, "get_course", archive_after_precheck)
    with pytest.raises(CourseConflictError, match="Archived"):
        repo.archive_source(course.id, source.id, expected_revision=source.revision)
    assert contender.get_source(course.id, source.id).state == "ready"


@pytest.mark.asyncio
async def test_archive_rejects_active_course_turn(monkeypatch, tmp_path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Physics")
    store = SimpleNamespace(has_active_course_turn=lambda _course_id: _async_true())
    monkeypatch.setattr(
        "deeptutor.services.session.get_personal_sqlite_session_store", lambda: store
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_turn_runtime_manager",
        lambda **_kwargs: SimpleNamespace(
            recover_orphan_course_turns=lambda _cid: _async_zero(),
            has_live_course_turn=lambda _cid: _async_false(),
        ),
    )

    with pytest.raises(CourseConflictError, match="active turn"):
        await CourseService(repo).archive(course.id, course.revision)
    assert repo.get_course(course.id).state == "active"


async def _async_true() -> bool:
    return True


async def _async_false() -> bool:
    return False


async def _async_zero() -> int:
    return 0


@pytest.mark.asyncio
async def test_archive_rejects_post_status_live_course_execution(monkeypatch, tmp_path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Physics")
    store = SimpleNamespace(has_active_course_turn=lambda _course_id: _async_false())
    runtime = SimpleNamespace(
        recover_orphan_course_turns=lambda _cid: _async_zero(),
        has_live_course_turn=lambda _course_id: _async_true(),
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_personal_sqlite_session_store", lambda: store
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_turn_runtime_manager", lambda **_kwargs: runtime
    )

    with pytest.raises(CourseConflictError, match="active turn"):
        await CourseService(repo).archive(course.id, course.revision)
    assert repo.get_course(course.id).state == "active"


@pytest.mark.asyncio
async def test_archive_recovers_restart_orphaned_course_turn(monkeypatch, tmp_path) -> None:
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore
    from deeptutor.services.session.turn_runtime import TurnRuntimeManager

    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Physics")
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    session = await store.create_session(course_id=course.id)
    turn = await store.create_turn(session["id"], capability="chat")
    runtime = TurnRuntimeManager(store)
    monkeypatch.setattr(
        "deeptutor.services.session.get_personal_sqlite_session_store", lambda: store
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_turn_runtime_manager", lambda **_kwargs: runtime
    )

    archived = await CourseService(repo).archive(course.id, course.revision)

    assert archived.state == "archived"
    assert (await store.get_turn(turn["id"]))["status"] == "failed"


@pytest.mark.asyncio
async def test_archive_directly_reconciles_restart_orphaned_source(
    monkeypatch, tmp_path
) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Physics")
    repo.create_source(
        course.id,
        kind="document",
        display_name="lost.txt",
        manifest=[],
        content_sha256="a" * 64,
        operation_id="op_lost",
    )
    store = SimpleNamespace(has_active_course_turn=lambda _course_id: _async_false())
    runtime = SimpleNamespace(
        recover_orphan_course_turns=lambda _course_id: _async_zero(),
        has_live_course_turn=lambda _course_id: _async_false(),
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_personal_sqlite_session_store", lambda: store
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_turn_runtime_manager", lambda **_kwargs: runtime
    )
    monkeypatch.setattr(
        "deeptutor.api.utils.task_id_manager.TaskIDManager.get_instance",
        lambda: SimpleNamespace(get_task_metadata=lambda _operation: None),
    )

    archived = await CourseService(repo).archive(course.id, course.revision)

    assert archived.state == "archived"


@pytest.mark.asyncio
async def test_source_archive_reconciles_orphan_before_revision_decision(
    monkeypatch, tmp_path
) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Physics")
    source = repo.create_source(
        course.id,
        kind="document",
        display_name="lost.txt",
        manifest=[],
        content_sha256="a" * 64,
        operation_id="op_lost",
    )
    store = SimpleNamespace(has_active_course_turn=lambda _course_id: _async_false())
    runtime = SimpleNamespace(
        recover_orphan_course_turns=lambda _course_id: _async_zero(),
        has_live_course_turn=lambda _course_id: _async_false(),
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_personal_sqlite_session_store", lambda: store
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_turn_runtime_manager", lambda **_kwargs: runtime
    )
    monkeypatch.setattr(
        "deeptutor.api.utils.task_id_manager.TaskIDManager.get_instance",
        lambda: SimpleNamespace(get_task_metadata=lambda _operation: None),
    )
    service = CourseService(repo)

    with pytest.raises(CourseConflictError, match="stale"):
        await service.archive_source(course.id, source.id, source.revision)
    failed = repo.get_source(course.id, source.id)
    assert failed.state == "failed"
    archived = await service.archive_source(course.id, source.id, failed.revision)
    assert archived.state == "archived"


@pytest.mark.asyncio
async def test_source_archive_rejects_active_course_turn(monkeypatch, tmp_path) -> None:
    repo = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = repo.create_course("Physics")
    source = repo.create_source(
        course.id,
        kind="notes",
        display_name="week-one.pdf",
        manifest=[],
        content_sha256="a" * 64,
    )
    source = repo.transition_source(
        course.id,
        source.id,
        operation_id=source.operation_id or "",
        expected_source_revision=source.revision,
        expected_course_revision=course.revision,
        expected_write_epoch=course.write_epoch,
        state="ready",
    )
    store = SimpleNamespace(has_active_course_turn=lambda _course_id: _async_true())
    runtime = SimpleNamespace(
        recover_orphan_course_turns=lambda _cid: _async_zero(),
        has_live_course_turn=lambda _course_id: _async_false(),
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_personal_sqlite_session_store", lambda: store
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_turn_runtime_manager", lambda **_kwargs: runtime
    )

    with pytest.raises(CourseConflictError, match="active turn"):
        await CourseService(repo).archive_source(course.id, source.id, source.revision)

    assert repo.get_source(course.id, source.id).state == "ready"


@pytest.mark.asyncio
async def test_course_lifecycle_lock_serializes_same_course() -> None:
    first = course_operation_lock("crs_serial")
    second = course_operation_lock("crs_serial")
    assert first is second
    await first.acquire()
    entered = False

    async def contender() -> None:
        nonlocal entered
        async with second:
            entered = True

    task = asyncio.create_task(contender())
    await asyncio.sleep(0)
    assert entered is False
    first.release()
    await task
    assert entered is True
