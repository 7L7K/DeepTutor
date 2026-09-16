import hashlib
import json
from types import SimpleNamespace

import pytest

from deeptutor.courses.materials import project_materials, source_materials
from deeptutor.courses.repository import CourseConflictError, CourseNotFoundError, CourseRepository
from deeptutor.courses.service import CourseService, source_kb_name

RECORDS = [
    {
        "kind": "capture_metadata",
        "record": {
            "id": "cap1",
            "recording_name": "Lecture one",
            "recorded_at": "2026-09-15T10:00:00Z",
        },
    },
    {
        "kind": "transcripts",
        "record": {
            "id": "t1",
            "capture_id": "cap1",
            "segments": [{"start_ms": 1200, "end_ms": 2000, "text": "Evidence from the lecture."}],
        },
    },
    {
        "kind": "syllabus_facts",
        "record": {"id": "s1", "title": "Late work", "value": "Accepted within two days."},
    },
    {
        "kind": "assignments",
        "record": {
            "id": "a1",
            "title": "Homework",
            "details": "Show your work.",
            "due_at": "2026-09-20",
        },
    },
    {"kind": "courses", "record": {"id": "c1", "title": "Internal metadata"}},
]


@pytest.fixture
def material_source(tmp_path, monkeypatch):
    from deeptutor.integrations.blueway import bundles

    repo = CourseRepository(tmp_path / "courses.db", "alice")
    course = repo.create_course("Physics")
    raw = json.dumps(
        {"schema": "teeechr.blueway.course-bundle.v1", "course_id": course.id, "records": RECORDS}
    ).encode()
    source = repo.create_source(
        course.id,
        kind="blueway snapshot",
        display_name="Bundle",
        manifest=[],
        content_sha256=hashlib.sha256(raw).hexdigest(),
    )
    source = repo.transition_source(
        course.id,
        source.id,
        operation_id=source.operation_id,
        expected_source_revision=source.revision,
        expected_course_revision=course.revision,
        expected_write_epoch=course.write_epoch,
        state="ready",
    )
    root = tmp_path / "kb"
    file = (
        root
        / source_kb_name(course.id, source.id)
        / "raw"
        / source.id
        / "blueway-course-bundle.json"
    )
    file.parent.mkdir(parents=True)
    file.write_bytes(raw)
    monkeypatch.setattr(
        bundles,
        "get_personal_path_service",
        lambda owner: SimpleNamespace(get_knowledge_bases_root=lambda: root),
    )
    return CourseService(repo), course, source, file


def test_groups_real_content_without_metadata_or_fake_full_syllabus():
    items = project_materials(RECORDS)
    assert len(items) == 3
    assert items[0]["title"] == "Lecture one"
    assert items[0]["segments"][0]["start_ms"] == 1200
    assert "not be the complete syllabus" in items[1]["notice"]
    assert any(f["label"] == "Instructions" for f in items[2]["fields"])
    assert project_materials(list(reversed(RECORDS)))[-1]["id"] == items[0]["id"]


def test_summary_then_exact_detail(material_source):
    service, course, source, _ = material_source
    result = source_materials(service, course.id, source.id)
    assert len(result["items"]) == 3
    assert "segments" not in result["items"][0]
    detail = source_materials(
        service,
        course.id,
        source.id,
        item_id=result["items"][0]["id"],
        revision=source.revision,
        content_hash=source.content_sha256,
    )
    assert detail["items"][0]["segments"][0]["text"] == "Evidence from the lecture."
    with pytest.raises(CourseNotFoundError):
        source_materials(service, course.id, source.id, item_id="missing")


@pytest.mark.parametrize("kwargs", [{"revision": 999}, {"content_hash": "wrong"}])
def test_stale_reference_fails(material_source, kwargs):
    service, course, source, _ = material_source
    with pytest.raises(CourseConflictError, match="no longer available"):
        source_materials(service, course.id, source.id, **kwargs)


def test_owner_and_course_boundary(material_source, tmp_path):
    service, course, source, _ = material_source
    stranger = CourseService(CourseRepository(tmp_path / "courses.db", "bob"))
    with pytest.raises(CourseNotFoundError):
        source_materials(stranger, course.id, source.id)
    other = service.repository.create_course("Other")
    with pytest.raises(CourseNotFoundError):
        source_materials(service, other.id, source.id)


def test_tampered_bundle_fails(material_source):
    service, course, source, file = material_source
    file.write_text("{}")
    with pytest.raises(CourseConflictError, match="could not be verified"):
        source_materials(service, course.id, source.id)


