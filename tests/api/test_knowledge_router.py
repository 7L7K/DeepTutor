from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

try:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - optional dependency in lightweight envs
    Depends = None
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)

if FastAPI is not None and TestClient is not None:
    knowledge_router_module = importlib.import_module("deeptutor.api.routers.knowledge")
    router = knowledge_router_module.router
else:  # pragma: no cover - optional dependency in lightweight envs
    knowledge_router_module = None
    router = None


def _build_app() -> FastAPI:
    if FastAPI is None or router is None:  # pragma: no cover - guarded by pytestmark
        raise RuntimeError("fastapi is not installed")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/knowledge")
    return app


class _FakeKBManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.base_dir / "kb_config.json"
        self.config: dict[str, dict] = {"knowledge_bases": {}}

    def _load_config(self) -> dict:
        return self.config

    def _save_config(self) -> None:
        pass

    def list_knowledge_bases(self) -> list[str]:
        return sorted(self.config.get("knowledge_bases", {}).keys())

    def update_kb_status(self, name: str, status: str, progress: dict | None = None) -> None:
        entry = self.config.setdefault("knowledge_bases", {}).setdefault(name, {"path": name})
        entry["status"] = status
        entry["progress"] = progress or {}

    def get_default(self) -> str | None:
        names = self.list_knowledge_bases()
        return names[0] if names else None

    def get_knowledge_base_path(self, name: str) -> Path:
        kb_dir = self.base_dir / name
        kb_dir.mkdir(parents=True, exist_ok=True)
        return kb_dir

    def register_lightrag_server_kb(
        self,
        name: str,
        server_url: str,
        *,
        api_key: str = "",
        search_mode: str = "",
        description: str = "",
    ) -> dict:
        if name in self.config.get("knowledge_bases", {}):
            raise ValueError(f"A knowledge base named '{name}' already exists.")
        entry = {
            "path": name,
            "type": "lightrag_server",
            "rag_provider": "lightrag-server",
            "server_url": server_url,
            "api_key": api_key,
            "status": "ready",
        }
        if search_mode:
            entry["search_mode"] = search_mode
        self.config.setdefault("knowledge_bases", {})[name] = entry
        return entry


class _FakeInitializer:
    def __init__(self, kb_name: str, base_dir: str, **_kwargs) -> None:
        self.kb_name = kb_name
        self.base_dir = base_dir
        self.kb_dir = Path(base_dir) / kb_name
        self.raw_dir = self.kb_dir / "raw"
        self.progress_tracker = _kwargs.get("progress_tracker")

    def create_directory_structure(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def _register_to_config(self) -> None:
        pass


def _upload_payload() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", ("demo.txt", b"hello", "text/plain"))]


def _invalid_upload_payload() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", ("archive.zip", b"PK\x03\x04", "application/zip"))]


def _uppercase_upload_payload() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", ("报告.PDF", b"%PDF-1.4\n", "application/pdf"))]


def _write_ready_llamaindex_version(kb_dir: Path) -> None:
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"provider": "llamaindex", "signature": "sig", "version": "version-1"}),
        encoding="utf-8",
    )


def test_rag_providers_lists_llamaindex_and_pageindex() -> None:
    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/knowledge/rag-providers")

    assert response.status_code == 200
    payload = response.json()
    by_id = {p["id"]: p for p in payload["providers"]}
    assert set(by_id) == {
        "llamaindex",
        "pageindex",
        "graphrag",
        "lightrag",
        "lightrag-server",
        "ima",
    }
    # LlamaIndex works out of the box; PageIndex needs an API key; GraphRAG and
    # LightRAG are optional local engines (no API key, configured = installed).
    assert by_id["llamaindex"]["requires_api_key"] is False
    assert by_id["pageindex"]["requires_api_key"] is True
    assert by_id["graphrag"]["requires_api_key"] is False
    assert by_id["lightrag"]["requires_api_key"] is False
    # LightRAG Server is a thin HTTP client: always available, no API key gate
    # (the per-KB endpoint is configured at connect time).
    assert by_id["lightrag-server"]["requires_api_key"] is False
    assert by_id["lightrag-server"]["configured"] is True
    # Same for IMA: a thin HTTPS client, credentials bound per-KB at connect
    # time rather than gated by one global key.
    assert by_id["ima"]["requires_api_key"] is False
    assert by_id["ima"]["configured"] is True
    # Mode-aware engines advertise their retrieval modes; vector engines don't.
    assert "hybrid" in by_id["lightrag"]["modes"]
    assert "mix" in by_id["lightrag-server"]["modes"]
    assert not by_id["llamaindex"].get("modes")
    # IMA exposes a single retrieval call, so it advertises no modes.
    assert not by_id["ima"].get("modes")


def test_set_rag_provider_mode_persists_validates_and_reflects() -> None:
    with TestClient(_build_app()) as client:
        ok = client.put("/api/v1/knowledge/rag-providers/lightrag/mode", json={"mode": "MIX"})
        assert ok.status_code == 200
        assert ok.json()["mode"] == "mix"  # normalized

        providers = client.get("/api/v1/knowledge/rag-providers").json()["providers"]
        by_id = {p["id"]: p for p in providers}
        assert by_id["lightrag"]["default_mode"] == "mix"

        # Invalid mode for the engine → 400; mode-less engine → 404.
        assert (
            client.put(
                "/api/v1/knowledge/rag-providers/lightrag/mode", json={"mode": "bogus"}
            ).status_code
            == 400
        )
        assert (
            client.put(
                "/api/v1/knowledge/rag-providers/llamaindex/mode", json={"mode": "x"}
            ).status_code
            == 404
        )


