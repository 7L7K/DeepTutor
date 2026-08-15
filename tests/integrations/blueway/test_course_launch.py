"""Owner and term isolation for the authenticated BlueWay launch seam."""

from __future__ import annotations

import hashlib
from pathlib import Path

from deeptutor.courses.repository import CourseRepository
from deeptutor.integrations.blueway.launch import resolve_course_launch
from deeptutor.integrations.blueway.repository import BlueWayRepository


def _ready_map(
    courses: CourseRepository,
    blueway: BlueWayRepository,
    connection_id: str,
    external_term_id: str | None,
    *,
    title: str = "Biology 101",
    external_course_id: str = "blueway-biology-101",
):
    course = blueway.create_course_map(
        connection_id=connection_id,
        external_course_id=external_course_id,
        external_term_id=external_term_id,
        remote_title=title,
        remote_state="active",
        remote_hash=((external_term_id or "legacy")[:1] or "x") * 64,
        snapshot_id=f"snapshot-{external_term_id or 'legacy'}",
        expected_generation=1,
    )
    source = courses.create_source(
        course.id,
        kind="blueway snapshot",
        display_name=f"{title} verified bundle",
        manifest=[],
        content_sha256=((external_term_id or "legacy")[-1:] or "x") * 64,
    )
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute("UPDATE course_sources SET state = 'ready' WHERE id = ?", (source.id,))
    authorization_id = f"auth-{connection_id}-{external_course_id}-{external_term_id or 'legacy'}"
    blueway.create_workspace_authorization(
        authorization_id=authorization_id,
        client_id="blueway-client",
        external_subject_hash=hashlib.sha256(b"blueway-a").hexdigest(),
        scope="teeechr.workspace.read.v1",
        connection_id=connection_id,
        external_course_id=external_course_id,
        external_term_id=external_term_id,
    )
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE blueway_workspace_authorizations SET last_verified_at = ?, lease_expires_at = ? WHERE authorization_id = ?",
            (1_800_000_000.0, 2_000_000_000.0, authorization_id),
        )
    return course


def test_launch_is_exact_by_course_and_term_and_does_not_create_rows(tmp_path: Path) -> None:
    courses = CourseRepository(tmp_path / "courses.db", "owner-a")
    blueway = BlueWayRepository(courses)
    connection = blueway.create_active_connection(
        external_subject="blueway-a",
        scope_version="v1",
        observability_trace_id="bwr_11111111-1111-4111-8111-111111111111",
    )
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute("UPDATE blueway_connections SET last_sync_at = ? WHERE id = ?", (1_800_000_000.0, connection.id))

    fall = _ready_map(courses, blueway, connection.id, "fall-2026")
    winter = _ready_map(courses, blueway, connection.id, "winter-2027")

    fall_result = resolve_course_launch(
        blueway,
        external_course_id="blueway-biology-101",
        external_term_id="fall-2026",
        now=1_800_000_100.0,
    )
    winter_result = resolve_course_launch(
        blueway,
        external_course_id="blueway-biology-101",
        external_term_id="winter-2027",
    )
    assert fall_result.as_dict() == {
        "schema_version": "teeechr.blueway.launch.v1",
        "status": "ready",
        "course_id": fall.id,
    }
    assert winter_result.course_id == winter.id
    assert winter_result.course_id != fall_result.course_id
    assert resolve_course_launch(
        blueway,
        external_course_id="blueway-biology-101",
        external_term_id="fall-2026",
        now=1_800_000_000.0 + 24 * 60 * 60 + 1,
    ).status == "stale"
    assert resolve_course_launch(
        blueway,
        external_course_id="blueway-biology-101",
        external_term_id="spring-2028",
    ).status == "term_mismatch"

    with courses._connect() as conn:  # noqa: SLF001
        assert conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM blueway_course_maps").fetchone()[0] == 2


