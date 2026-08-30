from __future__ import annotations

import asyncio
from contextlib import contextmanager
import importlib
from pathlib import Path
import sys
import types

import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture(autouse=True)
def _cleanup_question_router_module():
    yield
    sys.modules.pop("deeptutor.api.routers.question", None)


class _DummyProcessLogEvent:
    def __init__(self, **kwargs) -> None:
        self.data = {"type": "process_log", **kwargs}

    def to_dict(self):
        return self.data


@contextmanager
def _noop_context(*_args, **_kwargs):
    yield


def _package(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []
    return module


def _load_question_router_module(monkeypatch: pytest.MonkeyPatch):
    sys.modules.pop("deeptutor.api.routers.question", None)

    from deeptutor.multi_user.context import set_current_user, user_from_token_payload

    fake_agents = _package("deeptutor.agents")
    fake_agents_question = types.ModuleType("deeptutor.agents.question")
    fake_agents_question.AgentCoordinator = object
    fake_agents.question = fake_agents_question
    monkeypatch.setitem(sys.modules, "deeptutor.agents", fake_agents)
    monkeypatch.setitem(sys.modules, "deeptutor.agents.question", fake_agents_question)

    fake_logging = _package("deeptutor.logging")
    fake_logging.ProcessLogEvent = _DummyProcessLogEvent
    fake_logging.bind_log_context = _noop_context
    fake_logging.capture_process_logs = _noop_context
    fake_logging.current_log_context = lambda: {}
    monkeypatch.setitem(sys.modules, "deeptutor.logging", fake_logging)

    fake_config = types.ModuleType("deeptutor.services.config")
    fake_config.PROJECT_ROOT = Path.cwd()
    fake_config.load_config_with_main = lambda *_args, **_kwargs: {}
    monkeypatch.setitem(sys.modules, "deeptutor.services.config", fake_config)

    fake_auth = types.ModuleType("deeptutor.api.routers.auth")
    fake_auth.ws_auth_failed = object()

    async def _allow_local_test_user(_websocket):
        return set_current_user(user_from_token_payload(None))

    fake_auth.ws_require_auth = _allow_local_test_user
    monkeypatch.setitem(sys.modules, "deeptutor.api.routers.auth", fake_auth)

    fake_llm_package = _package("deeptutor.services.llm")
    fake_llm_config = types.ModuleType("deeptutor.services.llm.config")
    fake_llm_config.get_llm_config = lambda: None
    fake_llm_package.config = fake_llm_config
    monkeypatch.setitem(sys.modules, "deeptutor.services.llm", fake_llm_package)
    monkeypatch.setitem(sys.modules, "deeptutor.services.llm.config", fake_llm_config)

    fake_settings_package = _package("deeptutor.services.settings")
    fake_interface_settings = types.ModuleType("deeptutor.services.settings.interface_settings")
    fake_interface_settings.get_ui_language = lambda default="en": default
    fake_settings_package.interface_settings = fake_interface_settings
    monkeypatch.setitem(sys.modules, "deeptutor.services.settings", fake_settings_package)
    monkeypatch.setitem(
        sys.modules,
        "deeptutor.services.settings.interface_settings",
        fake_interface_settings,
    )

    fake_tools = _package("deeptutor.tools")
    fake_tools_question = types.ModuleType("deeptutor.tools.question")

    async def _default_mimic_exam_questions(*_args, **_kwargs):
        return {"success": True}

    fake_tools_question.mimic_exam_questions = _default_mimic_exam_questions
    fake_tools.question = fake_tools_question
    monkeypatch.setitem(sys.modules, "deeptutor.tools", fake_tools)
    monkeypatch.setitem(sys.modules, "deeptutor.tools.question", fake_tools_question)

    return importlib.import_module("deeptutor.api.routers.question")


def _build_app(router_module) -> FastAPI:
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/question")
    return app


def test_mimic_websocket_accepts_config_and_returns_messages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)

    async def _fake_mimic_exam_questions(*_args, **_kwargs):
        return {"success": False, "error": "stub mimic failure"}

    monkeypatch.setattr(question_router_module, "mimic_exam_questions", _fake_mimic_exam_questions)
    # ``MIMIC_OUTPUT_DIR`` was a module-level constant resolved at import time
    # (which froze it to the admin path). It's now a per-call helper so the
    # path follows whichever user is running. Patch the helper instead.
    monkeypatch.setattr(
        question_router_module, "_mimic_output_dir", lambda: tmp_path / "mimic_papers"
    )

    with TestClient(_build_app(question_router_module)) as client:
        with client.websocket_connect("/api/v1/question/mimic") as websocket:
            websocket.send_json(
                {
                    "mode": "parsed",
                    "paper_path": str(tmp_path / "paper"),
                    "kb_name": "demo-kb",
                    "max_questions": 3,
                }
            )
            messages = [websocket.receive_json() for _ in range(3)]

    assert [message["type"] for message in messages] == ["status", "status", "error"]
    assert messages[0]["stage"] == "init"
    assert messages[1]["stage"] == "processing"
    assert messages[2]["content"] == "stub mimic failure"


def test_quiz_judge_revalidates_after_upgrade_before_starting_provider_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user disabled while an idle judge socket is open cannot start a judge run."""
    from starlette.datastructures import QueryParams

    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import quiz_judge
    from deeptutor.services import auth as auth_service

    state = {"disabled": False, "provider_started": False}
    users = {
        "alice": {
            "id": "u_alice",
            "hash": "unused-by-token-auth",
            "role": "user",
            "disabled": False,
        }
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "AUTH_SECRET", "judge-revalidation-test-secret")
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "judge-revalidation-test-secret")
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_service, "_load_users", lambda: users)
    token = auth_service.create_token("alice", "user", "u_alice")

    class FakeWebSocket:
        def __init__(self) -> None:
            self.closed_code: int | None = None
            self.accepted = False
            self.messages: list[dict] = []
            self.headers: dict[str, str] = {}
            self.cookies: dict[str, str] = {}
            self.query_params = QueryParams({"token": token})

        async def accept(self) -> None:
            self.accepted = True

        async def receive_json(self) -> dict:
            state["disabled"] = True
            users["alice"]["disabled"] = True
            return {"question": "What is 2 + 2?", "user_answer": "4", "language": "en"}

        async def send_json(self, payload: dict) -> None:
            self.messages.append(payload)

        async def close(self, code: int = 1000) -> None:
            self.closed_code = code

    async def _provider_must_not_start(**_kwargs):
        state["provider_started"] = True
        yield "unexpected"

    monkeypatch.setattr(quiz_judge, "llm_stream", _provider_must_not_start)

    websocket = FakeWebSocket()
    asyncio.run(quiz_judge.websocket_quiz_judge(websocket))

    assert websocket.accepted is True
    assert websocket.closed_code == 4001
    assert state["disabled"] is True
    assert state["provider_started"] is False
