"""Authenticated Course aggregate service."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path
import threading
from typing import Any
from weakref import WeakKeyDictionary

from deeptutor.multi_user.context import get_current_user_or_none, set_current_user
from deeptutor.multi_user.models import CurrentUser
from deeptutor.multi_user.paths import get_personal_path_service, personal_scope_for_user
from deeptutor.services.pocketbase_client import is_pocketbase_enabled

from .models import Course, CourseSource
from .repository import CourseRepository


class CourseUnavailableError(RuntimeError):
    pass


def source_kb_name(course_id: str, source_id: str) -> str:
    """Return the opaque physical index shard for one immutable source."""
    return f"course_{course_id}_{source_id}"


def source_kb_ref(course_id: str, source_id: str) -> str:
    return f"personal:kb:{source_kb_name(course_id, source_id)}"


_course_lock_guard = threading.Lock()
_course_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = (
    WeakKeyDictionary()
)


def course_operation_lock(course_id: str) -> asyncio.Lock:
    """Return the per-loop lifecycle lock for one Course aggregate."""
    loop = asyncio.get_running_loop()
    with _course_lock_guard:
        by_course = _course_locks.setdefault(loop, {})
        if course_id not in by_course and len(by_course) >= 512:
            for stale_id, stale_lock in list(by_course.items()):
                if not stale_lock.locked():
                    by_course.pop(stale_id, None)
                if len(by_course) < 512:
                    break
        return by_course.setdefault(course_id, asyncio.Lock())


@lru_cache(maxsize=128)
def _repository_for(db_path: str, owner_user_id: str) -> CourseRepository:
    return CourseRepository(Path(db_path), owner_user_id)


class CourseService:
    def __init__(self, repository: CourseRepository) -> None:
        self.repository = repository

    @property
    def owner_user_id(self) -> str:
        return self.repository.owner_user_id

    def create(self, title: str) -> Course:
        return self.repository.create_course(title)

    def list(self, *, include_archived: bool = True) -> list[Course]:
        return self.repository.list_courses(include_archived=include_archived)

    def get(self, course_id: str) -> Course:
        return self.repository.get_course(course_id)

    def rename(self, course_id: str, title: str, expected_revision: int) -> Course:
        return self.repository.update_course_title(course_id, title, expected_revision)

    def _reconcile_abandoned_sources(
        self, course_id: str, sources: list[CourseSource] | None = None
    ) -> int:
        """Fail only operations absent from the full live set for this Course."""
        from deeptutor.api.utils.task_id_manager import TaskIDManager

        sources = sources if sources is not None else self.repository.list_sources(course_id)
        manager = TaskIDManager.get_instance()
        active = {
            source.operation_id
            for source in sources
            if source.operation_id
            and (manager.get_task_metadata(source.operation_id) or {}).get("status") == "running"
        }
        return self.repository.reconcile_abandoned_sources(
            active_operation_ids=active,
            course_id=course_id,
            older_than_seconds=0,
            candidate_source_ids={source.id for source in sources},
        )

    async def archive(self, course_id: str, expected_revision: int) -> Course:
        from deeptutor.services.session import (
            get_personal_sqlite_session_store,
            get_turn_runtime_manager,
        )

        async with course_operation_lock(course_id):
            self._reconcile_abandoned_sources(course_id)
            store = get_personal_sqlite_session_store()
            runtime = get_turn_runtime_manager(personal=True)
            await runtime.recover_orphan_course_turns(course_id)
            if (
                await store.has_active_course_turn(course_id)
                or await runtime.has_live_course_turn(course_id)
            ):
                from .repository import CourseConflictError

                raise CourseConflictError("Course has an active turn")
            return self.repository.archive_course(course_id, expected_revision)

    def restore(self, course_id: str, expected_revision: int) -> Course:
        return self.repository.restore_course(course_id, expected_revision)

    def list_sources(self, course_id: str) -> list[CourseSource]:
        sources = self.repository.list_sources(course_id)
        if self._reconcile_abandoned_sources(course_id, sources):
            return self.repository.list_sources(course_id)
        return sources

    def get_source(self, course_id: str, source_id: str) -> CourseSource:
        return self.repository.get_source(course_id, source_id)

    def reconcile_source_for_progress(
        self, course_id: str, source_id: str
    ) -> CourseSource:
        """Return a terminal restart-safe source state for progress streaming.

        Background-task metadata is process-local. If a processing row has no
        live task in this process, the server restarted (or dispatch failed),
        so the exact source is failed immediately instead of opening an SSE
        stream that can never terminate. A ready row is already authoritative
        even if the process crashed before publishing its completion event.
        """
        from deeptutor.api.utils.task_id_manager import TaskIDManager

        source = self.repository.get_source(course_id, source_id)
        metadata = (
            TaskIDManager.get_instance().get_task_metadata(source.operation_id)
            if source.operation_id
            else None
        )
        if source.state == "processing" and not (metadata or {}).get("status") == "running":
            # Reconcile against every live operation in the parent Course. An
            # orphan progress request must never fail a different active source.
            self._reconcile_abandoned_sources(course_id)
            source = self.repository.get_source(course_id, source_id)
        return source

    async def archive_source(
        self, course_id: str, source_id: str, expected_revision: int
    ) -> CourseSource:
        from deeptutor.services.session import (
            get_personal_sqlite_session_store,
            get_turn_runtime_manager,
        )

        store = get_personal_sqlite_session_store()
        runtime = get_turn_runtime_manager(personal=True)
        self._reconcile_abandoned_sources(course_id)
        await runtime.recover_orphan_course_turns(course_id)
        if (
            await store.has_active_course_turn(course_id)
            or await runtime.has_live_course_turn(course_id)
        ):
            from .repository import CourseConflictError

            raise CourseConflictError("Course has an active turn")
        return self.repository.archive_source(course_id, source_id, expected_revision)


def get_current_course_service() -> CourseService:
    if is_pocketbase_enabled():
        raise CourseUnavailableError(
            "Private courses require the supported local JSON/SQLite multi-user backend"
        )
    user = get_current_user_or_none()
    if user is None:
        raise CourseUnavailableError("Authenticated user context is required")
    paths = get_personal_path_service(user.id)
    repository = _repository_for(str(paths.get_courses_db()), user.id)
    return CourseService(repository)


def install_personal_course_context() -> None:
    """Route ambient Course work to the authenticated user's private scope."""
    user = get_current_user_or_none()
    if user is None:
        raise CourseUnavailableError("Authenticated user context is required")
    set_current_user(
        CurrentUser(
            id=user.id,
            username=user.username,
            role=user.role,
            scope=personal_scope_for_user(user.id),
        )
    )


