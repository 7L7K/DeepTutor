"""The built-in ``cron`` tool: schema contract, owner injection, actions."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from deeptutor.services.cron.service import CronOwner, CronService
from deeptutor.tools.cron_tool import run_cron_action


@pytest.fixture
def cron_service(tmp_path, monkeypatch):
    import deeptutor.services.cron.service as service_mod
    import deeptutor.tools.cron_tool as tool_mod

    service = CronService(store_path=tmp_path / "jobs.json")
    monkeypatch.setattr(service_mod, "_service", service)
    monkeypatch.setattr(tool_mod, "get_cron_service", lambda: service)
    return service


CHAT_OWNER = {"kind": "chat", "user_id": "local-admin", "session_id": "s1"}
PARTNER_OWNER = {
    "kind": "partner",
    "partner_id": "ada",
    "channel": "telegram",
    "chat_id": "42",
    "session_key": "telegram:42",
    "channel_meta": {"thread_ts": "111.222"},
}


class TestCronTool:
    def test_requires_injected_owner(self, cron_service):
        outcome = run_cron_action({"action": "schedule", "message": "x", "every_seconds": 60})
        assert outcome.ok is False
        assert "not available" in outcome.text

    def test_delegated_partner_cannot_touch_shared_cron_store(self, cron_service):
        from deeptutor.tools.partner_memory import delegated_partner_call

        with delegated_partner_call("u_learner"):
            outcome = run_cron_action(
                {
                    "action": "schedule",
                    "message": "run later as owner",
                    "every_seconds": 60,
                    "_cron_owner": PARTNER_OWNER,
                }
            )

        assert outcome.ok is False
        assert "assigned Partner" in outcome.text
        assert cron_service.list_jobs() == []

    def test_schedule_every_and_list_and_cancel(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "schedule",
                "message": "summarize my day",
                "name": "daily recap",
                "every_seconds": 3600,
                "_cron_owner": CHAT_OWNER,
            }
        )
        assert outcome.ok, outcome.text
        job_id = outcome.meta["job_id"]

        listed = run_cron_action({"action": "list", "_cron_owner": CHAT_OWNER})
        assert job_id in listed.text and "daily recap" in listed.text

        # Another owner can't see or cancel it.
        other = run_cron_action({"action": "list", "_cron_owner": PARTNER_OWNER})
        assert "No scheduled tasks" in other.text
        steal = run_cron_action(
            {"action": "cancel", "job_id": job_id, "_cron_owner": PARTNER_OWNER}
        )
        assert steal.ok is False

        cancelled = run_cron_action(
            {"action": "cancel", "job_id": job_id, "_cron_owner": CHAT_OWNER}
        )
        assert cancelled.ok, cancelled.text

    def test_schedule_caps_enabled_jobs_per_owner(self, cron_service, monkeypatch):
        import deeptutor.services.cron.service as service_mod

        monkeypatch.setattr(service_mod, "_MAX_ENABLED_JOBS_PER_OWNER", 2)
        monkeypatch.setattr(service_mod, "_MAX_ENABLED_JOBS_GLOBAL", 8)
        for message in ("first", "second"):
            outcome = run_cron_action(
                {
                    "action": "schedule",
                    "message": message,
                    "every_seconds": 60,
                    "_cron_owner": CHAT_OWNER,
                }
            )
            assert outcome.ok, outcome.text

        limited = run_cron_action(
            {
                "action": "schedule",
                "message": "third",
                "every_seconds": 60,
                "_cron_owner": CHAT_OWNER,
            }
        )

        assert limited.ok is False
        assert "owner limit reached (2 enabled jobs per owner)" in limited.text
        assert len(cron_service.list_jobs(owner_key="chat:local-admin")) == 2

    def test_schedule_caps_enabled_jobs_globally_without_collapsing_owners(
        self, cron_service, monkeypatch
    ):
        import deeptutor.services.cron.service as service_mod

        monkeypatch.setattr(service_mod, "_MAX_ENABLED_JOBS_PER_OWNER", 3)
        monkeypatch.setattr(service_mod, "_MAX_ENABLED_JOBS_GLOBAL", 3)
        owners = [
            CHAT_OWNER,
            PARTNER_OWNER,
            {"kind": "chat", "user_id": "u_other", "is_admin": False, "session_id": "s2"},
        ]
        for index, owner in enumerate(owners):
            outcome = run_cron_action(
                {
                    "action": "schedule",
                    "message": f"job {index}",
                    "every_seconds": 60,
                    "_cron_owner": owner,
                }
            )
            assert outcome.ok, outcome.text

        limited = run_cron_action(
            {
                "action": "schedule",
                "message": "one too many",
                "every_seconds": 60,
                "_cron_owner": CHAT_OWNER,
            }
        )

        assert limited.ok is False
        assert "global limit reached (3 enabled jobs)" in limited.text
        assert {job.owner.key for job in cron_service.list_jobs()} == {
            "chat:local-admin",
            "partner:ada",
            "chat:u_other",
        }

    def test_disabled_jobs_do_not_count_against_schedule_caps(self, cron_service, monkeypatch):
        import deeptutor.services.cron.service as service_mod

        monkeypatch.setattr(service_mod, "_MAX_ENABLED_JOBS_PER_OWNER", 1)
        monkeypatch.setattr(service_mod, "_MAX_ENABLED_JOBS_GLOBAL", 1)
        first = run_cron_action(
            {
                "action": "schedule",
                "message": "first",
                "every_seconds": 60,
                "_cron_owner": CHAT_OWNER,
            }
        )
        assert first.ok, first.text
        job = cron_service.get_job(first.meta["job_id"])
        assert job is not None
        job.enabled = False

        replacement = run_cron_action(
            {
                "action": "schedule",
                "message": "replacement",
                "every_seconds": 60,
                "_cron_owner": CHAT_OWNER,
            }
        )

        assert replacement.ok, replacement.text

    def test_nanobot_action_aliases(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "add",
                "message": "summarize my day",
                "every_seconds": 3600,
                "_cron_owner": CHAT_OWNER,
            }
        )
        assert outcome.ok, outcome.text
        job_id = outcome.meta["job_id"]

        cancelled = run_cron_action(
            {"action": "remove", "job_id": job_id, "_cron_owner": CHAT_OWNER}
        )
        assert cancelled.ok, cancelled.text

    def test_schedule_at_parses_iso(self, cron_service):
        from datetime import datetime, timedelta

        at = (datetime.now().astimezone() + timedelta(hours=1)).isoformat()
        outcome = run_cron_action(
            {"action": "schedule", "message": "remind me", "at": at, "_cron_owner": CHAT_OWNER}
        )
        assert outcome.ok, outcome.text
        job = cron_service.get_job(outcome.meta["job_id"])
        assert job is not None and job.schedule.kind == "at"
        assert job.delete_after_run is True

    def test_schedule_requires_exactly_one_kind(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "schedule",
                "message": "x",
                "every_seconds": 60,
                "cron_expr": "0 9 * * *",
                "_cron_owner": CHAT_OWNER,
            }
        )
        assert outcome.ok is False
        assert "exactly one" in outcome.text

    def test_schedule_rejected_inside_cron_context(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "schedule",
                "message": "x",
                "every_seconds": 60,
                "_cron_owner": CHAT_OWNER,
                "_cron_in_context": True,
            }
        )
        assert outcome.ok is False
        assert "inside a running scheduled task" in outcome.text

    def test_schedule_rejects_past_at(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "schedule",
                "message": "x",
                "at": "2020-01-01T00:00:00",
                "_cron_owner": CHAT_OWNER,
            }
        )
        assert outcome.ok is False
        assert "past" in outcome.text

    def test_partner_owner_round_trip(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "schedule",
                "message": "morning briefing",
                "cron_expr": "0 8 * * *",
                "tz": "Asia/Hong_Kong",
                "_cron_owner": PARTNER_OWNER,
            }
        )
        assert outcome.ok, outcome.text
        job = cron_service.get_job(outcome.meta["job_id"])
        assert job.owner.key == "partner:ada"
        assert job.owner.session_key == "telegram:42"
        assert job.owner.channel_meta == {"thread_ts": "111.222"}
        assert job.schedule.tz == "Asia/Hong_Kong"


class TestRegistryIntegration:
    def test_cron_tool_is_builtin_and_automounted(self):
        from deeptutor.agents._shared.tool_composition import AUTO_MOUNTED_TOOLS
        from deeptutor.tools.builtin import BUILTIN_TOOL_NAMES

        assert "cron" in BUILTIN_TOOL_NAMES
        assert "cron" in AUTO_MOUNTED_TOOLS

    def test_schema_has_action_enum(self):
        from deeptutor.tools.builtin import CronTool

        schema = CronTool().get_definition().to_openai_schema()
        action = schema["function"]["parameters"]["properties"]["action"]
        assert set(action["enum"]) == {"schedule", "list", "cancel"}


class TestExecutorRouting:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("builtin_grant", "expected"),
        [
            (["cron"], ["cron"]),
            (["cron", "web_fetch"], ["cron", "web_fetch"]),
        ],
    )
    async def test_chat_job_uses_owner_builtin_grant(self, monkeypatch, builtin_grant, expected):
        """A learner keeps only live explicitly granted auto-mounted tools."""
        from deeptutor.core.stream import StreamEventType
        from deeptutor.multi_user import identity, model_access, tool_access
        import deeptutor.runtime.orchestrator as orchestrator_mod
        from deeptutor.services.cron import executor
        from deeptutor.services.cron.service import CronJob, CronOwner, CronSchedule
        import deeptutor.services.model_selection.runtime as model_runtime
        import deeptutor.services.session as session_mod

        seen_contexts = []
        activated_selections = []
        reset_tokens = []

        class FakeStore:
            async def get_session(self, _session_id):
                return {"id": "s1"}

            async def get_messages_for_context(self, _session_id):
                return []

            async def add_message(self, **_kwargs):
                return None

        class FakeOrchestrator:
            async def handle(self, context):
                seen_contexts.append(context)
                yield SimpleNamespace(
                    type=StreamEventType.RESULT,
                    source="chat",
                    metadata={"response": "scheduled reply"},
                    content=None,
                )

        monkeypatch.setattr(
            tool_access,
            "load_grant",
            lambda user_id: {"builtin_tools": builtin_grant} if user_id == "u_learner" else {},
        )
        monkeypatch.setattr(
            identity,
            "get_user_by_id",
            lambda user_id: (
                (
                    "learner",
                    {"id": user_id, "role": "user", "disabled": False},
                )
                if user_id == "u_learner"
                else None
            ),
        )
        monkeypatch.setattr(model_access, "has_capability_access", lambda _capability: True)
        monkeypatch.setattr(
            model_access,
            "redacted_model_access",
            lambda _user_id: {
                "llm": [
                    {
                        "profile_id": "learner-profile",
                        "model_id": "learner-model",
                        "available": True,
                    }
                ]
            },
        )
        token = object()

        def activate(selection):
            activated_selections.append(selection)
            return SimpleNamespace(), token

        monkeypatch.setattr(model_runtime, "activate_llm_selection", activate)
        monkeypatch.setattr(model_runtime, "reset_llm_selection", reset_tokens.append)
        monkeypatch.setattr(session_mod, "get_sqlite_session_store", lambda: FakeStore())
        monkeypatch.setattr(orchestrator_mod, "ChatOrchestrator", FakeOrchestrator)
        monkeypatch.setattr(executor, "_maybe_send_desktop_notification", _noop_notify)
        job = CronJob(
            id="learner-job",
            name="review",
            message="review this",
            schedule=CronSchedule(kind="every", every_seconds=60),
            owner=CronOwner(kind="chat", user_id="u_learner", is_admin=False, session_id="s1"),
        )

        status, error = await executor.execute_job(job)

        assert (status, error) == ("ok", None)
        assert len(seen_contexts) == 1
        assert seen_contexts[0].allowed_builtin_tools == expected
        assert activated_selections == [
            {"profile_id": "learner-profile", "model_id": "learner-model"}
        ]
        assert reset_tokens == [token]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("live_owner", "builtin_grant", "has_model", "expected_error"),
        [
            (None, ["cron"], True, "no longer exists"),
            (("learner", {"role": "user", "disabled": True}), ["cron"], True, "is disabled"),
            (
                ("learner", {"role": "admin", "disabled": False}),
                ["cron"],
                True,
                "no longer a learner",
            ),
            (("learner", {"role": "user", "disabled": False}), [], True, "cron permission"),
            (
                ("learner", {"role": "user", "disabled": False}),
                ["cron"],
                False,
                "no usable assigned LLM model",
            ),
        ],
        ids=("revoked", "disabled", "wrong-role", "cron-grant-revoked", "model-revoked"),
    )
    async def test_chat_job_reauthorizes_live_learner_before_execution(
        self, monkeypatch, live_owner, builtin_grant, has_model, expected_error
    ):
        """Persisted learner jobs stop before touching their session when authority changes."""
        from deeptutor.multi_user import identity, model_access, tool_access
        from deeptutor.services.cron import executor
        from deeptutor.services.cron.service import CronJob, CronOwner, CronSchedule
        import deeptutor.services.session as session_mod

        monkeypatch.setattr(identity, "get_user_by_id", lambda _user_id: live_owner)
        monkeypatch.setattr(
            tool_access,
            "load_grant",
            lambda _user_id: {"builtin_tools": builtin_grant},
        )
        monkeypatch.setattr(model_access, "has_capability_access", lambda _capability: has_model)
        monkeypatch.setattr(
            session_mod,
            "get_sqlite_session_store",
            lambda: (_ for _ in ()).throw(
                AssertionError("unauthorized cron must not load a session")
            ),
        )
        job = CronJob(
            id="learner-job",
            name="review",
            message="review this",
            schedule=CronSchedule(kind="every", every_seconds=60),
            owner=CronOwner(kind="chat", user_id="u_learner", is_admin=False, session_id="s1"),
        )

        status, error = await executor.execute_job(job)

        assert status == "skipped"
        assert expected_error in (error or "")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("live_owner", "expected_error"),
        [
            (None, "no longer exists"),
            (("admin", {"role": "admin", "disabled": True}), "is disabled"),
            (("admin", {"role": "user", "disabled": False}), "no longer an administrator"),
        ],
        ids=("admin-revoked", "admin-disabled", "admin-demoted"),
    )
    async def test_admin_chat_job_reauthorizes_live_owner_before_admin_scope(
        self, monkeypatch, live_owner, expected_error
    ):
        """A persisted admin bit cannot keep using shared scope after revocation."""
        from deeptutor.multi_user import identity
        from deeptutor.services.cron import executor
        from deeptutor.services.cron.service import CronJob, CronOwner, CronSchedule
        import deeptutor.services.session as session_mod

        monkeypatch.setattr(identity, "get_user_by_id", lambda _user_id: live_owner)
        monkeypatch.setattr(
            session_mod,
            "get_sqlite_session_store",
            lambda: (_ for _ in ()).throw(
                AssertionError("stale admin cron must not load a session")
            ),
        )
        job = CronJob(
            id="admin-job",
            name="review",
            message="review this",
            schedule=CronSchedule(kind="every", every_seconds=60),
            owner=CronOwner(kind="chat", user_id="u_admin", is_admin=True, session_id="s1"),
        )

        status, error = await executor.execute_job(job)

        assert status == "skipped"
        assert expected_error in (error or "")

    @pytest.mark.asyncio
    async def test_admin_chat_job_with_missing_owner_id_fails_closed(self, monkeypatch):
        """A corrupt admin marker without the reserved sentinel cannot gain scope."""
        from deeptutor.multi_user import identity
        from deeptutor.services.cron import executor
        from deeptutor.services.cron.service import CronJob, CronOwner, CronSchedule
        import deeptutor.services.session as session_mod

        monkeypatch.setattr(identity, "get_user_by_id", lambda _user_id: None)
        monkeypatch.setattr(
            session_mod,
            "get_sqlite_session_store",
            lambda: (_ for _ in ()).throw(
                AssertionError("corrupt admin cron must not load a session")
            ),
        )
        job = CronJob(
            id="admin-missing-id",
            name="review",
            message="review this",
            schedule=CronSchedule(kind="every", every_seconds=60),
            owner=CronOwner(kind="chat", user_id="", is_admin=True, session_id="s1"),
        )

        status, error = await executor.execute_job(job)

        assert status == "skipped"
        assert "no longer exists" in (error or "")

    @pytest.mark.asyncio
    async def test_chat_job_keeps_admin_builtin_tools_unrestricted(self, monkeypatch):
        """The local admin remains the sole unrestricted cron owner."""
        from deeptutor.core.stream import StreamEventType
        import deeptutor.runtime.orchestrator as orchestrator_mod
        from deeptutor.services.cron import executor
        from deeptutor.services.cron.service import CronJob, CronOwner, CronSchedule
        import deeptutor.services.session as session_mod

        seen_contexts = []

        class FakeStore:
            async def get_session(self, _session_id):
                return {"id": "s1"}

            async def get_messages_for_context(self, _session_id):
                return []

            async def add_message(self, **_kwargs):
                return None

        class FakeOrchestrator:
            async def handle(self, context):
                seen_contexts.append(context)
                yield SimpleNamespace(
                    type=StreamEventType.RESULT,
                    source="chat",
                    metadata={"response": "scheduled reply"},
                    content=None,
                )

        monkeypatch.setattr(session_mod, "get_sqlite_session_store", lambda: FakeStore())
        monkeypatch.setattr(orchestrator_mod, "ChatOrchestrator", FakeOrchestrator)
        monkeypatch.setattr(executor, "_maybe_send_desktop_notification", _noop_notify)
        job = CronJob(
            id="admin-job",
            name="review",
            message="review this",
            schedule=CronSchedule(kind="every", every_seconds=60),
            owner=CronOwner(kind="chat", user_id="local-admin", session_id="s1", is_admin=True),
        )

        status, error = await executor.execute_job(job)

        assert (status, error) == ("ok", None)
        assert seen_contexts[0].allowed_builtin_tools is None

    @pytest.mark.asyncio
    async def test_delegated_partner_job_never_replays_as_owner(self, monkeypatch):
        from deeptutor.services.cron import executor
        from deeptutor.services.cron.service import CronJob, CronSchedule

        class ForbiddenManager:
            def get_partner(self, _partner_id):
                raise AssertionError("delegated cron must stop before Partner manager lookup")

        import deeptutor.services.partners as partners_mod

        monkeypatch.setattr(partners_mod, "get_partner_manager", lambda: ForbiddenManager())
        job = CronJob(
            id="delegated",
            name="unsafe",
            message="run later",
            schedule=CronSchedule(kind="every", every_seconds=60),
            owner=CronOwner(kind="partner", partner_id="ada", delegated_user_id="u_learner"),
        )

        status, error = await executor.execute_job(job)

        assert status == "skipped"
        assert "assigned Partner" in (error or "")

    @pytest.mark.asyncio
    async def test_partner_job_runs_and_publishes_outbound(self, monkeypatch):
        from deeptutor.services.cron import executor
        from deeptutor.services.cron.service import CronJob, CronOwner, CronSchedule

        processed = []
        published = []

        class FakeBus:
            async def publish_outbound(self, msg):
                published.append(msg)

        class FakeRunner:
            bus = FakeBus()

            async def process_message(self, msg, *, delivery_meta=None):
                processed.append(msg)
                if delivery_meta is not None:
                    delivery_meta["delivered_via"] = "test"
                return "Reminder: stretch"

        class FakeInstance:
            running = True
            runner = FakeRunner()

        class FakeMgr:
            def get_partner(self, partner_id):
                return FakeInstance() if partner_id == "ada" else None

        import deeptutor.services.partners as partners_mod

        monkeypatch.setattr(partners_mod, "get_partner_manager", lambda: FakeMgr())
        monkeypatch.setattr(executor, "_maybe_send_desktop_notification", _noop_notify)

        job = CronJob(
            id="j1",
            name="briefing",
            message="what's new today?",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=CronOwner(
                kind="partner",
                partner_id="ada",
                channel="telegram",
                chat_id="42",
                session_key="telegram:42",
                channel_meta={"thread_ts": "111.222"},
            ),
        )
        status, error = await executor.execute_job(job)
        assert (status, error) == ("ok", None)
        assert len(processed) == 1
        inbound = processed[0]
        assert inbound.channel == "telegram" and inbound.chat_id == "42"
        assert inbound.session_key == "telegram:42"
        assert "what's new today?" in inbound.content
        assert inbound.metadata["_cron_job_id"] == "j1"
        assert inbound.metadata["thread_ts"] == "111.222"

        assert len(published) == 1
        outbound = published[0]
        assert outbound.channel == "telegram" and outbound.chat_id == "42"
        assert outbound.content == "Reminder: stretch"
        assert outbound.metadata["_cron_job_id"] == "j1"
        assert outbound.metadata["thread_ts"] == "111.222"
        assert outbound.metadata["delivered_via"] == "test"

    @pytest.mark.asyncio
    async def test_partner_job_skipped_when_not_running(self, monkeypatch):
        from deeptutor.services.cron import executor
        from deeptutor.services.cron.service import CronJob, CronOwner, CronSchedule

        class FakeMgr:
            def get_partner(self, partner_id):
                return None

        import deeptutor.services.partners as partners_mod

        monkeypatch.setattr(partners_mod, "get_partner_manager", lambda: FakeMgr())
        monkeypatch.setattr(executor, "_maybe_send_desktop_notification", _noop_notify)

        job = CronJob(
            id="j2",
            name="x",
            message="y",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=CronOwner(kind="partner", partner_id="ghost"),
        )
        status, error = await executor.execute_job(job)
        assert status == "skipped"
        assert "not running" in (error or "")


async def _noop_notify(*_args, **_kwargs):
    return None
