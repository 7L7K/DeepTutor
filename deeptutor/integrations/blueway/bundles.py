"""Internal deterministic Course-source staging for verified BlueWay records.

This deliberately bypasses FastAPI UploadFile and every paid provider.  The
renderer receives only already-validated, owner-mapped records and writes a
private JSON bundle which the existing deterministic local indexer can consume.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import secrets

from deeptutor.courses.deterministic_provider import build_index, build_index_payload
from deeptutor.courses.ingestion import source_kb_name
from deeptutor.courses.models import CourseSource
from deeptutor.multi_user.identity import identity_write_lock
from deeptutor.multi_user.paths import get_personal_path_service, restrict_private_tree_permissions

from .repository import BlueWayRepository, Connection


class BundleMaterializationError(RuntimeError):
    pass


def _ready_bundle_path(
    repository: BlueWayRepository, *, course_id: str, source: CourseSource
) -> tuple[Path, Path]:
    """Resolve and verify the immutable raw bundle behind one ready source."""
    root = (
        get_personal_path_service(repository.owner_user_id)
        .get_knowledge_bases_root()
        .resolve()
    )
    kb_dir = root / source_kb_name(course_id, source.id)
    bundle_path = kb_dir / "raw" / source.id / "blueway-course-bundle.json"
    try:
        resolved_kb_dir = kb_dir.resolve()
        resolved_bundle_path = bundle_path.resolve(strict=True)
        resolved_kb_dir.relative_to(root)
        resolved_bundle_path.relative_to(resolved_kb_dir)
    except (OSError, ValueError) as exc:
        raise BundleMaterializationError(
            "BlueWay Course bundle path is unavailable"
        ) from exc
    if (
        not resolved_bundle_path.is_file()
        or bundle_path.is_symlink()
        or resolved_bundle_path.stat().st_nlink != 1
    ):
        raise BundleMaterializationError(
            "BlueWay Course bundle path is unavailable"
        )
    try:
        restrict_private_tree_permissions(resolved_kb_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        raise BundleMaterializationError(
            "BlueWay Course bundle path is unavailable"
        ) from exc
    encoded = resolved_bundle_path.read_bytes()
    if hashlib.sha256(encoded).hexdigest() != source.content_sha256:
        raise BundleMaterializationError(
            "BlueWay Course bundle fingerprint does not match its source receipt"
        )
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleMaterializationError(
            "BlueWay Course bundle is invalid"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "teeechr.blueway.course-bundle.v1"
        or payload.get("course_id") != course_id
        or not isinstance(payload.get("records"), list)
    ):
        raise BundleMaterializationError(
            "BlueWay Course bundle identity does not match its source"
        )
    return resolved_kb_dir, resolved_bundle_path


def _ready_index_matches(
    kb_dir: Path, bundle_path: Path, expected_sha256: str
) -> bool:
    index_path = kb_dir / "deterministic-index.json"
    try:
        resolved_index_path = index_path.resolve(strict=True)
        resolved_index_path.relative_to(kb_dir)
        index_stat = index_path.lstat()
        if index_path.is_symlink() or index_stat.st_nlink != 1:
            return False
        raw = index_path.read_bytes()
        if len(raw) > 256_000:
            return False
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    expected = build_index_payload(
        [str(bundle_path)],
        source_content_sha256=expected_sha256,
    )
    return expected is not None and payload == expected


def ensure_ready_bundle_index(
    repository: BlueWayRepository, *, course_id: str, source: CourseSource
) -> bool:
    """Repair a derived legacy index only from its verified immutable bundle.

    Returns ``True`` when the index was rebuilt and ``False`` when the existing
    index already carried the exact Course-source receipt.
    """
    if source.kind != "blueway snapshot" or source.state != "ready":
        raise BundleMaterializationError(
            "Only ready BlueWay Course bundles can be reconciled"
        )
    kb_dir, bundle_path = _ready_bundle_path(
        repository, course_id=course_id, source=source
    )
    if _ready_index_matches(kb_dir, bundle_path, source.content_sha256):
        return False
    if not build_index(
        kb_dir,
        [str(bundle_path)],
        source_content_sha256=source.content_sha256,
    ):
        raise BundleMaterializationError(
            "Deterministic BlueWay bundle index was empty"
        )
    restrict_private_tree_permissions(kb_dir)
    if not _ready_index_matches(kb_dir, bundle_path, source.content_sha256):
        raise BundleMaterializationError(
            "Deterministic BlueWay bundle index receipt is invalid"
        )
    return True


def reconcile_ready_bundle_indexes(repository: BlueWayRepository) -> int:
    """Best-effort startup reconciliation for legacy derived indexes.

    Invalid or missing immutable raw bundles remain unavailable. They are never
    converted into provider authority merely because an index file exists.
    """
    repaired = 0
    for course in repository.courses.list_courses():
        for source in repository.courses.list_sources(course.id):
            if source.kind != "blueway snapshot" or source.state != "ready":
                continue
            try:
                repaired += int(
                    ensure_ready_bundle_index(
                        repository, course_id=course.id, source=source
                    )
                )
            except BundleMaterializationError:
                continue
    return repaired


def _encoded_bundle(*, snapshot_id: str, course_id: str, records: list[dict]) -> bytes:
    payload = {
        "schema": "teeechr.blueway.course-bundle.v1",
        "snapshot_id": snapshot_id,
        "course_id": course_id,
        "records": records,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _idempotency_key(*, external_subject: str, external_course_id: str, external_term_id: str | None, bundle_sha256: str) -> str:
    """A bounded key which retains all semantic identity through a digest."""
    identity = json.dumps(
        {"external_subject": external_subject, "external_course_id": external_course_id, "external_term_id": external_term_id, "bundle_sha256": bundle_sha256},
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
        for course_id, external_course_id, external_term_id, records in repository.bundle_records(connection.id):
            encoded = _encoded_bundle(snapshot_id=snapshot_id, course_id=course_id, records=records)
            digest = hashlib.sha256(encoded).hexdigest()
            existing = [source for source in repository.courses.list_sources(course_id) if source.kind == "blueway snapshot" and source.state in {"ready", "archived"}]
            previous = next((source for source in existing if source.state == "ready"), None)
            key = _idempotency_key(
                external_subject=connection.external_subject, external_course_id=external_course_id, external_term_id=external_term_id, bundle_sha256=digest,
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
                if not build_index(
                    raw_dir.parent.parent,
                    [str(bundle_path)],
                    source_content_sha256=source.content_sha256,
                ):
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
                ensure_ready_bundle_index(
                    repository, course_id=course_id, source=source
                )
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
