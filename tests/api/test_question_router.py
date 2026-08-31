from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
import importlib
import json
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

    async def _still_authenticated(_websocket):
        return True

    fake_auth.ws_revalidate_auth = _still_authenticated
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
        print("unstructured output must not be sent to a learner socket")
        return {"success": False, "error": "stub mimic failure"}

    monkeypatch.setattr(question_router_module, "mimic_exam_questions", _fake_mimic_exam_questions)
    # ``MIMIC_OUTPUT_DIR`` was a module-level constant resolved at import time
    # (which froze it to the admin path). It's now a per-call helper so the
    # path follows whichever user is running. Patch the helper instead.
    monkeypatch.setattr(
        question_router_module, "_mimic_output_dir", lambda: tmp_path / "mimic_papers"
    )
    (tmp_path / "paper").mkdir()
    monkeypatch.setattr(
        question_router_module,
        "get_path_service",
        lambda: types.SimpleNamespace(get_question_dir=lambda: tmp_path),
    )

    class _Lease:
        async def __aexit__(self, *_args) -> None:
            return None

        async def aclose(self) -> None:
            return None

    async def _admit():
        return None, _Lease()

    monkeypatch.setattr(question_router_module, "_admit_question_generation", _admit)

    with TestClient(_build_app(question_router_module)) as client:
        with client.websocket_connect("/api/v1/question/mimic") as websocket:
            websocket.send_json(
                {
                    "mode": "parsed",
                    "paper_path": "paper",
                    "kb_name": "demo-kb",
                    "max_questions": 3,
                }
            )
            messages = [websocket.receive_json() for _ in range(3)]

    assert [message["type"] for message in messages] == ["status", "status", "error"]
    assert messages[0]["stage"] == "init"
    assert messages[1]["stage"] == "processing"
    assert messages[2]["content"] == "Question generation is unavailable."
    assert not any(message.get("type") == "process_log" for message in messages)


def test_question_generate_uses_current_topic_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)
    received: dict = {}

    class FakeCoordinator:
        def __init__(self, **_kwargs) -> None:
            pass

        def set_ws_callback(self, _callback) -> None:
            pass

        async def generate_from_topic(self, **kwargs):
            received.update(kwargs)
            return {"success": True, "completed": 2, "failed": 0}

    class FakeTaskManager:
        def generate_task_id(self, *_args) -> str:
            return "question-task"

        def update_task_status(self, *_args, **_kwargs) -> None:
            pass

    class FakeConfig:
        api_key = "test-key"
        base_url = "https://example.test/v1"
        api_version = None
        model = "test-model"

    class FakeAdmission:
        async def aclose(self) -> None:
            pass

    class FakeWebSocket:
        def __init__(self) -> None:
            self.messages: list[dict] = []

        async def accept(self) -> None:
            pass

        async def receive_json(self) -> dict:
            return {
                "requirement": {
                    "knowledge_point": "fractions",
                    "difficulty": "easy",
                    "question_type": "choice",
                    "preference": "ignored by the current contract",
                },
                "kb_name": "demo-kb",
                "count": 2,
            }

        async def receive(self) -> dict:
            return {"type": "websocket.receive", "text": json.dumps(await self.receive_json())}

        async def send_json(self, payload: dict) -> None:
            self.messages.append(payload)

        async def close(self, *_args, **_kwargs) -> None:
            pass

    async def _admit():
        return None, FakeAdmission()

    monkeypatch.setattr(question_router_module, "AgentCoordinator", FakeCoordinator)
    monkeypatch.setattr(
        question_router_module,
        "TaskIDManager",
        types.SimpleNamespace(get_instance=lambda: FakeTaskManager()),
    )
    monkeypatch.setattr(question_router_module, "get_llm_config", lambda: FakeConfig())
    monkeypatch.setattr(
        question_router_module,
        "get_path_service",
        lambda: types.SimpleNamespace(
            get_question_batch_dir=lambda _task_id: tmp_path,
            get_question_dir=lambda: tmp_path,
        ),
    )
    monkeypatch.setattr(question_router_module, "_admit_question_generation", _admit)

    websocket = FakeWebSocket()
    asyncio.run(question_router_module.websocket_question_generate(websocket))

    assert received == {
        "user_topic": "fractions",
        "num_questions": 2,
        "difficulty": "easy",
        "question_types": ["choice"],
        "per_type_counts": {"choice": 2},
    }
    assert any(message.get("type") == "complete" for message in websocket.messages)