def test_launch_fails_closed_for_missing_foreign_and_not_ready_courses(tmp_path: Path) -> None:
    owner_courses = CourseRepository(tmp_path / "owner.db", "owner-a")
    owner_blueway = BlueWayRepository(owner_courses)
    owner_connection = owner_blueway.create_active_connection(external_subject="blueway-a", scope_version="v1")
    _ready_map(owner_courses, owner_blueway, owner_connection.id, "fall-2026")

    foreign_courses = CourseRepository(tmp_path / "foreign.db", "owner-b")
    foreign_blueway = BlueWayRepository(foreign_courses)
    foreign_connection = foreign_blueway.create_active_connection(external_subject="blueway-b", scope_version="v1")
    _ready_map(
        foreign_courses,
        foreign_blueway,
        foreign_connection.id,
        "fall-2026",
        external_course_id="foreign-biology-101",
    )

    assert resolve_course_launch(
        owner_blueway,
        external_course_id="not-a-course",
        external_term_id="fall-2026",
    ).status == "course_not_found"
    assert resolve_course_launch(
        owner_blueway,
        external_course_id="foreign-biology-101",
        external_term_id="fall-2026",
    ).status == "course_not_found"

    with owner_courses._connect() as conn:  # noqa: SLF001
        row = conn.execute("SELECT course_id FROM blueway_course_maps LIMIT 1").fetchone()
        assert row is not None
        course_id = str(row["course_id"])
    with owner_courses._write_lock, owner_courses._connect() as conn:  # noqa: SLF001
        conn.execute("DELETE FROM course_sources WHERE course_id = ?", (course_id,))
    assert resolve_course_launch(
        owner_blueway,
        external_course_id="blueway-biology-101",
        external_term_id="fall-2026",
    ).status == "course_not_ready"


def test_launch_requires_exact_scoped_authorization_and_unexpired_lease(tmp_path: Path) -> None:
    courses = CourseRepository(tmp_path / "courses.db", "owner-a")
    blueway = BlueWayRepository(courses)
    connection = blueway.create_active_connection(external_subject="blueway-a", scope_version="v1")
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE blueway_connections SET last_sync_at = ? WHERE id = ?",
            (1_800_000_000.0, connection.id),
        )
    _ready_map(courses, blueway, connection.id, "fall-2026")

    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute(
            """UPDATE blueway_workspace_authorizations
                  SET external_course_id = NULL, external_term_id = NULL
                WHERE connection_id = ?""",
            (connection.id,),
        )
    assert resolve_course_launch(
        blueway,
        external_course_id="blueway-biology-101",
        external_term_id="fall-2026",
    ).status == "course_not_ready"

    _ready_map(courses, blueway, connection.id, "spring-2027")
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE blueway_workspace_authorizations SET lease_expires_at = ?",
            (1_800_000_000.0,),
        )
    expired = resolve_course_launch(
        blueway,
        external_course_id="blueway-biology-101",
        external_term_id="spring-2027",
        now=1_800_000_001.0,
    )
    assert expired.status == "course_not_ready"
    assert expired.trace_id == connection.observability_trace_id
    assert expired.connection_ref == connection.id


def test_revoked_exact_workspace_authorization_blocks_direct_launch(tmp_path: Path) -> None:
    courses = CourseRepository(tmp_path / "courses.db", "owner-a")
    blueway = BlueWayRepository(courses)
    connection = blueway.create_active_connection(external_subject="blueway-a", scope_version="v1")
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE blueway_connections SET last_sync_at = ? WHERE id = ?",
            (1_800_000_000.0, connection.id),
        )
    _ready_map(courses, blueway, connection.id, "fall-2026")
    with courses._connect() as conn:  # noqa: SLF001
        authorization_id = str(
            conn.execute(
                "SELECT authorization_id FROM blueway_workspace_authorizations WHERE connection_id = ?",
                (connection.id,),
            ).fetchone()[0]
        )

    blueway.revoke_workspace_authorization(authorization_id)
    assert resolve_course_launch(
        blueway,
        external_course_id="blueway-biology-101",
        external_term_id="fall-2026",
    ).status == "course_not_ready"


