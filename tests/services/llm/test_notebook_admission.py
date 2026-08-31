from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.llm import notebook_admission
from deeptutor.services.sandbox.quota import QuotaExceeded, UserExecQuota


def _learner(tmp_path) -> CurrentUser:
    return CurrentUser(
        id="learner-1",
        username="learner",
        role="user",
        scope=UserScope(kind="user", user_id="learner-1", root=tmp_path),
    )


def test_notebook_admission_rejects_learner_without_live_llm_grant(tmp_path, monkeypatch) -> None:
    token = set_current_user(_learner(tmp_path))
    try:
        monkeypatch.setattr(
            "deeptutor.multi_user.model_access.has_capability_access", lambda _capability: False
        )
        activated: list[object] = []
        monkeypatch.setattr(
            notebook_admission,
            "activate_llm_selection",
            lambda selection: activated.append(selection),
        )

        async def invoke() -> None:
            async with notebook_admission.admitted_notebook_llm_call():
                raise AssertionError("ungranted learner must not reach the provider")

        with pytest.raises(notebook_admission.NotebookLLMAdmissionError):
            asyncio.run(invoke())
        assert activated == []
    finally:
        reset_current_user(token)


def test_notebook_admission_pins_the_first_available_live_grant(tmp_path, monkeypatch) -> None:
    token = set_current_user(_learner(tmp_path))
    try:
        monkeypatch.setattr(
            "deeptutor.multi_user.model_access.has_capability_access", lambda _capability: True
        )
        monkeypatch.setattr(
            "deeptutor.multi_user.model_access.redacted_model_access",
            lambda _user_id: {
                "llm": [
                    {"profile_id": "profile-1", "model_id": "model-1", "available": True},
                    {"profile_id": "profile-2", "model_id": "model-2", "available": True},
                ]
            },
        )
        monkeypatch.setattr(
            notebook_admission, "_selection_has_own_runtime_config", lambda _selection: True
        )
        selections: list[dict[str, str] | None] = []
        reset_tokens: list[object] = []
        marker = object()
        monkeypatch.setattr(
            notebook_admission,
            "activate_llm_selection",
            lambda selection: (selections.append(selection) or SimpleNamespace(), marker),
        )
        monkeypatch.setattr(
            notebook_admission, "reset_llm_selection", lambda value: reset_tokens.append(value)
        )

        async def invoke() -> None:
            async with notebook_admission.admitted_notebook_llm_call():
                pass

        asyncio.run(invoke())
        assert selections == [{"profile_id": "profile-1", "model_id": "model-1"}]
        assert reset_tokens == [marker]
    finally:
        reset_current_user(token)


def test_notebook_admission_enforces_process_local_rate_quota(tmp_path, monkeypatch) -> None:
    token = set_current_user(_learner(tmp_path))
    try:
        monkeypatch.setattr(
            "deeptutor.multi_user.model_access.has_capability_access", lambda _capability: True
        )
        monkeypatch.setattr(
            "deeptutor.multi_user.model_access.redacted_model_access",
            lambda _user_id: {
                "llm": [{"profile_id": "profile-1", "model_id": "model-1", "available": True}]
            },
        )
        monkeypatch.setattr(
            notebook_admission, "_selection_has_own_runtime_config", lambda _selection: True
        )
        monkeypatch.setattr(
            notebook_admission,
            "activate_llm_selection",
            lambda _selection: (SimpleNamespace(), object()),
        )
        monkeypatch.setattr(notebook_admission, "reset_llm_selection", lambda _token: None)
        monkeypatch.setattr(
            notebook_admission,
            "_NOTEBOOK_LLM_USER_QUOTA",
            UserExecQuota(max_concurrent=1, max_per_minute=1),
        )
        monkeypatch.setattr(
            notebook_admission,
            "_NOTEBOOK_LLM_GLOBAL_QUOTA",
            UserExecQuota(max_concurrent=1, max_per_minute=2),
        )

        async def invoke() -> None:
            async with notebook_admission.admitted_notebook_llm_call():
                pass

        asyncio.run(invoke())
        with pytest.raises(QuotaExceeded):
            asyncio.run(invoke())
    finally:
        reset_current_user(token)


def test_notebook_admission_rejects_credential_empty_profile_fallback(
    tmp_path, monkeypatch
) -> None:
    token = set_current_user(_learner(tmp_path))
    try:
        monkeypatch.setattr(
            "deeptutor.multi_user.model_access.has_capability_access", lambda _capability: True
        )
        monkeypatch.setattr(
            "deeptutor.multi_user.model_access.redacted_model_access",
            lambda _user_id: {
                "llm": [
                    {
                        "profile_id": "granted-empty",
                        "model_id": "model-a",
                        "model": "gpt-4o-mini",
                        "available": True,
                    }
                ]
            },
        )
        monkeypatch.setattr(
            "deeptutor.multi_user.model_access.admin_catalog",
            lambda: {
                "services": {
                    "llm": {
                        "profiles": [
                            {
                                "id": "granted-empty",
                                "binding": "openai",
                                "api_key": "",
                                "models": [{"id": "model-a", "model": "gpt-4o-mini"}],
                            },
                            {
                                "id": "ungranted-keyed",
                                "binding": "openai",
                                "api_key": "secret-not-used",
                                "models": [{"id": "model-b", "model": "gpt-4o-mini"}],
                            },
                        ]
                    }
                }
            },
        )
        activated: list[object] = []
        monkeypatch.setattr(
            notebook_admission,
            "activate_llm_selection",
            lambda selection: activated.append(selection),
        )

        async def invoke() -> None:
            async with notebook_admission.admitted_notebook_llm_call():
                raise AssertionError("credential fallback must not reach provider work")

        with pytest.raises(notebook_admission.NotebookLLMAdmissionError):
            asyncio.run(invoke())
        assert activated == []
    finally:
        reset_current_user(token)