def test_question_request_envelope_is_limited_before_json_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)
    monkeypatch.setattr(question_router_module, "_MAX_REQUEST_JSON_CHARS", 16)

    class FakeWebSocket:
        async def receive(self) -> dict:
            return {"type": "websocket.receive", "text": "{" + "x" * 16}

    with pytest.raises(ValueError):
        asyncio.run(question_router_module._receive_bounded_request_json(FakeWebSocket()))


def test_question_initial_request_has_a_bounded_idle_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)
    monkeypatch.setattr(question_router_module, "_QUESTION_INITIAL_REQUEST_TIMEOUT_S", 0.01)

    class FakeWebSocket:
        async def receive(self) -> dict:
            await asyncio.sleep(1)
            return {"type": "websocket.receive", "text": "{}"}

    with pytest.raises(TimeoutError):
        asyncio.run(question_router_module._receive_bounded_request_json(FakeWebSocket()))


def test_mimic_rejects_invalid_upload_without_question_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)
    admission_calls = 0

    class _Lease:
        async def aclose(self) -> None:
            return None

    async def _admit():
        nonlocal admission_calls
        admission_calls += 1
        return None, _Lease()

    monkeypatch.setattr(question_router_module, "_admit_question_generation", _admit)

    with TestClient(_build_app(question_router_module)) as client:
        with client.websocket_connect("/api/v1/question/mimic") as websocket:
            websocket.send_json(
                {"mode": "upload", "pdf_data": "not valid base64", "pdf_name": "exam.pdf"}
            )
            message = websocket.receive_json()

    # Local validation runs before scarce provider/process capacity is
    # reserved, so malformed input cannot occupy a generation lease.
    assert admission_calls == 0
    assert message == {"type": "error", "content": "Question generation is unavailable."}


def test_idle_question_socket_does_not_hold_generation_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)
    admission_calls = 0

    class FakeWebSocket:
        def __init__(self) -> None:
            self.receive_started = asyncio.Event()
            self.release_receive = asyncio.Event()

        async def accept(self) -> None:
            return None

        async def receive(self) -> dict:
            self.receive_started.set()
            await self.release_receive.wait()
            return {
                "type": "websocket.receive",
                "text": json.dumps({"requirement": "fractions", "kb_name": "demo-kb"}),
            }

        async def send_json(self, _payload: dict) -> None:
            return None

        async def close(self, *_args, **_kwargs) -> None:
            return None

    async def _admit():
        nonlocal admission_calls
        admission_calls += 1

        class Lease:
            async def aclose(self) -> None:
                return None

        return None, Lease()

    monkeypatch.setattr(question_router_module, "_admit_question_generation", _admit)

    async def _exercise() -> None:
        websocket = FakeWebSocket()
        task = asyncio.create_task(question_router_module.websocket_question_generate(websocket))
        await asyncio.wait_for(websocket.receive_started.wait(), timeout=1)
        assert admission_calls == 0
        websocket.release_receive.set()
        await task
        assert admission_calls == 1

    asyncio.run(_exercise())


def test_question_global_bulkhead_serializes_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)

    assert question_router_module._QUESTION_GLOBAL_QUOTA._max_concurrent == 1


