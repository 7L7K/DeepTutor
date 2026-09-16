"""Readable projections of immutable, owner-authorized BlueWay course sources."""

from __future__ import annotations

import hashlib
import json

from .repository import CourseConflictError, CourseNotFoundError

GROUPS = {
    "transcripts": "Lectures",
    "assignments": "Assignments",
    "syllabus_facts": "Syllabus",
    "source_texts": "Documents",
    "class_notes": "Notes",
    "capture_notes": "Notes",
    "course_profiles": "Course information",
    "class_meetings": "Schedule",
    "schedule_events": "Schedule",
    "class_links": "Course information",
}
LABELS = {
    "body": "Notes",
    "text": "Text",
    "value": "Details",
    "details": "Instructions",
    "due_at": "Due",
    "status": "Status",
    "submission_method": "Submission",
    "grading_note": "Grading",
    "instructor_name": "Instructor",
    "term": "Semester",
    "days": "Days",
    "start_time": "Starts",
    "end_time": "Ends",
    "room": "Room",
    "location_text": "Location",
    "date": "Date",
    "starts_at": "Starts",
    "ends_at": "Ends",
    "notes": "Notes",
    "label": "Label",
    "link_type": "Link type",
}


def material_id(kind: str, record: dict) -> str:
    return hashlib.sha256(f"{kind}:{record.get('id', '')}".encode()).hexdigest()[:24]


def project_materials(records: list[dict]) -> list[dict]:
    captures = {
        x["record"].get("id"): x["record"]
        for x in records
        if x.get("kind") == "capture_metadata" and isinstance(x.get("record"), dict)
    }
    result = []
    for item in records:
        kind, record = item.get("kind"), item.get("record")
        if kind not in GROUPS or not isinstance(record, dict):
            continue
        capture = captures.get(record.get("capture_id"), {})
        title = record.get("title") or record.get("display_name") or capture.get("recording_name")
        if not title:
            title = {
                "transcripts": "Lecture transcript",
                "syllabus_facts": "Syllabus detail",
                "class_notes": "Class notes",
                "capture_notes": "Lecture notes",
            }.get(kind, GROUPS[kind])
        segments = record.get("segments", []) if kind == "transcripts" else []
        fields = [
            {"label": label, "text": str(record[key])}
            for key, label in LABELS.items()
            if record.get(key) is not None and str(record[key]).strip()
        ]
        result.append(
            {
                "id": material_id(kind, record),
                "kind": kind,
                "group": GROUPS[kind],
                "title": str(title),
                "date": record.get("recorded_at")
                or capture.get("recorded_at")
                or capture.get("meeting_date")
                or record.get("due_at")
                or record.get("date"),
                "fields": fields,
                "segments": segments,
                "notice": "Extracted syllabus information; this may not be the complete syllabus."
                if kind == "syllabus_facts"
                else None,
            }
        )
    if len({item["id"] for item in result}) != len(result):
        raise CourseConflictError("Material identifiers are ambiguous")
    return result


def source_materials(
    service,
    course_id: str,
    source_id: str,
    *,
    revision: int | None = None,
    content_hash: str | None = None,
    item_id: str | None = None,
    include_content: bool = False,
) -> dict:
    from deeptutor.integrations.blueway.bundles import (
        BundleMaterializationError,
        _ready_bundle_path,
    )
    from deeptutor.integrations.blueway.repository import BlueWayRepository

    from .chat_contract import classify_course_chat_sources

    source = service.get_source(course_id, source_id)
    if source.id not in {
        item.source_id
        for item in classify_course_chat_sources(
            service.list_sources(course_id), course_id=course_id
        ).ready_sources
    }:
        raise CourseConflictError(
            "This material version is no longer available. Refresh Materials for the current version."
        )
    if (revision is not None and revision != source.revision) or (
        content_hash is not None and content_hash != source.content_sha256
    ):
        raise CourseConflictError(
            "This material version is no longer available. Refresh Materials for the current version."
        )
    if source.kind != "blueway snapshot":
        raise CourseConflictError("A readable BlueWay collection is required")
    try:
        _, path = _ready_bundle_path(
            BlueWayRepository(service.repository), course_id=course_id, source=source
        )
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source.content_sha256:
            raise ValueError("Source changed during read")
        payload = json.loads(raw)
    except (BundleMaterializationError, OSError, ValueError) as exc:
        raise CourseConflictError(
            "Material content could not be verified. Refresh and try again."
        ) from exc
    items = project_materials(payload["records"])
    if item_id is not None:
        items = [item for item in items if item["id"] == item_id]
        if not items:
            raise CourseNotFoundError("Material not found")
    elif not include_content:
        items = [
            {key: value for key, value in item.items() if key not in {"fields", "segments"}}
            for item in items
        ]
    return {
        "source_id": source.id,
        "revision": source.revision,
        "content_hash": source.content_sha256,
        "items": items,
    }


