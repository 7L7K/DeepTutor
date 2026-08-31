"""Only real knowledge bases belong in the generic admin assignment pool."""

from __future__ import annotations

import pytest

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


@pytest.mark.asyncio
async def test_admin_resources_exposes_builtin_tool_options(monkeypatch) -> None:
    from deeptutor.api.utils import tool_options

    async def fake_build_tool_options() -> dict[str, list[dict[str, str]]]:
        return {
            "tools": [{"name": "web_search"}],
            "builtin_tools": [{"name": "rag"}, {"name": "web_fetch"}],
            "mcp_tools": [{"name": "mcp_docs_search"}],
        }

    monkeypatch.setattr(tool_options, "build_tool_options", fake_build_tool_options)
    monkeypatch.setattr(multi_user_router, "_admin_catalog_summary", lambda: {"llm": []})
    monkeypatch.setattr(multi_user_router, "_admin_kb_summary", lambda: [])
    monkeypatch.setattr(multi_user_router, "_admin_skill_summary", lambda: [])
    monkeypatch.setattr(multi_user_router, "_admin_partner_summary", lambda: [])

    resources = await multi_user_router.admin_resources(None)

    assert resources["tools"] == [{"name": "web_search"}]
    assert resources["builtin_tools"] == [
        {"name": "rag"},
        {"name": "web_fetch"},
    ]
    assert resources["mcp_tools"] == [{"name": "mcp_docs_search"}]