def test_mimic_parsed_path_is_jailed_to_the_authenticated_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)
    allowed = tmp_path / "parsed-paper"
    allowed.mkdir()
    monkeypatch.setattr(
        question_router_module,
        "get_path_service",
        lambda: types.SimpleNamespace(get_question_dir=lambda: tmp_path),
    )

    assert question_router_module._resolve_parsed_mimic_path("parsed-paper") == str(allowed)
    with pytest.raises(ValueError):
        question_router_module._resolve_parsed_mimic_path(str(allowed))
    with pytest.raises(ValueError):
        question_router_module._resolve_parsed_mimic_path("../outside")


def test_question_scope_rejects_blank_resolved_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)

    reset_tokens: list[object] = []
    scope_token = object()
    fake_runtime = types.ModuleType("deeptutor.services.model_selection.runtime")
    fake_runtime.activate_llm_selection = lambda _selection: (
        types.SimpleNamespace(model="   "),
        scope_token,
    )
    fake_runtime.reset_llm_selection = reset_tokens.append
    monkeypatch.setitem(sys.modules, "deeptutor.services.model_selection.runtime", fake_runtime)
    fake_model_access = types.ModuleType("deeptutor.multi_user.model_access")
    fake_model_access.has_capability_access = lambda _capability: True
    fake_model_access.redacted_model_access = lambda _user_id: {"llm": []}
    monkeypatch.setitem(sys.modules, "deeptutor.multi_user.model_access", fake_model_access)
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )

    user_token = set_current_user(
        user_from_token_payload(
            types.SimpleNamespace(username="admin", role="admin", user_id="test-admin")
        )
    )

    try:
        with pytest.raises(PermissionError, match="Configured LLM model is unavailable"):
            question_router_module._activate_question_llm_scope()
    finally:
        reset_current_user(user_token)

    assert reset_tokens == [scope_token]


def test_question_admission_releases_user_lease_if_global_acquisition_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )
    from deeptutor.services.sandbox.quota import UserExecQuota

    class CancelledGlobalQuota:
        async def acquire(self, _key: str):
            raise asyncio.CancelledError()

    scope_token = object()
    reset_tokens: list[object] = []
    user_quota = UserExecQuota(max_concurrent=1, max_per_minute=10)
    fake_runtime = types.ModuleType("deeptutor.services.model_selection.runtime")
    fake_runtime.reset_llm_selection = reset_tokens.append
    monkeypatch.setitem(sys.modules, "deeptutor.services.model_selection.runtime", fake_runtime)
    monkeypatch.setattr(question_router_module, "_activate_question_llm_scope", lambda: scope_token)
    monkeypatch.setattr(question_router_module, "_QUESTION_REQUEST_QUOTA", user_quota)
    monkeypatch.setattr(question_router_module, "_QUESTION_GLOBAL_QUOTA", CancelledGlobalQuota())
    user_token = set_current_user(
        user_from_token_payload(
            types.SimpleNamespace(username="cancel", role="user", user_id="cancel-user")
        )
    )

    async def _exercise() -> None:
        with pytest.raises(asyncio.CancelledError):
            await question_router_module._admit_question_generation()
        lease = await user_quota.acquire("cancel-user")
        await lease.__aexit__(None, None, None)

    try:
        asyncio.run(_exercise())
    finally:
        reset_current_user(user_token)

    assert reset_tokens == [scope_token]


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