def test_supported_file_types_returns_upload_policy() -> None:
    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/knowledge/supported-file-types")

    assert response.status_code == 200
    payload = response.json()
    assert ".pdf" in payload["extensions"]
    assert ".docx" in payload["extensions"]
    assert ".xlsx" in payload["extensions"]
    assert ".pptx" in payload["extensions"]
    assert ".md" in payload["extensions"]
    assert ".png" in payload["extensions"]
    assert payload["max_file_size_bytes"] > 0
    assert "max_pdf_size_bytes" not in payload
    assert ".pdf" in payload["accept"]
    assert ".docx" in payload["accept"]
    assert ".png" in payload["accept"]
    assert "image/png" in payload["accept"]


def test_create_kb_does_not_require_llm_precheck(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "KnowledgeBaseInitializer", _FakeInitializer)
    monkeypatch.setattr(
        knowledge_router_module,
        "get_llm_config",
        lambda: (_ for _ in ()).throw(RuntimeError("should not be called")),
        raising=False,
    )

    async def _noop_init_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_initialization_task", _noop_init_task)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/create",
            data={"name": "kb-new", "rag_provider": "llamaindex"},
            files=_upload_payload(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "kb-new"
    assert isinstance(body.get("task_id"), str) and body["task_id"]
    assert manager.config["knowledge_bases"]["kb-new"]["rag_provider"] == "llamaindex"
    assert manager.config["knowledge_bases"]["kb-new"]["needs_reindex"] is False


def test_create_coerces_legacy_provider_to_llamaindex(monkeypatch, tmp_path: Path) -> None:
    """Unknown/removed provider strings silently normalize to llamaindex."""
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    async def _noop_init_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_initialization_task", _noop_init_task)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/create",
            data={"name": "kb-legacy", "rag_provider": "raganything"},
            files=_upload_payload(),
        )

    assert response.status_code == 200
    assert manager.config["knowledge_bases"]["kb-legacy"]["rag_provider"] == "llamaindex"


def test_create_preserves_known_nondefault_provider(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "KnowledgeBaseInitializer", _FakeInitializer)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    pageindex_config = importlib.import_module("deeptutor.services.rag.pipelines.pageindex.config")
    monkeypatch.setattr(pageindex_config, "is_pageindex_configured", lambda: True)

    async def _noop_init_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_initialization_task", _noop_init_task)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/create",
            data={"name": "kb-page", "rag_provider": "pageindex"},
            files=[("files", ("demo.pdf", b"%PDF-1.4\n", "application/pdf"))],
        )

    assert response.status_code == 200
    assert manager.config["knowledge_bases"]["kb-page"]["rag_provider"] == "pageindex"


def test_create_rejects_invalid_files_before_registering_kb(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/create",
            data={"name": "kb-invalid", "rag_provider": "llamaindex"},
            files=_invalid_upload_payload(),
        )

    assert response.status_code == 400
    assert "unsupported file type" in response.json()["detail"].lower()
    assert "kb-invalid" not in manager.config["knowledge_bases"]


def test_create_rejects_invalid_kb_name_before_registering_kb(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/create",
            data={"name": "bad/name", "rag_provider": "llamaindex"},
            files=_upload_payload(),
        )

    assert response.status_code == 400
    assert "reserved characters" in response.json()["detail"].lower()
    assert manager.config["knowledge_bases"] == {}


def test_create_normalizes_uploaded_extension_to_lowercase(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "KnowledgeBaseInitializer", _FakeInitializer)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    async def _noop_init_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_initialization_task", _noop_init_task)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/create",
            data={"name": "kb-uppercase", "rag_provider": "llamaindex"},
            files=_uppercase_upload_payload(),
        )

    assert response.status_code == 200
    assert response.json()["files"] == ["报告.pdf"]
    assert (tmp_path / "knowledge_bases" / "kb-uppercase" / "raw" / "报告.pdf").exists()