def resolve_course_turn_payload(
    course_id: str,
    payload: dict[str, Any],
    *,
    preserved_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve all course resources server-side before the generic turn runtime."""
    service = get_current_course_service()
    course = service.get(course_id)
    if course.state != "active":
        raise CourseUnavailableError("Archived courses cannot start or regenerate turns")

    capability = str(payload.get("capability") or "chat")
    if capability not in {"chat", "mastery_path"}:
        raise CourseUnavailableError("Only Chat and Mastery Path are available in Course mode")

    forbidden_fields = (
        "attachments",
        "notebook_references",
        "history_references",
        "question_notebook_references",
        "book_references",
        "memory_references",
    )
    for field in forbidden_fields:
        if payload.get(field):
            raise CourseUnavailableError(f"{field} is not available in private course mode")

    all_sources = service.list_sources(course_id)
    if preserved_context is not None:
        if str(preserved_context.get("course_id") or "") != course.id:
            raise CourseUnavailableError("Regeneration Course provenance is invalid")
        by_id = {source.id: source for source in all_sources}
        source_ids = [str(item) for item in preserved_context.get("source_ids") or []]
        revisions = dict(preserved_context.get("source_revisions") or {})
        fingerprints = dict(preserved_context.get("source_fingerprints") or {})
        sources = []
        for source_id in source_ids:
            source = by_id.get(source_id)
            expected_revision = int(revisions.get(source_id) or 0)
            revision_matches = source is not None and (
                source.revision == expected_revision
                or (
                    source.state == "archived"
                    and source.revision == expected_revision + 1
                )
            )
            if (
                source is None
                or source.state not in {"ready", "archived"}
                or not revision_matches
                or source.content_sha256 != str(fingerprints.get(source_id) or "")
            ):
                raise CourseUnavailableError(
                    "Regeneration Course source provenance is unavailable"
                )
            sources.append(source)
    else:
        superseded_ids = {
            source.supersedes_source_id
            for source in all_sources
            if source.supersedes_source_id and source.state in {"ready", "archived"}
        }
        sources = [
            source
            for source in all_sources
            if source.state == "ready" and source.id not in superseded_ids
        ]
    # ``managed_kb_ref`` is the one logical Course Knowledge authority.  Each
    # immutable source is indexed into an opaque physical shard so archived,
    # failed, stale, and superseded sources can never remain searchable through
    # another ready source's shared index.
    derived_kbs = [source_kb_ref(course.id, source.id) for source in sources]
    client_kbs = [str(item) for item in payload.get("knowledge_bases") or [] if str(item)]
    if client_kbs and client_kbs != derived_kbs:
        raise CourseUnavailableError("Course Knowledge is resolved by the server")

    from deeptutor.multi_user.knowledge_access import set_managed_course_kb_authority

    set_managed_course_kb_authority(
        [str(ref).removeprefix("personal:kb:") for ref in derived_kbs]
    )

    course_context = (
        dict(preserved_context)
        if preserved_context is not None
        else {
            "course_id": course.id,
            "course_revision": course.revision,
            "course_write_epoch": course.write_epoch,
            "source_ids": [source.id for source in sources],
            "source_revisions": {source.id: source.revision for source in sources},
            "source_fingerprints": {
                source.id: source.content_sha256 for source in sources
            },
        }
    )
    return {
        **payload,
        "course_id": course.id,
        "mastery_path_id": course.learning_path_id,
        "knowledge_bases": derived_kbs,
        # ``tools=[]`` disables user-toggleable tools, but chat also has
        # context/always-on auto-mounts (memory, notebooks, web_fetch, github,
        # cron, exec, ...).  Course sources are untrusted documents, so limit
        # that built-in surface to server-derived retrieval only.  Mastery's
        # Course-local tools are capability-owned and intentionally unaffected.
        "allowed_builtin_tools": ["rag"],
        "tools": [],
        "attachments": [],
        "notebook_references": [],
        "history_references": [],
        "question_notebook_references": [],
        "book_references": [],
        "memory_references": [],
        "course_context": course_context,
    }