def test_quiz_judge_revalidates_model_grant_before_starting_provider_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An idle socket cannot use a model grant revoked before its judge call."""
    from starlette.datastructures import QueryParams

    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import quiz_judge
    from deeptutor.multi_user import model_access
    from deeptutor.services import auth as auth_service

    state = {"grant_enabled": True, "provider_started": False}
    users = {
        "alice": {
            "id": "u_alice",
            "hash": "unused-by-token-auth",
            "role": "user",
            "disabled": False,
        }
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "AUTH_SECRET", "judge-grant-revalidation-test-secret")
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "judge-grant-revalidation-test-secret")
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_service, "_load_users", lambda: users)
    monkeypatch.setattr(
        model_access,
        "has_capability_access",
        lambda capability: capability == "llm" and state["grant_enabled"],
    )
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
            state["grant_enabled"] = False
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
    assert websocket.closed_code == 1008
    assert websocket.messages == [{"type": "error", "content": "AI judging is unavailable."}]
    assert state["provider_started"] is False


def test_quiz_judge_scopes_provider_work_to_the_users_granted_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-admin judge call must not fall through to the global model."""
    from starlette.datastructures import QueryParams

    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import quiz_judge
    from deeptutor.multi_user import model_access
    from deeptutor.services import auth as auth_service
    from deeptutor.services.model_selection import runtime as model_runtime

    users = {
        "alice": {
            "id": "u_alice",
            "hash": "unused-by-token-auth",
            "role": "user",
            "disabled": False,
        }
    }
    activated: list[dict[str, str] | None] = []
    reset_tokens: list[object] = []
    scope_token = object()
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "AUTH_SECRET", "judge-grant-scope-test-secret")
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "judge-grant-scope-test-secret")
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_service, "_load_users", lambda: users)
    monkeypatch.setattr(
        model_access, "has_capability_access", lambda capability: capability == "llm"
    )
    monkeypatch.setattr(
        model_access,
        "redacted_model_access",
        lambda _user_id: {
            "llm": [
                {
                    "profile_id": "profile_granted",
                    "model_id": "model_granted",
                    "available": True,
                }
            ]
        },
    )

    def _activate(selection):
        activated.append(selection)
        return object(), scope_token

    monkeypatch.setattr(model_runtime, "activate_llm_selection", _activate)
    monkeypatch.setattr(model_runtime, "reset_llm_selection", reset_tokens.append)
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
            return {"question": "What is 2 + 2?", "user_answer": "4", "language": "en"}

        async def send_json(self, payload: dict) -> None:
            self.messages.append(payload)

        async def close(self, code: int = 1000) -> None:
            self.closed_code = code

    async def _provider_stream(**_kwargs):
        yield "approved"

    monkeypatch.setattr(quiz_judge, "llm_stream", _provider_stream)

    websocket = FakeWebSocket()
    asyncio.run(quiz_judge.websocket_quiz_judge(websocket))

    assert activated == [{"profile_id": "profile_granted", "model_id": "model_granted"}]
    assert reset_tokens == [scope_token]
    assert [message["type"] for message in websocket.messages] == ["started", "text", "done"]


def test_quiz_judge_rejects_unbounded_or_external_image_input() -> None:
    from deeptutor.api.routers import quiz_judge

    with pytest.raises(ValueError, match="judge images are invalid"):
        quiz_judge._validated_judge_images(
            {
                "user_answer_images": [
                    {
                        "base64": "",
                        "url": "https://untrusted.example/answer.png",
                        "filename": "answer.png",
                        "mime_type": "image/png",
                    }
                ]
            }
        )

    with pytest.raises(ValueError, match="judge images are invalid"):
        quiz_judge._validated_judge_images(
            {
                "user_answer_images": [
                    {
                        "base64": "YQ==",
                        "url": "",
                        "filename": "answer.png",
                        "mime_type": "image/png",
                    }
                    for _ in range(6)
                ]
            }
        )

    with pytest.raises(ValueError, match="judge text is invalid"):
        quiz_judge._bounded_judge_text(
            {"question": "x" * (quiz_judge._MAX_JUDGE_QUESTION_CHARS + 1)},
            "question",
            quiz_judge._MAX_JUDGE_QUESTION_CHARS,
        )


def test_quiz_judge_resolves_and_validates_saved_local_image_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from deeptutor.api.routers import quiz_judge
    from deeptutor.services.storage.attachment_store import LocalDiskAttachmentStore

    image = tmp_path / "answer.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"safe-image")
    monkeypatch.setattr(
        LocalDiskAttachmentStore,
        "resolve_path",
        lambda *_args, **_kwargs: image,
    )

    records = quiz_judge._validated_judge_images(
        {
            "user_answer_images": [
                {
                    "base64": "",
                    "url": "/api/attachments/session-a/attachment-a/answer.png",
                    "filename": "answer.png",
                    "mime_type": "image/png",
                }
            ]
        }
    )

    assert records[0]["url"] == ""
    assert base64.b64decode(records[0]["base64"], validate=True) == image.read_bytes()