def test_upload_returns_409_when_kb_needs_reindex(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["legacy-kb"] = {
        "path": "legacy-kb",
        "rag_provider": "llamaindex",
        "needs_reindex": True,
        "status": "needs_reindex",
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/legacy-kb/upload", files=_upload_payload())

    assert response.status_code == 409
    assert "needs reindex" in response.json()["detail"].lower()


def test_upload_ready_kb_returns_task_id(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["ready-kb"] = {
        "path": "ready-kb",
        "rag_provider": "llamaindex",
        "needs_reindex": False,
        "status": "ready",
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    async def _noop_upload_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", _noop_upload_task)

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/ready-kb/upload", files=_upload_payload())

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("task_id"), str) and body["task_id"]


def test_upload_flips_ready_kb_to_processing_before_dispatch(monkeypatch, tmp_path: Path) -> None:
    """An existing ready KB must not keep reporting ``ready`` between the
    accepted upload response and the background task's first progress write."""
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["ready-kb"] = {
        "path": "ready-kb",
        "rag_provider": "llamaindex",
        "needs_reindex": False,
        "status": "ready",
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    async def _noop_upload_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", _noop_upload_task)

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/ready-kb/upload", files=_upload_payload())

    assert response.status_code == 200
    entry = manager.config["knowledge_bases"]["ready-kb"]
    assert entry["status"] == "processing"
    # Stage must be a member of the frontend's LIVE_PROGRESS_STAGES set.
    assert entry["progress"]["stage"] == "starting"
    assert entry["progress"]["task_id"] == response.json()["task_id"]


def test_upload_task_marks_provider_failures_as_error(monkeypatch, tmp_path: Path) -> None:
    base_dir = tmp_path / "knowledge_bases"
    kb_dir = base_dir / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    _write_ready_llamaindex_version(kb_dir)
    (base_dir / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "kb": {
                        "path": "kb",
                        "rag_provider": "llamaindex",
                        "status": "ready",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    source = tmp_path / "bad.txt"
    source.write_text("bad", encoding="utf-8")

    class _FailingRagService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def add_documents(self, *_args, **_kwargs) -> bool:
            raise RuntimeError("parse failed loudly")

    monkeypatch.setattr(
        "deeptutor.knowledge.add_documents.RAGService",
        _FailingRagService,
    )

    asyncio.run(
        knowledge_router_module.run_upload_processing_task(
            kb_name="kb",
            base_dir=str(base_dir),
            uploaded_file_paths=[str(source)],
            task_id="upload-failure-test",
            rag_provider="llamaindex",
        )
    )

    persisted = json.loads((base_dir / "kb_config.json").read_text(encoding="utf-8"))
    entry = persisted["knowledge_bases"]["kb"]
    assert entry["status"] == "error"
    assert "parse failed loudly" in entry["last_error"]
    assert entry["progress"]["stage"] == "error"
    assert entry["progress"]["indexed_count"] == 0


def test_list_files_accepts_default_alias(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["actual-kb"] = {
        "path": "actual-kb",
        "status": "ready",
    }
    raw_dir = manager.base_dir / "actual-kb" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "demo.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/knowledge/default/files")

    assert response.status_code == 200
    assert response.json()["files"][0]["name"] == "demo.txt"


def test_list_fallback_reports_error_status(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["broken-kb"] = {
        "path": "broken-kb",
        "status": "ready",
    }
    (manager.base_dir / "broken-kb").mkdir(parents=True)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/knowledge/list")

    assert response.status_code == 200
    [item] = response.json()
    assert item["status"] == "error"
    assert item["progress"]["stage"] == "error"
    assert "get_info" in item["progress"]["error"]


def _ready_kb_manager(tmp_path: Path, name: str = "kb") -> "_FakeKBManager":
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"][name] = {
        "path": name,
        "rag_provider": "llamaindex",
        "needs_reindex": False,
        "status": "ready",
    }
    (manager.base_dir / name / "raw").mkdir(parents=True, exist_ok=True)
    return manager


def test_create_folder_makes_subdir(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/kb/folders", json={"path": "Papers/2024"})

    assert response.status_code == 200
    assert response.json()["path"] == "Papers/2024"
    assert (manager.base_dir / "kb" / "raw" / "Papers" / "2024").is_dir()


def test_create_folder_rejects_traversal(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/kb/folders", json={"path": "../escape"})

    assert response.status_code == 400


def test_list_files_returns_nested_tree(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    raw = manager.base_dir / "kb" / "raw"
    (raw / "Papers").mkdir(parents=True)
    (raw / "Papers" / "a.pdf").write_text("%PDF-1.4\n", encoding="utf-8")
    (raw / "root.txt").write_text("hi", encoding="utf-8")
    (raw / "Empty").mkdir()
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/knowledge/kb/files")

    assert response.status_code == 200
    entries = {e["name"]: e for e in response.json()["files"]}
    assert entries["Papers"]["type"] == "folder"
    assert entries["Empty"]["type"] == "folder"  # empty folder still shows
    assert entries["Papers/a.pdf"]["type"] == "file"
    assert entries["root.txt"]["type"] == "file"


def test_upload_preserves_folder_structure(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    async def _noop_upload_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", _noop_upload_task)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/kb/upload",
            files=[("files", ("note.txt", b"hi", "text/plain"))],
            data={"rel_paths": "MyFolder/sub/note.txt"},
        )

    assert response.status_code == 200
    assert (manager.base_dir / "kb" / "raw" / "MyFolder" / "sub" / "note.txt").is_file()


def test_upload_allows_same_filename_in_different_folders(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    async def _noop_upload_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", _noop_upload_task)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/kb/upload",
            files=[
                ("files", ("note.txt", b"one", "text/plain")),
                ("files", ("note.txt", b"two", "text/plain")),
            ],
            data={"rel_paths": ["ModuleA/note.txt", "ModuleB/note.txt"]},
        )

    assert response.status_code == 200
    assert (manager.base_dir / "kb" / "raw" / "ModuleA" / "note.txt").is_file()
    assert (manager.base_dir / "kb" / "raw" / "ModuleB" / "note.txt").is_file()


def test_move_file_into_folder(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    raw = manager.base_dir / "kb" / "raw"
    (raw / "demo.txt").write_text("hi", encoding="utf-8")
    (raw / "Papers").mkdir()
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/kb/files/move",
            json={"source": "demo.txt", "dest_folder": "Papers"},
        )

    assert response.status_code == 200
    assert (raw / "Papers" / "demo.txt").is_file()
    assert not (raw / "demo.txt").exists()


def test_list_files_preserves_kb_named_default(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["actual-kb"] = {
        "path": "actual-kb",
        "status": "ready",
    }
    manager.config["knowledge_bases"]["default"] = {
        "path": "default",
        "status": "ready",
    }
    actual_raw = manager.base_dir / "actual-kb" / "raw"
    actual_raw.mkdir(parents=True)
    (actual_raw / "actual.txt").write_text("hello", encoding="utf-8")
    default_raw = manager.base_dir / "default" / "raw"
    default_raw.mkdir(parents=True)
    (default_raw / "default.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/knowledge/default/files")

    assert response.status_code == 200
    assert response.json()["files"][0]["name"] == "default.txt"


@pytest.mark.parametrize(
    ("filename", "payload", "mime_type", "disposition", "has_active_csp"),
    [
        (
            "lesson.html",
            b"<script>window.pwned = true</script>",
            "text/html",
            "attachment",
            True,
        ),
        (
            "diagram.svg",
            b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
            "image/svg+xml",
            "attachment",
            True,
        ),
        ("notes.txt", b"safe course notes", "text/plain", "inline", False),
        ("cover.png", b"\x89PNG\r\n\x1a\n", "image/png", "inline", False),
    ],
)
def test_uploaded_kb_file_response_blocks_active_content(
    monkeypatch,
    tmp_path: Path,
    filename: str,
    payload: bytes,
    mime_type: str,
    disposition: str,
    has_active_csp: bool,
) -> None:
    """Raw KB downloads must not turn uploaded markup into same-origin code."""
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    async def _noop_upload_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", _noop_upload_task)

    with TestClient(_build_app()) as client:
        uploaded = client.post(
            "/api/v1/knowledge/kb/upload",
            files=[("files", (filename, payload, mime_type))],
        )
        response = client.get(f"/api/v1/knowledge/kb/files/{filename}")

    assert uploaded.status_code == 200
    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-disposition"].startswith(disposition)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    if has_active_csp:
        assert response.headers["content-security-policy"] == (
            "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
    else:
        assert "content-security-policy" not in response.headers


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("legacy-page.xht", b"<script>window.pwned = true</script>"),
        ("legacy-diagram.svgz", b"\x1f\x8bnot-a-real-svgz"),
    ],
)
def test_existing_active_kb_file_aliases_are_forced_to_download(
    monkeypatch,
    tmp_path: Path,
    filename: str,
    payload: bytes,
) -> None:
    """Legacy raw files use the same active-content policy as new uploads."""
    manager = _ready_kb_manager(tmp_path)
    (manager.base_dir / "kb" / "raw" / filename).write_bytes(payload)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = client.get(f"/api/v1/knowledge/kb/files/{filename}")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == (
        "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )


def test_file_preview_text_accepts_default_alias(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["actual-kb"] = {
        "path": "actual-kb",
        "status": "ready",
    }
    raw_dir = manager.base_dir / "actual-kb" / "raw"
    raw_dir.mkdir(parents=True)
    target = raw_dir / "slides.pptx"
    target.write_bytes(b"PK\x03\x04")
    calls: dict[str, object] = {}

    def _fake_extract(path: Path, **kwargs) -> str:
        calls["path"] = path
        calls["kwargs"] = kwargs
        return "--- Slide 1 ---\nTitle"

    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "extract_text_from_path", _fake_extract)

    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/knowledge/default/file-preview-text/slides.pptx")

    assert response.status_code == 200
    assert response.text == "--- Slide 1 ---\nTitle"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in response.headers
    assert calls["path"] == target
    assert calls["kwargs"]["max_chars"] == 200_000


def test_file_preview_text_returns_422_for_extraction_errors(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["actual-kb"] = {
        "path": "actual-kb",
        "status": "ready",
    }
    raw_dir = manager.base_dir / "actual-kb" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "slides.pptx").write_bytes(b"PK\x03\x04")
    extraction_error = knowledge_router_module.DocumentExtractionError

    def _fake_extract(*_args, **_kwargs) -> str:
        raise extraction_error("slides.pptx: no extractable text")

    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "extract_text_from_path", _fake_extract)

    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/knowledge/actual-kb/file-preview-text/slides.pptx")

    assert response.status_code == 422
    assert "no extractable text" in response.json()["detail"]


def test_reindex_accepts_default_alias(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["actual-kb"] = {
        "path": "actual-kb",
        "status": "ready",
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    class _Signature:
        def hash(self) -> str:
            return "sig"

    embedding_signature = importlib.import_module("deeptutor.services.rag.embedding_signature")
    index_versioning = importlib.import_module("deeptutor.services.rag.index_versioning")
    monkeypatch.setattr(
        embedding_signature, "signature_from_embedding_config", lambda: _Signature()
    )
    monkeypatch.setattr(index_versioning, "find_matching_version", lambda *_args, **_kwargs: None)

    async def _noop_reindex_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_reindex_task", _noop_reindex_task)

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/default/reindex")

    assert response.status_code == 200
    body = response.json()
    assert body["noop"] is False
    assert isinstance(body.get("task_id"), str) and body["task_id"]
    assert manager.config["knowledge_bases"]["actual-kb"]["status"] == "initializing"


def test_reindex_error_status_bypasses_existing_match_noop(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["failed-kb"] = {
        "path": "failed-kb",
        "status": "error",
        "progress": {"stage": "error", "message": "previous indexing failed"},
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    class _Signature:
        def hash(self) -> str:
            return "sig"

    embedding_signature = importlib.import_module("deeptutor.services.rag.embedding_signature")
    index_versioning = importlib.import_module("deeptutor.services.rag.index_versioning")
    monkeypatch.setattr(
        embedding_signature, "signature_from_embedding_config", lambda: _Signature()
    )
    monkeypatch.setattr(
        index_versioning,
        "find_matching_version",
        lambda *_args, **_kwargs: {"layout": "flat", "ready": True},
    )

    async def _noop_reindex_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_reindex_task", _noop_reindex_task)

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/failed-kb/reindex")

    assert response.status_code == 200
    body = response.json()
    assert body["noop"] is False
    assert isinstance(body.get("task_id"), str) and body["task_id"]
    assert manager.config["knowledge_bases"]["failed-kb"]["status"] == "initializing"


def test_retry_error_status_queues_reindex(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["failed-kb"] = {
        "path": "failed-kb",
        "status": "error",
        "progress": {"stage": "error", "message": "previous indexing failed"},
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    class _Signature:
        def hash(self) -> str:
            return "sig"

    embedding_signature = importlib.import_module("deeptutor.services.rag.embedding_signature")
    index_versioning = importlib.import_module("deeptutor.services.rag.index_versioning")
    monkeypatch.setattr(
        embedding_signature, "signature_from_embedding_config", lambda: _Signature()
    )
    monkeypatch.setattr(
        index_versioning,
        "find_matching_version",
        lambda *_args, **_kwargs: {"layout": "flat", "ready": True},
    )

    async def _noop_reindex_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_reindex_task", _noop_reindex_task)

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/failed-kb/retry")

    assert response.status_code == 200
    body = response.json()
    assert body["noop"] is False
    assert isinstance(body.get("task_id"), str) and body["task_id"]
    assert manager.config["knowledge_bases"]["failed-kb"]["status"] == "initializing"


def test_retry_rejects_non_error_kb(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["ready-kb"] = {
        "path": "ready-kb",
        "status": "ready",
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/ready-kb/retry")

    assert response.status_code == 409
    assert "not in an error state" in response.json()["detail"]


def test_reindex_bypasses_existing_match_when_vectors_are_invalid(
    monkeypatch, tmp_path: Path
) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["bad-index-kb"] = {
        "path": "bad-index-kb",
        "status": "ready",
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    class _Signature:
        def hash(self) -> str:
            return "sig"

    kb_dir = manager.base_dir / "bad-index-kb"
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"signature": "sig", "version": "version-1"}),
        encoding="utf-8",
    )
    (version_dir / "default__vector_store.json").write_text(
        json.dumps({"embedding_dict": {"bad-node": [0.1, None, 0.3]}}),
        encoding="utf-8",
    )

    embedding_signature = importlib.import_module("deeptutor.services.rag.embedding_signature")
    monkeypatch.setattr(
        embedding_signature, "signature_from_embedding_config", lambda: _Signature()
    )

    async def _noop_reindex_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_reindex_task", _noop_reindex_task)

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/bad-index-kb/reindex")

    assert response.status_code == 200
    body = response.json()
    assert body["noop"] is False
    assert isinstance(body.get("task_id"), str) and body["task_id"]
    assert manager.config["knowledge_bases"]["bad-index-kb"]["status"] == "initializing"


def test_update_config_coerces_legacy_provider_to_llamaindex(tmp_path: Path) -> None:
    """Legacy `rag_provider` values are accepted and normalized to llamaindex."""

    class _FakeConfigService:
        def __init__(self) -> None:
            self.config: dict = {}

        def set_kb_config(self, kb_name: str, config: dict) -> None:
            self.kb_name = kb_name
            self.config = config

        def get_kb_config(self, _kb_name: str) -> dict:
            return self.config

    fake_service = _FakeConfigService()
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["demo"] = {"path": "demo"}

    config_module = importlib.import_module("deeptutor.services.config")
    app = _build_app()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(config_module, "get_kb_config_service", lambda: fake_service)
        monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
        with TestClient(app) as client:
            response = client.put(
                "/api/v1/knowledge/demo/config",
                json={"rag_provider": "raganything"},
            )

    assert response.status_code in {200, 204}
    assert fake_service.config.get("rag_provider") == "llamaindex"


def test_update_config_preserves_known_provider(tmp_path: Path) -> None:
    class _FakeConfigService:
        def __init__(self) -> None:
            self.config: dict = {}

        def set_kb_config(self, kb_name: str, config: dict) -> None:
            self.kb_name = kb_name
            self.config = config

        def get_kb_config(self, _kb_name: str) -> dict:
            return self.config

    fake_service = _FakeConfigService()
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["demo"] = {"path": "demo"}

    config_module = importlib.import_module("deeptutor.services.config")
    app = _build_app()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(config_module, "get_kb_config_service", lambda: fake_service)
        monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
        with TestClient(app) as client:
            response = client.put(
                "/api/v1/knowledge/demo/config",
                json={"rag_provider": "pageindex"},
            )

    assert response.status_code in {200, 204}
    assert fake_service.config.get("rag_provider") == "pageindex"


def test_update_config_rejects_provider_change_for_ready_index(monkeypatch, tmp_path: Path) -> None:
    kb_dir = tmp_path / "demo"
    kb_dir.mkdir(parents=True)
    _write_ready_llamaindex_version(kb_dir)

    class _FakeConfigService:
        def __init__(self) -> None:
            self.config: dict = {"rag_provider": "llamaindex"}

        def set_kb_config(self, kb_name: str, config: dict) -> None:
            self.kb_name = kb_name
            self.config.update(config)

        def get_kb_config(self, _kb_name: str) -> dict:
            return dict(self.config)

    fake_service = _FakeConfigService()
    config_module = importlib.import_module("deeptutor.services.config")
    manager = _FakeKBManager(tmp_path)
    manager.config["knowledge_bases"]["demo"] = {"path": "demo"}

    monkeypatch.setattr(config_module, "get_kb_config_service", lambda: fake_service)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_current_kb_base_dir", lambda: tmp_path)

    with TestClient(_build_app()) as client:
        response = client.put(
            "/api/v1/knowledge/demo/config",
            json={"rag_provider": "pageindex"},
        )

    assert response.status_code == 409
    assert "ready llamaindex index" in response.json()["detail"]
    assert fake_service.config["rag_provider"] == "llamaindex"


def test_update_config_rejects_connected_provider_change_but_allows_search_mode(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class _FakeConfigService:
        def __init__(self) -> None:
            self.config = {
                "type": "lightrag_server",
                "rag_provider": "lightrag-server",
                "search_mode": "hybrid",
                "server_url": "http://remote.invalid",
                "api_key": "admin-secret",
            }

        def get_kb_config(self, _kb_name: str) -> dict:
            return dict(self.config)

        def set_kb_config(self, _kb_name: str, config: dict) -> None:
            self.config.update(config)

    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["remote"] = {
        "path": "remote",
        "type": "lightrag_server",
        "rag_provider": "lightrag-server",
    }
    fake_service = _FakeConfigService()
    config_module = importlib.import_module("deeptutor.services.config")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(config_module, "get_kb_config_service", lambda: fake_service)

    with TestClient(_build_app()) as client:
        provider_change = client.put(
            "/api/v1/knowledge/remote/config",
            json={"rag_provider": "llamaindex"},
        )
        mode_change = client.put(
            "/api/v1/knowledge/remote/config",
            json={"search_mode": "mix"},
        )

    assert provider_change.status_code == 409
    assert fake_service.config["rag_provider"] == "lightrag-server"
    assert mode_change.status_code == 200
    assert fake_service.config["search_mode"] == "mix"


def test_regular_user_kb_config_cannot_forge_subagent_identity(tmp_path: Path, monkeypatch) -> None:
    """The authenticated learner patch is limited to an existing personal KB's retrieval fields."""
    from deeptutor.api.routers.auth import require_auth
    from deeptutor.multi_user.knowledge_access import resolve_kb_metadata
    from deeptutor.multi_user.models import CurrentUser, UserScope
    from deeptutor.multi_user.paths import user_context
    from deeptutor.services.config.knowledge_base_config import KnowledgeBaseConfigService
    from deeptutor.services.path_service import PathService

    learner_root = tmp_path / "users" / "learner-1"
    learner_paths = PathService(workspace_root=learner_root)
    kb_root = learner_paths.get_knowledge_bases_root()
    (kb_root / "personal-kb").mkdir(parents=True)
    config_path = kb_root / "kb_config.json"
    config_path.write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "personal-kb": {
                        "path": "personal-kb",
                        "description": "Learner notes",
                        "rag_provider": "llamaindex",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    learner = CurrentUser(
        id="learner-1",
        username="learner",
        role="user",
        scope=UserScope(kind="user", user_id="learner-1", root=learner_root),
    )
    monkeypatch.setattr(KnowledgeBaseConfigService, "_instances", {})

    async def authenticate_learner():
        from deeptutor.multi_user.context import set_current_user

        set_current_user(learner)
        return None

    app = FastAPI()
    app.include_router(
        router,
        prefix="/api/v1/knowledge",
        dependencies=[Depends(require_auth)],
    )
    app.dependency_overrides[require_auth] = authenticate_learner

    with TestClient(app) as client:
        forged = client.put(
            "/api/v1/knowledge/personal-kb/config",
            json={
                "type": "subagent",
                "agent_kind": "codex",
                "cwd": "/tmp/learner-controlled",
                "partner_id": "not-a-partner",
            },
        )
        unknown = client.put(
            "/api/v1/knowledge/personal-kb/config",
            json={"not_a_supported_config": True},
        )
        allowed = client.put(
            "/api/v1/knowledge/personal-kb/config",
            json={"search_mode": "hybrid"},
        )
        missing = client.put(
            "/api/v1/knowledge/missing-kb/config",
            json={"search_mode": "hybrid"},
        )

    assert forged.status_code == 422
    assert unknown.status_code == 422
    assert allowed.status_code == 200
    assert missing.status_code == 404

    with user_context(learner):
        metadata = resolve_kb_metadata("personal-kb")
        persisted = json.loads(config_path.read_text(encoding="utf-8"))["knowledge_bases"][
            "personal-kb"
        ]
    assert persisted["search_mode"] == "hybrid"
    assert metadata is not None and metadata.get("type") != "subagent"
    assert persisted.get("type") != "subagent"
    assert not {"agent_kind", "cwd", "partner_id"} & set(persisted)


def test_authenticated_learner_cannot_read_connected_pointer_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Stale personal pointers fail closed while ordinary retrieval config remains readable."""
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers.auth import require_auth
    from deeptutor.multi_user import grants, knowledge_access, paths
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.config.knowledge_base_config import KnowledgeBaseConfigService

    admin_root = (tmp_path / "data").resolve()
    users_root = admin_root / "users"
    system_root = admin_root / "system"
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", users_root)
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", tmp_path / "legacy-multi-user")
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(paths, "_legacy_migration_done", False)
    monkeypatch.setattr(grants, "GRANTS_DIR", system_root / "grants")
    knowledge_access._manager_for.cache_clear()
    monkeypatch.setattr(KnowledgeBaseConfigService, "_instances", {})

    kb_root = users_root / "learner-1" / "knowledge_bases"
    (kb_root / "notes").mkdir(parents=True)
    (kb_root / "kb_config.json").write_text(
        json.dumps(
            {
                "defaults": {
                    "default_kb": "notes",
                    "rag_provider": "llamaindex",
                    "search_mode": "hybrid",
                },
                "knowledge_bases": {
                    "notes": {
                        "path": "notes",
                        "rag_provider": "llamaindex",
                        "search_mode": "hybrid",
                        "api_key": "ordinary-entry-secret-must-not-project",
                    },
                    "stale-remote": {
                        "path": "stale-remote",
                        "type": "lightrag_server",
                        "rag_provider": "lightrag-server",
                        "server_url": "http://169.254.169.254/private",
                        "api_key": "connected-secret",
                        "client_id": "connected-client",
                        "external_path": "/srv/private-index",
                        "cwd": "/srv/private-agent",
                        "partner_id": "not-authorized",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    admin_kb_root = admin_root / "knowledge_bases"
    admin_kb_root.mkdir(parents=True)
    (admin_kb_root / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "assigned-stale-vault": {
                        "path": "assigned-stale-vault",
                        "type": "obsidian",
                        "vault_path": "/srv/admin-private-vault",
                        "api_key": "admin-connected-secret",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    grant_dir = system_root / "grants"
    grant_dir.mkdir(parents=True)
    (grant_dir / "learner-1.json").write_text(
        json.dumps(
            {
                "version": 2,
                "user_id": "learner-1",
                "models": {"llm": []},
                "knowledge_bases": [{"resource_id": "admin:kb:assigned-stale-vault"}],
                "skills": [],
                "partners": [],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda _token: TokenPayload(
            username="learner",
            role="user",
            user_id="learner-1",
        ),
    )

    app = FastAPI()
    app.include_router(
        router,
        prefix="/api/v1/knowledge",
        dependencies=[Depends(require_auth)],
    )
    headers = {"Authorization": "Bearer learner-token"}
    with TestClient(app) as client:
        bulk = client.get("/api/v1/knowledge/configs", headers=headers)
        ordinary_update = client.put(
            "/api/v1/knowledge/notes/config",
            json={"search_mode": "vector"},
            headers=headers,
        )
        ordinary_config = client.get("/api/v1/knowledge/notes/config", headers=headers)
        pointer_config = client.get(
            "/api/v1/knowledge/stale-remote/config",
            headers=headers,
        )
        pointer_details = client.get("/api/v1/knowledge/stale-remote", headers=headers)
        listing = client.get("/api/v1/knowledge/list", headers=headers)

    assert bulk.status_code == 403
    assert ordinary_update.status_code == 200
    assert ordinary_update.json()["config"] == {
        "rag_provider": "llamaindex",
        "search_mode": "vector",
    }
    assert ordinary_config.status_code == 200
    assert ordinary_config.json()["config"] == {
        "rag_provider": "llamaindex",
        "search_mode": "vector",
    }
    assert pointer_config.status_code == 403
    assert pointer_details.status_code == 403
    assert listing.status_code == 200
    listed = {item["name"]: item for item in listing.json()}
    assert listed["notes"]["available"] is True
    assert listed["stale-remote"] == {
        "id": "user:kb:stale-remote",
        "name": "stale-remote",
        "is_default": False,
        "statistics": {},
        "metadata": {},
        "path": None,
        "status": "unavailable",
        "progress": None,
        "source": "user",
        "assigned": False,
        "read_only": False,
        "provenance_label": "Created by you",
        "available": False,
    }
    assert "assigned-stale-vault" not in listed
    serialized_responses = " ".join(
        response.text
        for response in (
            ordinary_update,
            ordinary_config,
            pointer_config,
            pointer_details,
            listing,
        )
    )
    for secret in (
        "ordinary-entry-secret-must-not-project",
        "connected-secret",
        "connected-client",
        "169.254.169.254",
        "/srv/private-index",
        "/srv/private-agent",
        "not-authorized",
        "/srv/admin-private-vault",
        "admin-connected-secret",
    ):
        assert secret not in serialized_responses


def test_rag_providers_marks_linkable() -> None:
    with TestClient(_build_app()) as client:
        providers = client.get("/api/v1/knowledge/rag-providers").json()["providers"]
    by_id = {p["id"]: p for p in providers}
    # Self-contained local indexes can be linked in place; PageIndex (cloud) and
    # LightRAG Server (remote, no local folder) can't.
    assert by_id["llamaindex"]["linkable"] is True
    assert by_id["graphrag"]["linkable"] is True
    assert by_id["lightrag"]["linkable"] is True
    assert by_id["pageindex"]["linkable"] is False
    assert by_id["lightrag-server"]["linkable"] is False


def test_probe_folder_endpoint_finds_ready_index(tmp_path: Path) -> None:
    version = tmp_path / "version-1"
    version.mkdir()
    (version / "docstore.json").write_text("{}", encoding="utf-8")
    (version / "index_store.json").write_text("{}", encoding="utf-8")
    (version / "meta.json").write_text(
        json.dumps({"version": "version-1", "signature": "x", "layout": "flat"}),
        encoding="utf-8",
    )

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/probe-folder",
            json={"folder_path": str(tmp_path), "rag_provider": "llamaindex"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["version"] == "version-1"


def test_probe_folder_endpoint_rejects_pageindex(tmp_path: Path) -> None:
    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/probe-folder",
            json={"folder_path": str(tmp_path), "rag_provider": "pageindex"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]


def _patch_server_probe(monkeypatch, *, ok: bool, error: str | None = None) -> None:
    """Stub the LightRAG server probe so router tests need no live server."""
    from deeptutor.services.rag.pipelines.lightrag_server import probe as probe_module

    async def _fake_probe(server_url: str, api_key: str = "", **_kwargs):
        result = probe_module.ServerProbe(base_url=server_url.rstrip("/"))
        result.ok = ok
        result.reachable = ok
        result.auth_required = bool(api_key)
        result.auth_ok = ok
        result.error = error
        return result

    monkeypatch.setattr(probe_module, "probe_server", _fake_probe)


def test_authenticated_regular_learner_cannot_reach_host_or_connector_side_effects(
    monkeypatch,
) -> None:
    """All connector dependencies reject a real learner token before the endpoint runs."""
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.rag.pipelines.ima import probe as ima_probe_module
    from deeptutor.services.rag.pipelines.lightrag_server import probe as server_probe_module

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda _token: TokenPayload(
            username="learner",
            role="user",
            user_id="learner-1",
        ),
    )

    touched: list[str] = []

    def forbidden_sync(*_args, **_kwargs):
        touched.append("filesystem-or-manager")
        raise AssertionError("learner reached a host filesystem or manager side effect")

    async def forbidden_network(*_args, **_kwargs):
        touched.append("network")
        raise AssertionError("learner reached an outbound connector probe")

    monkeypatch.setattr(knowledge_router_module, "assert_path_allowed", forbidden_sync)
    monkeypatch.setattr(knowledge_router_module, "probe_linked_folder", forbidden_sync)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", forbidden_sync)
    monkeypatch.setattr(knowledge_router_module, "_writable_kb", forbidden_sync)
    monkeypatch.setattr(knowledge_router_module, "_current_kb_base_dir", forbidden_sync)
    monkeypatch.setattr(knowledge_router_module, "resolve_kb", forbidden_sync)
    monkeypatch.setattr(server_probe_module, "probe_server", forbidden_network)
    monkeypatch.setattr(ima_probe_module, "probe_knowledge_base", forbidden_network)

    requests = (
        (
            "POST",
            "/api/v1/knowledge/connect-obsidian",
            {"name": "vault", "vault_path": "/srv/vault"},
        ),
        ("POST", "/api/v1/knowledge/probe-folder", {"folder_path": "/srv/index"}),
        (
            "POST",
            "/api/v1/knowledge/connect-folder",
            {"name": "index", "folder_path": "/srv/index"},
        ),
        (
            "POST",
            "/api/v1/knowledge/probe-lightrag-server",
            {"server_url": "http://169.254.169.254"},
        ),
        (
            "POST",
            "/api/v1/knowledge/connect-lightrag-server",
            {"name": "remote", "server_url": "http://169.254.169.254"},
        ),
        (
            "POST",
            "/api/v1/knowledge/probe-ima",
            {
                "client_id": "client",
                "api_key": "secret",
                "knowledge_base_id": "library",
            },
        ),
        (
            "POST",
            "/api/v1/knowledge/connect-ima",
            {
                "name": "ima",
                "client_id": "client",
                "api_key": "secret",
                "knowledge_base_id": "library",
            },
        ),
        ("POST", "/api/v1/knowledge/demo/link-folder", {"folder_path": "/srv/source"}),
        ("GET", "/api/v1/knowledge/demo/linked-folders", None),
        ("DELETE", "/api/v1/knowledge/demo/linked-folders/folder-1", None),
        ("POST", "/api/v1/knowledge/demo/sync-folder/folder-1", None),
        ("POST", "/api/v1/knowledge/configs/sync", None),
    )

    headers = {"Authorization": "Bearer learner-token"}
    with TestClient(_build_app()) as client:
        responses = [
            client.request(method, path, json=payload, headers=headers)
            if payload is not None
            else client.request(method, path, headers=headers)
            for method, path, payload in requests
        ]

    assert [response.status_code for response in responses] == [403] * len(requests)
    assert all(response.json()["detail"] == "Admin access required" for response in responses)
    assert touched == []


@pytest.mark.parametrize(
    ("auth_enabled", "role", "headers"),
    [
        (True, "admin", {"Authorization": "Bearer admin-token"}),
        (False, "user", {}),
    ],
    ids=["authenticated-admin", "auth-disabled-local-admin"],
)
def test_admin_and_auth_disabled_local_can_probe_host_folder(
    monkeypatch,
    tmp_path: Path,
    auth_enabled: bool,
    role: str,
    headers: dict[str, str],
) -> None:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.services.auth import TokenPayload

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", auth_enabled)
    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda _token: TokenPayload(username=role, role=role, user_id=f"{role}-1"),
    )
    touched: list[str] = []

    class _ProbeResult:
        def to_dict(self) -> dict:
            return {"ok": True, "version": "version-1"}

    def allow_path(_path: str) -> Path:
        touched.append("path")
        return tmp_path

    def probe(_path: str, _provider: str) -> _ProbeResult:
        touched.append("probe")
        return _ProbeResult()

    monkeypatch.setattr(knowledge_router_module, "assert_path_allowed", allow_path)
    monkeypatch.setattr(knowledge_router_module, "probe_linked_folder", probe)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/probe-folder",
            json={"folder_path": str(tmp_path)},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert touched == ["path", "probe"]


def test_probe_lightrag_server_endpoint_reports_verdict(monkeypatch) -> None:
    _patch_server_probe(monkeypatch, ok=True)
    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/probe-lightrag-server",
            json={"server_url": "http://localhost:9621", "api_key": "k"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["base_url"] == "http://localhost:9621"


def test_connect_lightrag_server_registers_pointer(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    _patch_server_probe(monkeypatch, ok=True)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/connect-lightrag-server",
            json={
                "name": "remote-kb",
                "server_url": "http://localhost:9621/",
                "api_key": "secret",
                "search_mode": "MIX",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["rag_provider"] == "lightrag-server"
    entry = manager.config["knowledge_bases"]["remote-kb"]
    assert entry["type"] == "lightrag_server"
    assert entry["server_url"] == "http://localhost:9621"
    assert entry["search_mode"] == "mix"  # normalized + validated


def test_connect_lightrag_server_rejects_unreachable(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    _patch_server_probe(monkeypatch, ok=False, error="Could not reach a LightRAG server")

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/connect-lightrag-server",
            json={"name": "bad", "server_url": "http://nope:9621"},
        )

    assert response.status_code == 400
    assert "LightRAG" in response.json()["detail"]
    assert "bad" not in manager.config["knowledge_bases"]


def test_assert_not_connected_kb_blocks_connected_writes() -> None:
    from fastapi import HTTPException

    guard = knowledge_router_module._assert_not_connected_kb
    for kind in ("linked", "obsidian", "lightrag_server"):
        with pytest.raises(HTTPException) as excinfo:
            guard("kb", {"type": kind})
        assert excinfo.value.status_code == 409
    # An ordinary KB is writable — the guard is a no-op.
    guard("kb", {"path": "kb", "status": "ready"})
