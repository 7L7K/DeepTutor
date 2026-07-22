"""Internal deterministic Course-source staging for verified BlueWay records.

This deliberately bypasses FastAPI UploadFile and every paid provider.  The
renderer receives only already-validated, owner-mapped records and writes a
private JSON bundle which the existing deterministic local indexer can consume.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import secrets

from deeptutor.courses.deterministic_provider import build_index
from deeptutor.courses.ingestion import source_kb_name
from deeptutor.multi_user.identity import identity_write_lock
from deeptutor.multi_user.paths import get_personal_path_service, restrict_private_tree_permissions

from .repository import BlueWayRepository, Connection


class BundleMaterializationError(RuntimeError):
    pass


def _encoded_bundle(*, snapshot_id: str, course_id: str, records: list[dict]) -> bytes:
    payload = {
        "schema": "teeechr.blueway.course-bundle.v1",
        "snapshot_id": snapshot_id,
        "course_id": course_id,
        "records": records,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _idempotency_key(*, external_subject: str, external_course_id: str, bundle_sha256: str) -> str:
    """A bounded key which retains all semantic identity through a digest."""
    identity = json.dumps(
        {"external_subject": external_subject, "external_course_id": external_course_id, "bundle_sha256": bundle_sha256},
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return f"blueway:{hashlib.sha256(identity).hexdigest()}"


def materialize_course_bundles(
    repository: BlueWayRepository, *, connection: Connection, snapshot_id: str,
    assert_owner_current: Callable[[], None] | None = None,
) -> int:
    """Stage/replace one owned generated source per active mapped Course.

    A new source is made ready before its prior version is archived.  If a
    disconnect or Course archive wins any fence, normal Course APIs reject the
    commit and no generated source is granted retrieval authority.
    """
    paths = get_personal_path_service(repository.owner_user_id)
    staged: list[dict] = []
    processing_sources: list[tuple[str, str]] = []
    try:
        for course_id, external_course_id, records in repository.bundle_records(connection.id):
            encoded = _encoded_bundle(snapshot_id=snapshot_id, course_id=course_id, records=records)
            digest = hashlib.sha256(encoded).hexdigest()
            existing = [source for source in repository.courses.list_sources(course_id) if source.kind == "blueway snapshot" and source.state in {"ready", "archived"}]
            previous = next((source for source in existing if source.state == "ready"), None)
            key = _idempotency_key(
                external_subject=connection.external_subject, external_course_id=external_course_id, bundle_sha256=digest,
            )
            source = repository.courses.get_source_by_idempotency_key(course_id, key)
            if source is None:
                source = repository.courses.create_source(
                    course_id, kind="blueway snapshot", display_name="BlueWay verified course bundle",
                    manifest=[{"path": "blueway-course-bundle.json", "size": len(encoded), "sha256": digest}],
                    content_sha256=digest, supersedes_source_id=previous.id if previous else None,
                    operation_id=f"blueway_bundle_{secrets.token_hex(16)}", idempotency_key=key,
                )
            if source.state == "processing":
                processing_sources.append((course_id, source.id))
                base = paths.get_knowledge_bases_root()
                raw_dir = base / source_kb_name(course_id, source.id) / "raw" / source.id
                raw_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                bundle_path = raw_dir / "blueway-course-bundle.json"
                bundle_path.write_bytes(encoded)
                bundle_path.chmod(0o600)
                if not build_index(raw_dir.parent.parent, [str(bundle_path)]):
                    raise RuntimeError("Deterministic BlueWay bundle index was empty")
                restrict_private_tree_permissions(raw_dir.parent.parent)
                staged.append({
                    "course_id": course_id, "source_id": source.id,
                    "operation_id": str(source.operation_id), "source_revision": source.revision,
                    "previous_source_id": previous.id if previous is not None and previous.id != source.id else None,
                })
            elif source.state == "ready":
                # A same-subject reconnect may own the exact immutable bundle
                # already.  It still needs a guarded record-source rebind.
                staged.append({
                    "course_id": course_id, "source_id": source.id,
                    "operation_id": str(source.operation_id), "source_revision": source.revision,
                    "previous_source_id": None, "already_ready": True,
                })
            elif source.state != "ready":
                raise RuntimeError("BlueWay bundle source is not ready to commit")
        if assert_owner_current is not None:
            assert_owner_current()
        # Lock order is identity -> CourseRepository.  Account disable/delete
        # mutations hold the same identity lock, so no source can become ready
        # after a concurrent owner revocation wins.
        with identity_write_lock():
            if assert_owner_current is not None:
                assert_owner_current()
            repository.commit_bundle_sources(connection.id, expected_generation=connection.grant_generation, items=staged)
        return len(staged)
    except Exception as exc:
        # A generated source must never be left indefinitely processing if a
        # Course archive/revocation or local-index failure wins the race.
        for course_id, source_id in processing_sources:
            source = repository.courses.get_source(course_id, source_id)
            if source.state == "processing" and source.operation_id:
                repository.abandon_bundle_source(
                    course_id=course_id, source_id=source.id, operation_id=source.operation_id,
                    expected_revision=source.revision,
                )
        raise BundleMaterializationError("BlueWay Course bundle could not be materialized") from exc