def search_blueway_materials(
    service, course_context: dict, kb_name: str, query: str
) -> dict | None:
    """Search verified course content locally and emit server-owned item references.

    None delegates non-BlueWay sources to their existing retrieval provider.
    Empty matches intentionally carry no citation authority.
    """
    import re

    from .service import source_kb_name

    course_id = str(course_context.get("course_id") or "")
    source_id = next(
        (
            sid
            for sid in course_context.get("source_ids", [])
            if kb_name
            in {source_kb_name(course_id, sid), "personal:kb:" + source_kb_name(course_id, sid)}
        ),
        None,
    )
    if source_id is None:
        raise CourseNotFoundError("Source not attached to this course turn")
    source = service.get_source(course_id, source_id)
    if source.kind != "blueway snapshot":
        return None
    revision = course_context.get("source_revisions", {}).get(source_id)
    fingerprint = course_context.get("source_fingerprints", {}).get(source_id)
    if not isinstance(revision, int) or not isinstance(fingerprint, str) or not fingerprint:
        raise CourseConflictError("Material reference is incomplete")
    collection = source_materials(
        service,
        course_id,
        source_id,
        revision=course_context.get("source_revisions", {}).get(source_id),
        content_hash=course_context.get("source_fingerprints", {}).get(source_id),
        include_content=True,
    )
    stop = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "what",
        "when",
        "how",
        "why",
        "can",
        "could",
        "you",
        "me",
        "my",
        "this",
        "that",
        "we",
        "in",
        "on",
        "to",
        "of",
        "for",
        "and",
        "it",
        "do",
        "does",
        "did",
        "please",
        "about",
        "from",
        "with",
    }
    terms = set(re.findall(r"\w+", query.lower())) - stop
    terms |= {term[:-1] for term in terms if term.endswith("s") and len(term) > 4}
    if "midterm" in terms:
        terms.update({"exam", "midterm"})
    if {"course", "name"} <= terms or {"class", "name"} <= terms:
        terms.add("information")
    lecture_query = bool(terms & {"lecture", "lectures", "transcript", "transcripts", "professor"})
    latest = lecture_query and bool(terms & {"last", "latest", "recent"})
    items = collection["items"]
    dated_lectures = sorted(
        [i for i in items if i["kind"] == "transcripts" and i["date"]],
        key=lambda i: i["date"],
        reverse=True,
    )
    latest_id = dated_lectures[0]["id"] if latest and dated_lectures else None
    candidates = []
    for item in items:
        if latest_id and item["kind"] == "transcripts" and item["id"] != latest_id:
            continue
        header = f"{item['group']}: {item['title']}" + (
            f" ({item['date']})" if item["date"] else ""
        )
        if latest and item["kind"] == "transcripts":
            header += "\nRecency is based only on available recording dates; undated lectures cannot be ordered."
        if item["notice"]:
            header += "\n" + item["notice"]
        if item["segments"]:
            # Small overlapping windows allow a topic near the end of a lecture to be found.
            segments = item["segments"]
            passages = [
                (
                    index,
                    "\n".join(
                        f"[{s['start_ms'] // 60000}:{s['start_ms'] // 1000 % 60:02d}] {s['text']}"
                        for s in segments[index : index + 8]
                    ),
                )
                for index in range(0, len(segments), 6)
            ]
        else:
            body = "\n".join(f"{f['label']}: {f['text']}" for f in item["fields"])
            if not body and item["kind"] == "course_profiles":
                body = item["title"]
            passages = [
                (index, body[index : index + 2400]) for index in range(0, max(1, len(body)), 1800)
            ]
        for index, body in passages:
            text = header + "\n" + body
            words = set(re.findall(r"\w+", text.lower()))
            score = len(terms & words)
            if lecture_query and item["kind"] == "transcripts":
                score += 1
            if latest_id == item["id"]:
                score += 4
            if not score or not body.strip():
                continue
            candidates.append((score, item, index, text[:3200]))
    candidates.sort(key=lambda v: (-v[0], v[1]["id"], v[2]))
    selected = []
    remaining = 3800
    for candidate in candidates[:4]:
        score, item, index, text = candidate
        if remaining < 200:
            break
        excerpt = text[:remaining]
        selected.append((score, item, index, excerpt))
        remaining -= len(excerpt) + 2
    sources = [
        {
            "source_id": source_id,
            "kb_name": kb_name,
            "title": item["title"],
            "section": item["title"],
            "fragment_id": f"material:{item['id']}:{index}",
            "content": text,
        }
        for _, item, index, text in selected
    ]
    for provenance, (_, item, index, _) in zip(sources, selected):
        if item["segments"]:
            seconds = item["segments"][index]["start_ms"] // 1000
            provenance["timestamp"] = f"{seconds // 60}:{seconds % 60:02d}"
    return {
        "content": "\n\n".join(text for _, _, _, text in selected),
        "sources": sources,
        "course_material_retrieval": True,
        "missing_evidence": not bool(selected),
    }
