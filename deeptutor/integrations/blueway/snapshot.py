"""Exact, offline validation for the narrow versioned BlueWay export."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any


class SnapshotValidationError(ValueError):
    pass


DATASETS = frozenset({
    "courses", "class_meetings", "schedule_events", "assignments", "class_notes",
    "class_links", "course_profiles", "syllabus_facts", "source_texts",
    "capture_metadata", "capture_notes", "transcripts",
})
MAX_RECORDS_PER_PAGE = 500
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_RECORD_BYTES = 64 * 1024
MAX_NOTE_BYTES = 32 * 1024
MAX_SOURCE_TEXT_BYTES = 2 * 1024 * 1024
MAX_TRANSCRIPT_BYTES = 5 * 1024 * 1024
_COMMON = {"id", "revision", "content_sha256", "state"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT_ID = re.compile(r"^bws_[0-9a-f]{64}$")
_FIELDS: dict[str, set[str]] = {
    "courses": _COMMON | {"course_id", "term_id", "title"},
    "class_meetings": _COMMON | {"course_id", "term_id", "title", "days", "start_time", "end_time", "room", "location_text"},
    "schedule_events": _COMMON | {"course_id", "title", "date", "starts_at", "ends_at", "all_day", "notes"},
    "assignments": _COMMON | {"course_id", "title", "due_at", "details", "submission_method", "grading_note", "status"},
    "class_notes": _COMMON | {"course_id", "body"},
    "class_links": _COMMON | {"course_id", "label", "link_type"},
    "course_profiles": _COMMON | {"course_id", "term_id", "title", "display_name", "term", "instructor_name"},
    "syllabus_facts": _COMMON | {"course_id", "kind", "title", "value"},
    "source_texts": _COMMON | {"course_id", "title", "text", "source_kind"},
    "capture_metadata": _COMMON | {
        "course_id", "content_hash", "content_version", "duration_ms", "completed_at",
        "metadata_version", "course_name_snapshot", "meeting_date", "meeting_binding_status",
        "schedule_item_id", "scheduled_start_at", "scheduled_end_at", "recording_name",
        "recorded_at", "stopped_at", "schedule_event_id",
    },
    "capture_notes": _COMMON | {"course_id", "capture_id", "body"},
    "transcripts": _COMMON | {"course_id", "capture_id", "recorded_at", "stopped_at", "duration_ms", "language", "layer", "segments"},
}


def _stable_json(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(f"{json.dumps(key, ensure_ascii=False)}:{_stable_json(value[key])}" for key in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_stable_json(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def canonical_snapshot_hash(snapshot: dict[str, Any]) -> str:
    payload = dict(snapshot)
    payload.pop("payload_sha256", None)
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _bytes(value: Any) -> int:
    return len(_stable_json(value).encode("utf-8"))


def _text(value: Any, *, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value.encode("utf-8")) <= limit


def _validate_record(kind: str, record: Any) -> None:
    if not isinstance(record, dict) or set(record) - _FIELDS[kind] or not _COMMON.issubset(record):
        raise SnapshotValidationError("BlueWay record has undeclared or missing fields")
    record_limit = MAX_TRANSCRIPT_BYTES if kind == "transcripts" else MAX_SOURCE_TEXT_BYTES if kind == "source_texts" else MAX_RECORD_BYTES
    if _bytes(record) > record_limit:
        raise SnapshotValidationError("BlueWay record exceeds the 64 KiB limit")
    if not _text(record["id"], limit=256) or not all(isinstance(record[field], str) and _HEX64.fullmatch(record[field]) for field in ("revision", "content_sha256")):
        raise SnapshotValidationError("BlueWay record identity or hash is invalid")
    if not isinstance(record["state"], str) or record["state"] not in {"current", "archived", "unlinked"}:
        raise SnapshotValidationError("BlueWay record state is invalid")
    course_id = record.get("course_id")
    if course_id is not None and not _text(course_id, limit=256):
        raise SnapshotValidationError("BlueWay course_id is invalid")
    if "term_id" in record and record["term_id"] is not None and not _text(record["term_id"], limit=256):
        raise SnapshotValidationError("BlueWay term_id is invalid")
    if kind == "courses" and (
        record.get("course_id") != record["id"]
        or record["state"] != "current"
        or not _text(record.get("title"), limit=256)
    ):
        raise SnapshotValidationError("BlueWay course identity/title is invalid")
    if kind == "capture_metadata" and "schedule_event_id" in record and not _text(record["schedule_event_id"], limit=128):
        raise SnapshotValidationError("BlueWay capture schedule event identity is invalid")
    # The export is intentionally scalar-only outside transcript segments.
    # Accept omitted optional fields, but never provider-shaped objects.
    for field, value in record.items():
        if field in _COMMON or field == "course_id":
            continue
        if kind == "class_meetings" and field == "days":
            if not isinstance(value, list) or not all(_text(day, limit=16) for day in value):
                raise SnapshotValidationError("BlueWay meeting days are invalid")
            continue
        if kind == "transcripts" and field in {"segments", "duration_ms"}:
            continue
        if value is not None and not isinstance(value, str):
            raise SnapshotValidationError("BlueWay optional field type is invalid")
    if kind in {"class_notes", "capture_notes"} and "body" in record and not _text(record["body"], limit=MAX_NOTE_BYTES):
        raise SnapshotValidationError("BlueWay note exceeds the 32 KiB limit")
    if kind == "source_texts" and "text" in record and not _text(record["text"], limit=MAX_SOURCE_TEXT_BYTES):
        raise SnapshotValidationError("BlueWay source text exceeds the 2 MiB limit")
    if kind == "transcripts":
        if record.get("layer") not in {"raw", "cleaned", "derived"} or not isinstance(record.get("segments"), list):
            raise SnapshotValidationError("BlueWay transcript contract is invalid")
        duration = record.get("duration_ms")
        if duration is not None and (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or not 0 <= duration <= 14_400_000
        ):
            raise SnapshotValidationError("BlueWay transcript duration is invalid")
        timestamps = {}
        for field in ("recorded_at", "stopped_at"):
            if field in record and (not isinstance(record[field], str) or not _text(record[field], limit=64)):
                raise SnapshotValidationError("BlueWay transcript timestamp is invalid")
            if field in record:
                from datetime import datetime
                try:
                    parsed = datetime.fromisoformat(record[field].replace("Z", "+00:00"))
                    if parsed.tzinfo is None or parsed.utcoffset() is None:
                        raise ValueError("timezone required")
                    timestamps[field] = parsed
                except ValueError as exc:
                    raise SnapshotValidationError("BlueWay transcript timestamp is invalid") from exc
        if timestamps.get("recorded_at") and timestamps.get("stopped_at") and timestamps["recorded_at"] > timestamps["stopped_at"]:
            raise SnapshotValidationError("BlueWay transcript timestamp is invalid")
        if "language" in record and (not isinstance(record["language"], str) or not _text(record["language"], limit=32)):
            raise SnapshotValidationError("BlueWay transcript language is invalid")
        if _bytes(record) > MAX_TRANSCRIPT_BYTES:
            raise SnapshotValidationError("BlueWay transcript exceeds the 5 MiB limit")
        previous_end = 0
        for segment in record["segments"]:
            if not isinstance(segment, dict) or set(segment) != {"start_ms", "end_ms", "text"}:
                raise SnapshotValidationError("BlueWay transcript segment is invalid")
            if (not isinstance(segment["start_ms"], int) or isinstance(segment["start_ms"], bool)
                or not isinstance(segment["end_ms"], int) or isinstance(segment["end_ms"], bool)
                or segment["start_ms"] < previous_end or segment["end_ms"] < segment["start_ms"]
                or (duration is not None and segment["end_ms"] > duration)
                or not _text(segment["text"], limit=MAX_NOTE_BYTES)):
                raise SnapshotValidationError("BlueWay transcript segment is invalid")
            previous_end = segment["end_ms"]


def validate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Validate one response before it can affect persistent course state."""
    required = {"schema_version", "snapshot_id", "snapshot_revision", "generated_at", "complete", "next_cursor", "datasets", "unavailable", "payload_sha256"}
    if not isinstance(snapshot, dict) or set(snapshot) != required or snapshot.get("schema_version") != 1:
        raise SnapshotValidationError("Unsupported BlueWay snapshot schema")
    if not isinstance(snapshot["snapshot_id"], str) or not _SNAPSHOT_ID.fullmatch(snapshot["snapshot_id"]) or not isinstance(snapshot["snapshot_revision"], int) or isinstance(snapshot["snapshot_revision"], bool) or not 1 <= snapshot["snapshot_revision"] <= 9_007_199_254_740_991 or not _text(snapshot["generated_at"], limit=64):
        raise SnapshotValidationError("BlueWay snapshot identity is invalid")
    try:
        from datetime import datetime
        datetime.fromisoformat(snapshot["generated_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotValidationError("BlueWay snapshot timestamp is invalid") from exc
    if not isinstance(snapshot["complete"], bool) or (snapshot["complete"] and snapshot["next_cursor"] is not None) or (not snapshot["complete"] and not _text(snapshot["next_cursor"], limit=512)):
        raise SnapshotValidationError("BlueWay snapshot completeness/cursor is invalid")
    datasets = snapshot["datasets"]
    if not isinstance(datasets, dict) or set(datasets) != DATASETS or _bytes(snapshot) > MAX_PAGE_BYTES:
        raise SnapshotValidationError("BlueWay datasets are invalid or page exceeds 5 MiB")
    unavailable = snapshot["unavailable"]
    if not isinstance(unavailable, list) or any(
        not isinstance(item, dict)
        or set(item) != {"dataset", "reason"}
        or not _text(item["dataset"], limit=64)
        or item["dataset"] not in DATASETS
        or not _text(item["reason"], limit=256)
        for item in unavailable
    ) or len({item["dataset"] for item in unavailable}) != len(unavailable):
        raise SnapshotValidationError("BlueWay unavailable list is invalid")
    if any(datasets[item["dataset"]] for item in unavailable):
        raise SnapshotValidationError("BlueWay unavailable dataset cannot include records")
    if not isinstance(snapshot["payload_sha256"], str) or snapshot["payload_sha256"] != canonical_snapshot_hash(snapshot):
        raise SnapshotValidationError("BlueWay snapshot hash mismatch")
    total, seen = 0, set()
    for kind, records in datasets.items():
        if not isinstance(records, list):
            raise SnapshotValidationError("BlueWay dataset is invalid")
        for record in records:
            _validate_record(kind, record)
            identity = (kind, record["id"])
            if identity in seen:
                raise SnapshotValidationError("BlueWay snapshot contains duplicate record ids")
            seen.add(identity)
            total += 1
    if total > MAX_RECORDS_PER_PAGE:
        raise SnapshotValidationError("BlueWay page exceeds the 500-record limit")
    return snapshot


def validate_snapshot_fixture(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotValidationError("BlueWay fixture is unreadable") from exc
    return validate_snapshot(payload)