def test_launch_refuses_revoked_connection_and_failed_sync(tmp_path: Path) -> None:
    courses = CourseRepository(tmp_path / "courses.db", "owner-a")
    blueway = BlueWayRepository(courses)
    connection = blueway.create_active_connection(external_subject="blueway-a", scope_version="v1")
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute("UPDATE blueway_connections SET last_sync_at = ? WHERE id = ?", (1_800_000_000.0, connection.id))
    _ready_map(courses, blueway, connection.id, "fall-2026")

    run = blueway.queue_sync(connection.id)
    blueway.fail_run(run.id, error_code="provider_unavailable")
    assert resolve_course_launch(
        blueway,
        external_course_id="blueway-biology-101",
        external_term_id="fall-2026",
    ).status == "temporarily_unavailable"

    connection = blueway.get_connection(connection.id)
    blueway.begin_disconnect(connection.id, expected_revision=connection.revision)
    assert resolve_course_launch(
        blueway,
        external_course_id="blueway-biology-101",
        external_term_id="fall-2026",
    ).status == "connection_revoked"


def test_legacy_termless_launch_resolves_one_exact_null_term_mapping(tmp_path: Path) -> None:
    courses = CourseRepository(tmp_path / "courses.db", "owner-a")
    blueway = BlueWayRepository(courses)
    connection = blueway.create_active_connection(external_subject="blueway-a", scope_version="v1")
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE blueway_connections SET last_sync_at = ? WHERE id = ?",
            (1_800_000_000.0, connection.id),
        )
    legacy = _ready_map(
        courses,
        blueway,
        connection.id,
        None,
        external_course_id="legacy-biology-101",
    )

    result = resolve_course_launch(
        blueway,
        external_course_id="legacy-biology-101",
        external_term_id=None,
        now=1_800_000_100.0,
    )

    assert result.status == "ready"
    assert result.course_id == legacy.id


def test_termless_launch_never_falls_back_to_term_qualified_courses(tmp_path: Path) -> None:
    courses = CourseRepository(tmp_path / "courses.db", "owner-a")
    blueway = BlueWayRepository(courses)
    connection = blueway.create_active_connection(external_subject="blueway-a", scope_version="v1")
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE blueway_connections SET last_sync_at = ? WHERE id = ?",
            (1_800_000_000.0, connection.id),
        )
    _ready_map(courses, blueway, connection.id, "fall-2026")
    _ready_map(courses, blueway, connection.id, "winter-2027")

    result = resolve_course_launch(
        blueway,
        external_course_id="blueway-biology-101",
        external_term_id=None,
    )

    assert result.status == "term_mismatch"
    assert result.course_id is None


def test_blank_or_whitespace_term_does_not_use_legacy_fallback(tmp_path: Path) -> None:
    courses = CourseRepository(tmp_path / "courses.db", "owner-a")
    blueway = BlueWayRepository(courses)
    connection = blueway.create_active_connection(external_subject="blueway-a", scope_version="v1")
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE blueway_connections SET last_sync_at = ? WHERE id = ?",
            (1_800_000_000.0, connection.id),
        )
    _ready_map(
        courses,
        blueway,
        connection.id,
        None,
        external_course_id="legacy-biology-101",
    )

    result = resolve_course_launch(
        blueway,
        external_course_id="legacy-biology-101",
        external_term_id="   ",
    )

    assert result.status == "term_mismatch"
    assert result.course_id is None


def test_multiple_legacy_mappings_fail_closed(tmp_path: Path) -> None:
    courses = CourseRepository(tmp_path / "courses.db", "owner-a")
    blueway = BlueWayRepository(courses)
    first = blueway.create_active_connection(external_subject="blueway-a", scope_version="v1")
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute("UPDATE blueway_connections SET last_sync_at = ? WHERE id = ?", (1_800_000_000.0, first.id))
    _ready_map(courses, blueway, first.id, None, external_course_id="legacy-biology-101")
    pending = blueway.begin_disconnect(first.id, expected_revision=first.revision)
    blueway.complete_disconnect(pending.id, expected_revision=pending.revision)

    second = blueway.create_active_connection(external_subject="blueway-b", scope_version="v1")
    with courses._write_lock, courses._connect() as conn:  # noqa: SLF001
        conn.execute("UPDATE blueway_connections SET last_sync_at = ? WHERE id = ?", (1_800_000_000.0, second.id))
    _ready_map(courses, blueway, second.id, None, external_course_id="legacy-biology-101")

    result = resolve_course_launch(
        blueway,
        external_course_id="legacy-biology-101",
        external_term_id=None,
    )

    assert result.status == "course_not_found"
    assert result.course_id is None
