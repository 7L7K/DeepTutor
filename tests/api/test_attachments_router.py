from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import attachments as attachments_module
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.storage.attachment_store import LocalDiskAttachmentStore


def _app(store: SQLiteSessionStore, attachment_store: LocalDiskAttachmentStore) -> FastAPI:
    app = FastAPI()
    app.include_router(attachments_module.router, prefix="/api/attachments")
    return app


def test_attachment_requires_a_session_owned_message_reference(monkeypatch, tmp_path: Path) -> None:
    store = SQLiteSessionStore(db_path=tmp_path / "history.db")
    attachment_store = LocalDiskAttachmentStore(root=tmp_path / "attachments")
    monkeypatch.setattr(attachments_module, "get_sqlite_session_store", lambda: store)
    monkeypatch.setattr(attachments_module, "get_attachment_store", lambda: attachment_store)

    sid = asyncio.run(store.create_session())["id"]
    aid = "owned-file"
    url = asyncio.run(
        attachment_store.put(
            session_id=sid,
            attachment_id=aid,
            filename="notes.txt",
            data=b"private notes",
        )
    )
    asyncio.run(
        store.add_message(
            session_id=sid,
            role="user",
            content="",
            attachments=[{"id": aid, "url": url, "filename": "notes.txt"}],
        )
    )

    with TestClient(_app(store, attachment_store)) as client:
        owner = client.get(f"/api/attachments/{sid}/{aid}/notes.txt")
        assert owner.status_code == 200
        assert owner.content == b"private notes"
        assert owner.headers["x-content-type-options"] == "nosniff"
        assert client.get(f"/api/attachments/{sid}/unlinked/notes.txt").status_code == 404


def test_active_attachment_is_download_only(monkeypatch, tmp_path: Path) -> None:
    store = SQLiteSessionStore(db_path=tmp_path / "history.db")
    attachment_store = LocalDiskAttachmentStore(root=tmp_path / "attachments")
    monkeypatch.setattr(attachments_module, "get_sqlite_session_store", lambda: store)
    monkeypatch.setattr(attachments_module, "get_attachment_store", lambda: attachment_store)

    sid = asyncio.run(store.create_session())["id"]
    aid = "active-file"
    url = asyncio.run(
        attachment_store.put(
            session_id=sid,
            attachment_id=aid,
            filename="unsafe.html",
            data=b"<script>window.pwned=true</script>",
        )
    )
    asyncio.run(
        store.add_message(
            session_id=sid,
            role="user",
            content="",
            attachments=[{"id": aid, "url": url, "filename": "unsafe.html"}],
        )
    )

    with TestClient(_app(store, attachment_store)) as client:
        response = client.get(f"/api/attachments/{sid}/{aid}/unsafe.html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["content-security-policy"] == "sandbox; default-src 'none'"