def test_archived_source_unavailable(material_source):
    service, course, source, _ = material_source
    with service.repository._connect() as conn:
        conn.execute("UPDATE course_sources SET state='archived' WHERE id=?", (source.id,))
    with pytest.raises(CourseConflictError, match="no longer available"):
        source_materials(service, course.id, source.id)


def test_retrieval_returns_exact_syllabus_item_and_abstains_on_missing_policy(material_source):
    from deeptutor.courses.materials import search_blueway_materials

    service, course, source, _ = material_source
    ctx = {
        "course_id": course.id,
        "source_ids": [source.id],
        "source_revisions": {source.id: source.revision},
        "source_fingerprints": {source.id: source.content_sha256},
    }
    kb = "personal:kb:" + source_kb_name(course.id, source.id)
    result = search_blueway_materials(service, ctx, kb, "What is the late work policy?")
    assert "Accepted within two days" in result["content"]
    assert result["sources"][0]["title"] == "Late work"
    item_id = result["sources"][0]["fragment_id"].split(":")[1]
    opened = source_materials(service, course.id, source.id, item_id=item_id)
    assert opened["items"][0]["title"] == "Late work"
    missing = search_blueway_materials(service, ctx, kb, "What is the attendance policy?")
    assert missing["missing_evidence"] and not missing["sources"]
    with pytest.raises(CourseNotFoundError):
        search_blueway_materials(service, ctx, "foreign-kb", "late work")


def test_retrieval_finds_end_of_long_transcript_and_preserves_locator(material_source):
    from deeptutor.courses.materials import search_blueway_materials

    service, course, source, file = material_source
    payload = json.loads(file.read_text())
    transcript = payload["records"][1]["record"]
    transcript["segments"] = [
        {
            "start_ms": i * 1000,
            "end_ms": (i + 1) * 1000,
            "text": "Ordinary discussion."
            if i < 100
            else "Gradient descent converges iteratively.",
        }
        for i in range(101)
    ]
    raw = json.dumps(payload).encode()
    file.write_bytes(raw)
    fingerprint = hashlib.sha256(raw).hexdigest()
    with service.repository._connect() as conn:
        conn.execute(
            "UPDATE course_sources SET content_sha256=? WHERE id=?", (fingerprint, source.id)
        )
    ctx = {
        "course_id": course.id,
        "source_ids": [source.id],
        "source_revisions": {source.id: source.revision},
        "source_fingerprints": {source.id: fingerprint},
    }
    result = search_blueway_materials(
        service, ctx, source_kb_name(course.id, source.id), "Explain gradient descent"
    )
    assert "Gradient descent" in result["content"]
    assert result["sources"][0]["fragment_id"].endswith(":96")


@pytest.mark.asyncio
async def test_real_rag_tool_reads_course_bundle_without_provider(material_source, monkeypatch):
    from deeptutor.courses import service as services
    from deeptutor.tools import rag_tool
    from deeptutor.tools.builtin import RAGTool

    service, course, source, _ = material_source
    monkeypatch.setattr(services, "get_current_course_service", lambda: service)

    async def forbidden(**kwargs):
        raise AssertionError("BlueWay local retrieval must not call generic provider")

    monkeypatch.setattr(rag_tool, "rag_search", forbidden)
    context = {
        "course_id": course.id,
        "source_ids": [source.id],
        "source_revisions": {source.id: source.revision},
        "source_fingerprints": {source.id: source.content_sha256},
    }
    tool = RAGTool()
    result = await tool.execute(
        query="late work policy",
        kb_name=source_kb_name(course.id, source.id),
        _course_context=context,
    )
    assert "Accepted within two days" in result.content
    assert result.sources[0]["fragment_id"].startswith("material:")
    empty = await tool.execute(
        query="attendance policy",
        kb_name=source_kb_name(course.id, source.id),
        _course_context=context,
    )
    assert not empty.sources


def test_material_endpoint_revision_and_item_contract(material_source, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from deeptutor.api.routers import courses

    service, course, source, _ = material_source
    monkeypatch.setattr(courses, "_service", lambda: service)
    app = FastAPI()
    app.include_router(courses.router, prefix="/api/v1/courses")
    client = TestClient(app)
    url = f"/api/v1/courses/{course.id}/sources/{source.id}/materials"
    response = client.get(
        url, params={"revision": source.revision, "content_hash": source.content_sha256}
    )
    assert response.status_code == 200
    item = response.json()["items"][0]["id"]
    assert client.get(url, params={"item_id": item}).json()["items"][0]["segments"]
    assert client.get(url, params={"revision": 999}).status_code == 409
    assert client.get(url, params={"item_id": "absent"}).status_code == 404
    assert client.get(url.replace(course.id, "foreign")).status_code == 404