def test_quiz_judge_rejected_duplicate_does_not_consume_global_rate_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import quiz_judge
    from deeptutor.multi_user.context import set_current_user, user_from_token_payload
    from deeptutor.services.model_selection import runtime as model_runtime
    from deeptutor.services.sandbox.quota import UserExecQuota

    async def _allow_local_admin(_websocket):
        return set_current_user(user_from_token_payload(None))

    async def _still_authenticated(_websocket):
        return True

    class FakeWebSocket:
        def __init__(self) -> None:
            self.closed_code: int | None = None
            self.messages: list[dict] = []

        async def accept(self) -> None:
            pass

        async def receive_json(self) -> dict:
            return {"question": "What is 2 + 2?", "user_answer": "4", "language": "en"}

        async def send_json(self, payload: dict) -> None:
            self.messages.append(payload)

        async def close(self, code: int = 1000) -> None:
            self.closed_code = code

    monkeypatch.setattr(auth_router, "ws_require_auth", _allow_local_admin)
    monkeypatch.setattr(auth_router, "ws_revalidate_auth", _still_authenticated)
    monkeypatch.setattr(quiz_judge, "_activate_judge_llm_scope", lambda: object())
    monkeypatch.setattr(model_runtime, "reset_llm_selection", lambda _token: None)
    user_quota = UserExecQuota(max_concurrent=1, max_per_minute=10)
    global_quota = UserExecQuota(max_concurrent=4, max_per_minute=2)
    monkeypatch.setattr(quiz_judge, "_JUDGE_REQUEST_QUOTA", user_quota)
    monkeypatch.setattr(quiz_judge, "_JUDGE_GLOBAL_QUOTA", global_quota)

    async def _exercise() -> None:
        # Hold the first learner's slot. The second socket must fail at the
        # per-user gate before it can debit the shared global rate bucket.
        held_user_lease = await user_quota.acquire("local-admin")
        websocket = FakeWebSocket()
        await quiz_judge.websocket_quiz_judge(websocket)
        assert websocket.messages == [{"type": "error", "content": "AI judging is unavailable."}]

        # Both global starts remain available to other learners.
        first_global_lease = await global_quota.acquire(quiz_judge._JUDGE_GLOBAL_QUOTA_KEY)
        second_global_lease = await global_quota.acquire(quiz_judge._JUDGE_GLOBAL_QUOTA_KEY)
        await second_global_lease.__aexit__(None, None, None)
        await first_global_lease.__aexit__(None, None, None)
        await held_user_lease.__aexit__(None, None, None)

    asyncio.run(_exercise())


def test_quiz_judge_hides_receive_errors_from_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import quiz_judge
    from deeptutor.multi_user.context import set_current_user, user_from_token_payload

    async def _allow_local_admin(_websocket):
        return set_current_user(user_from_token_payload(None))

    class FakeWebSocket:
        def __init__(self) -> None:
            self.closed_code: int | None = None
            self.messages: list[dict] = []

        async def accept(self) -> None:
            pass

        async def receive_json(self) -> dict:
            raise RuntimeError("internal parser detail")

        async def send_json(self, payload: dict) -> None:
            self.messages.append(payload)

        async def close(self, code: int = 1000) -> None:
            self.closed_code = code

    monkeypatch.setattr(auth_router, "ws_require_auth", _allow_local_admin)
    websocket = FakeWebSocket()
    asyncio.run(quiz_judge.websocket_quiz_judge(websocket))

    assert websocket.messages == [{"type": "error", "content": "AI judging is unavailable."}]
    assert websocket.closed_code == 1000
