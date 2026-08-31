"""Run a due cron job for its owner (chat session or partner conversation)."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any
import uuid

from deeptutor.services.cron.service import CronJob

logger = logging.getLogger(__name__)


async def execute_job(job: CronJob) -> tuple[str, str | None]:
    """Returns ``(status, error)`` — status is ok/error/skipped."""
    if job.owner.kind == "partner":
        return await _execute_partner_job(job)
    return await _execute_chat_job(job)


def _reminder_prompt(job: CronJob) -> str:
    return (
        "The scheduled time has arrived. Deliver this reminder to the user now, "
        "as a brief and natural message in their language. Speak directly to them; "
        "do not narrate scheduler status or mention internal job ids.\n\n"
        f"Reminder: {job.message}"
    )


def _notification_text(text: str, *, limit: int = 240) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


async def _maybe_send_desktop_notification(job: CronJob, text: str) -> None:
    """Best-effort local desktop notification for interactive reminders.

    DeepTutor still persists/delivers through its normal chat or partner
    channel. This is only a convenience for local macOS runs; failures are
    deliberately non-fatal because launchd/headless servers often cannot
    show notifications.
    """
    if sys.platform != "darwin":
        return
    if not text.strip():
        return
    if job.owner.kind == "partner" and (job.owner.channel or "web") != "web":
        return

    title = f"DeepTutor: {job.name or 'Reminder'}"
    body = _notification_text(text)
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript",
            "-e",
            "on run argv",
            "-e",
            "display notification (item 1 of argv) with title (item 2 of argv)",
            "-e",
            "end run",
            body,
            title,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode:
            logger.debug("macOS notification failed: %s", stderr.decode(errors="ignore"))
    except Exception:
        logger.debug("macOS notification failed", exc_info=True)


async def _execute_partner_job(job: CronJob) -> tuple[str, str | None]:
    """Run the partner turn and publish the reply through the original channel."""
    from deeptutor.partners.bus.events import InboundMessage
    from deeptutor.services.partners import get_partner_manager

    # Provenance-free legacy jobs cannot be distinguished from legitimate
    # owner jobs in code. Deployments upgrading from delegated-cron builds must
    # remove or migrate those records before enabling the scheduler.
    if job.owner.delegated_user_id:
        return "skipped", "assigned Partner scheduled jobs are disabled"

    instance = get_partner_manager().get_partner(job.owner.partner_id)
    if not instance or not instance.running or not instance.runner:
        return "skipped", "partner not running"

    metadata = dict(job.owner.channel_meta or {})
    metadata["_cron_job_id"] = job.id
    msg = InboundMessage(
        channel=job.owner.channel or "web",
        sender_id="cron",
        chat_id=job.owner.chat_id or "cron",
        content=_reminder_prompt(job),
        metadata=metadata,
        session_key_override=job.owner.session_key or None,
    )
    delivery_meta: dict[str, Any] = dict(job.owner.channel_meta or {})
    try:
        final = await instance.runner.process_message(msg, delivery_meta=delivery_meta)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Partner cron job %s failed", job.id)
        return "error", f"{type(exc).__name__}: {exc}"

    final = final.strip()
    if not final:
        return "error", "turn produced no answer"

    if not delivery_meta.get("_streamed"):
        from deeptutor.partners.bus.events import OutboundMessage

        delivery_meta["_cron_job_id"] = job.id
        await instance.runner.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=final,
                metadata=delivery_meta,
            )
        )
    await _maybe_send_desktop_notification(job, final)
    return "ok", None


async def _execute_chat_job(job: CronJob) -> tuple[str, str | None]:
    """Run one chat turn in the owner's scope and append the exchange to the
    originating session, so the result is waiting in their chat history."""
    from deeptutor.core.context import UnifiedContext
    from deeptutor.core.stream import StreamEventType
    from deeptutor.multi_user.models import LOCAL_ADMIN_ID, CurrentUser
    from deeptutor.multi_user.paths import local_admin_user, scope_for_user, user_context
    from deeptutor.runtime.orchestrator import ChatOrchestrator
    from deeptutor.services.session import get_sqlite_session_store

    # The single-user runtime has no durable identity record for its local
    # administrator.  Preserve that narrowly-defined sentinel, but never
    # treat an arbitrary persisted ``is_admin`` bit as live authority.
    if job.owner.is_admin and job.owner.user_id == LOCAL_ADMIN_ID:
        user = local_admin_user()
    else:
        # Jobs persist longer than a login session.  Re-resolve the owner
        # instead of trusting a historical username/role snapshot so a removed,
        # disabled, or reclassified learner cannot keep spending shared model
        # capacity through an old scheduled job.
        from deeptutor.multi_user.identity import get_user_by_id

        live_owner = get_user_by_id(job.owner.user_id)
        if live_owner is None:
            return "skipped", "scheduled job owner no longer exists"
        username, record = live_owner
        if record.get("disabled") is True:
            return "skipped", "scheduled job owner is disabled"
        live_role = str(record.get("role") or "user")
        expected_role = "admin" if job.owner.is_admin else "user"
        if live_role != expected_role:
            return "skipped", (
                "scheduled job owner is no longer an administrator"
                if expected_role == "admin"
                else "scheduled job owner is no longer a learner"
            )
        user = CurrentUser(
            id=job.owner.user_id,
            username=username,
            role=live_role,
            scope=scope_for_user(job.owner.user_id, is_admin=live_role == "admin"),
        )

    prompt = _reminder_prompt(job)
    with user_context(user):
        # Cron re-enters the chat pipeline without going through turn_runtime,
        # so it must reconstruct the same server-owned built-in-tool boundary
        # here.  A scheduled job is not an authority escalation for its owner.
        from deeptutor.multi_user.tool_access import allowed_builtin_tools

        allowed_builtins = allowed_builtin_tools()
        llm_scope_token = None
        reset_llm_selection = None
        if not user.is_admin:
            # A learner must retain the cron built-in grant at execution time;
            # possessing a job record is not a standing permission.  Resolve
            # one currently usable assigned model and install it in this task's
            # context so the scheduled turn cannot use deployment-global LLM
            # settings as a fallback.
            if allowed_builtins is None or "cron" not in allowed_builtins:
                return "skipped", "scheduled job no longer has cron permission"
            from deeptutor.multi_user.model_access import (
                has_capability_access,
                redacted_model_access,
            )

            if not has_capability_access("llm"):
                return "skipped", "scheduled job owner has no usable assigned LLM model"
            assigned_llms = [
                item
                for item in redacted_model_access(user.id).get("llm", [])
                if isinstance(item, dict)
                and item.get("available")
                and str(item.get("profile_id") or "").strip()
                and str(item.get("model_id") or "").strip()
            ]
            if not assigned_llms:
                return "skipped", "scheduled job owner has no usable assigned LLM model"
            selection = {
                "profile_id": assigned_llms[0].get("profile_id"),
                "model_id": assigned_llms[0].get("model_id"),
            }
            from deeptutor.services.model_selection.runtime import (
                activate_llm_selection,
            )
            from deeptutor.services.model_selection.runtime import (
                reset_llm_selection as reset_active_llm_selection,
            )

            try:
                _config, llm_scope_token = activate_llm_selection(selection)
            except (RuntimeError, ValueError) as exc:
                logger.warning("Cron job %s could not activate its assigned model: %s", job.id, exc)
                return "skipped", "scheduled job owner has no usable assigned LLM model"
            reset_llm_selection = reset_active_llm_selection

        try:
            store = get_sqlite_session_store()
            session = await store.get_session(job.owner.session_id)
            if session is None:
                return "error", "session no longer exists"

            history = await store.get_messages_for_context(job.owner.session_id)
            context = UnifiedContext(
                session_id=job.owner.session_id,
                user_message=prompt,
                conversation_history=[
                    {"role": m.get("role"), "content": m.get("content")}
                    for m in history
                    if m.get("role") in {"user", "assistant"} and m.get("content")
                ],
                allowed_builtin_tools=(
                    None if allowed_builtins is None else sorted(allowed_builtins)
                ),
                active_capability="chat",
                language=job.owner.language or "en",
                metadata={
                    "turn_id": f"cron-{job.id}-{uuid.uuid4().hex[:8]}",
                    "source": "cron",
                    "cron_job_id": job.id,
                },
            )

            final_text = ""
            errors: list[str] = []
            async for event in ChatOrchestrator().handle(context):
                meta: dict[str, Any] = event.metadata or {}
                if event.type == StreamEventType.RESULT and event.source == "chat":
                    final_text = str(meta.get("response") or "")
                elif event.type == StreamEventType.ERROR and event.content:
                    errors.append(event.content)

            if not final_text.strip():
                return "error", (errors[-1] if errors else "turn produced no answer")

            await store.add_message(
                session_id=job.owner.session_id,
                role="user",
                content=prompt,
                capability="chat",
                metadata={"cron_job_id": job.id},
            )
            await store.add_message(
                session_id=job.owner.session_id,
                role="assistant",
                content=final_text,
                capability="chat",
                metadata={"cron_job_id": job.id},
            )
            await _maybe_send_desktop_notification(job, final_text)
        finally:
            if reset_llm_selection is not None:
                reset_llm_selection(llm_scope_token)
    return "ok", None


__all__ = ["execute_job"]
