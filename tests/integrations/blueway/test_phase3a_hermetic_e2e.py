"""Hermetic Phase 3A two-owner integration proof over real local HTTP."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from deeptutor.courses.repository import CourseRepository
from deeptutor.integrations.blueway.repository import BlueWayRepository

# ``tests`` is intentionally not an installed package in this repository.
# Keep this helper local to the test directory without altering production
# import resolution or requiring a global PYTHONPATH setting.
sys.path.insert(0, str(Path(__file__).parent))
pytest_plugins = ("phase3a_hermetic_harness",)
from phase3a_hermetic_harness import HermeticPhase3AHarness


def _mapped_course_id(repository: BlueWayRepository, connection_id: str) -> str:
    with repository.courses._connect() as database:  # noqa: SLF001 - durable map assertion.
        row = database.execute(
            """SELECT course_id FROM blueway_course_maps
               WHERE connection_id = ? AND external_course_id = 'remote-course-b'""",
            (connection_id,),
        ).fetchone()
    assert row is not None
    return str(row["course_id"])


def _ready_bundle_text(harness: HermeticPhase3AHarness, owner: str, course_id: str) -> str:
    repository = harness.repository(owner)
    sources = [
        source
        for source in repository.list_sources(course_id)
        if source.kind == "blueway snapshot" and source.state == "ready"
    ]
    assert len(sources) == 1
    source = sources[0]
    index = (
        harness.workspace_root
        / "data"
        / "users"
        / harness.owner_ids[owner]
        / "knowledge_bases"
        / f"course_{course_id}_{source.id}"
        / "deterministic-index.json"
    )
    return str(json.loads(index.read_text(encoding="utf-8"))["chunks"][0]["text"])


def test_phase3a_hermetic_two_owner_disconnect_reconnect_restart(
    hermetic_phase3a: HermeticPhase3AHarness,
) -> None:
    """Prove the full synthetic-owner lifecycle without hosted providers."""
    harness = hermetic_phase3a

    # Alice's pending pairing is private even before approval.
    alice_pending = harness.connection_start("alice")
    foreign_attempt = harness.client.get(
        f"/api/v1/integrations/blueway/connect/{alice_pending['attempt_id']}/status",
        headers=harness.headers("bob"),
    )
    assert foreign_attempt.status_code == 404
    harness.approve(start=alice_pending, subject="blueway-subject-alice")
    alice_polled = harness.poll_connection("alice", str(alice_pending["attempt_id"]))
    assert alice_polled["connection"]["state"] == "active"
    alice_run_id = str(alice_polled["active_run"]["id"])
    assert harness.wait_for_run("alice", alice_run_id)["state"] == "completed"
    alice_connection = alice_polled["connection"]
    alice_grant = harness.authority.grant_id_for_subject("blueway-subject-alice")

    # The no-speech source is omitted, while the real transcript remains owner-scoped.
    alice_repository = BlueWayRepository(harness.repository("alice"))
    alice_course = _mapped_course_id(alice_repository, str(alice_connection["id"]))
    assert "PHASE3A_ALICE_ONLY" in _ready_bundle_text(harness, "alice", alice_course)
    no_speech_course = next(
        course.id
        for course in harness.repository("alice").list_courses()
        if course.id != alice_course
    )
    assert not harness.repository("alice").list_sources(no_speech_course)
    encrypted = harness.credential_path("alice", str(alice_connection["id"]))
    assert encrypted.exists() and encrypted.stat().st_mode & 0o777 == 0o600
    assert b"refresh_" not in encrypted.read_bytes()

    # Bob receives a different local workspace and cannot enumerate Alice's run or course.
    assert harness.status("bob")["connection"] is None
    assert (
        harness.client.get(
            f"/api/v1/integrations/blueway/sync-runs/{alice_run_id}", headers=harness.headers("bob")
        ).status_code
        == 404
    )
    assert (
        harness.client.get(
            f"/api/v1/courses/{alice_course}", headers=harness.headers("bob")
        ).status_code
        == 404
    )
    bob_connection, bob_run = harness.connect_approve_sync(
        owner="bob", subject="blueway-subject-bob"
    )
    bob_repository = BlueWayRepository(harness.repository("bob"))
    bob_course = _mapped_course_id(bob_repository, str(bob_connection["id"]))
    bob_text = _ready_bundle_text(harness, "bob", bob_course)
    assert "PHASE3A_BOB_ONLY" in bob_text
    assert "PHASE3A_ALICE_ONLY" not in bob_text
    assert alice_course != bob_course
    assert str(bob_run["id"]) != alice_run_id

    # Re-instantiation reads the encrypted persistent credential and SQLite state;
    # no in-memory attempt, repository, or token data is copied into the replacement.
    harness.restart_service()
    restarted_status = harness.status("alice")
    assert restarted_status["connection"]["id"] == alice_connection["id"]
    rerun = harness.client.post(
        "/api/v1/integrations/blueway/sync", headers=harness.headers("alice")
    )
    assert rerun.status_code == 202, rerun.text
    assert harness.wait_for_run("alice", str(rerun.json()["id"]))["state"] == "completed"

    # Disconnect revokes the remote grant and fences future local access; imported
    # Course/source rows remain.  Same-subject reconnect creates a new grant but
    # reuses the original opaque Course mapping rather than duplicating content.
    disconnected = harness.client.post(
        "/api/v1/integrations/blueway/disconnect",
        headers=harness.headers("alice"),
        json={"expected_revision": restarted_status["connection"]["revision"]},
    )
    assert disconnected.status_code == 200, disconnected.text
    assert disconnected.json()["connection"]["state"] == "disconnected"
    assert harness.authority.grant_is_revoked(alice_grant)
    assert alice_grant in harness.authority.revoked_grant_ids
    assert (
        harness.client.post(
            "/api/v1/integrations/blueway/sync", headers=harness.headers("alice")
        ).status_code
        == 404
    )
    assert harness.repository("alice").get_course(alice_course).id == alice_course

    reconnected, reconnect_run = harness.connect_approve_sync(
        owner="alice", subject="blueway-subject-alice"
    )
    assert reconnected["id"] != alice_connection["id"]
    assert (
        _mapped_course_id(BlueWayRepository(harness.repository("alice")), str(reconnected["id"]))
        == alice_course
    )
    assert harness.authority.grant_id_for_subject("blueway-subject-alice") != alice_grant
    assert harness.wait_for_run("alice", str(reconnect_run["id"]))["state"] == "completed"


@pytest.mark.parametrize("owner", ["alice", "bob"])
def test_phase3a_hermetic_requires_authenticated_route_context(
    hermetic_phase3a: HermeticPhase3AHarness, owner: str
) -> None:
    """The hermetic app mounts the integration under the production auth guard."""
    response = hermetic_phase3a.client.get("/api/v1/integrations/blueway")
    assert response.status_code == 401
    assert hermetic_phase3a.status(owner)["enabled"] is True
