"""Only real knowledge bases belong in the generic admin assignment pool."""

from __future__ import annotations

from deeptutor.multi_user import router as multi_user_router


def test_admin_kb_summary_excludes_connected_pointers_but_keeps_normal_kbs(
    monkeypatch,
) -> None:
    class _FakeKBManager:
        def __init__(self, **_kwargs) -> None:
            self.metadata = {
                "CourseNotes": {"type": None},
                "AdminVault": {"type": "obsidian", "vault_path": "/admin/vault"},
                "AdminIndex": {"type": "linked", "external_path": "/admin/index"},
                "RemoteRag": {"type": "lightrag_server", "server_url": "http://rag"},
                "RemoteIma": {"type": "ima", "knowledge_base_id": "ima-kb"},
                "AdminClaude": {"type": "subagent", "agent_kind": "claude_code"},
                "AssignedPartner": {"type": "subagent", "agent_kind": "partner"},
            }

        def list_knowledge_bases(self) -> list[str]:
            return list(self.metadata)

        def get_metadata(self, name: str) -> dict:
            return self.metadata[name]

    monkeypatch.setattr(multi_user_router, "KnowledgeBaseManager", _FakeKBManager)

    assert multi_user_router._admin_kb_summary() == [
        {"resource_id": "admin:kb:CourseNotes", "name": "CourseNotes", "source": "admin"}
    ]
