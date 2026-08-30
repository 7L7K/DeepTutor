"""Owned Course-source ingestion built on the existing Knowledge pipeline."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import stat
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from deeptutor.api.utils.task_id_manager import TaskIDManager
from deeptutor.api.utils.task_log_stream import get_task_stream_manager
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.grants import load_grant
from deeptutor.multi_user.identity import get_user_by_id
from deeptutor.multi_user.models import LOCAL_ADMIN_ID, LOCAL_ADMIN_USERNAME, CurrentUser
from deeptutor.multi_user.paths import (
    get_personal_path_service,
    personal_scope_for_user,
    restrict_private_tree_permissions,
)
from deeptutor.services.config import load_auth_settings

from .models import CourseSource
from .repository import CourseConflictError, CourseRepository
from .service import (
    get_current_course_service,
    install_personal_course_context,
    source_kb_name,
)
from .source_admission import (
    CourseSourceAdmissionError,
    CourseSourceAdmissionLimitError,
    get_course_source_admission_ledger,
)

logger = logging.getLogger(__name__)

COURSE_SOURCE_MAX_FILES = 10
COURSE_SOURCE_MAX_BATCH_BYTES = 10 * 1024 * 1024
COURSE_SOURCE_MAX_USER_STORAGE_BYTES = 1024 * 1024 * 1024
COURSE_SOURCE_MIN_STORAGE_RESERVATION_BYTES = 32 * 1024 * 1024
COURSE_SOURCE_INDEX_EXPANSION_MULTIPLIER = 8


@dataclass(frozen=True)
class CourseSourceStorageAdmission:
    input_bytes: int
    tree_bytes_before: int
    reserved_growth_bytes: int


def _private_tree_size(root: Path) -> int:
    """Count regular-file bytes and fail closed on unsafe filesystem entries."""
    try:
        root_stat = root.lstat()
    except FileNotFoundError:
        return 0
    total = 0
    expected_uid = os.geteuid() if hasattr(os, "geteuid") else None
    try:
        if (
            stat.S_ISLNK(root_stat.st_mode)
            or not stat.S_ISDIR(root_stat.st_mode)
            or (expected_uid is not None and root_stat.st_uid != expected_uid)
        ):
            raise OSError("unsafe private Course storage root")
        for path in root.rglob("*"):
            path_stat = path.lstat()
            if expected_uid is not None and path_stat.st_uid != expected_uid:
                raise OSError("foreign-owned entry inside private Course storage")
            if stat.S_ISLNK(path_stat.st_mode):
                raise OSError("symbolic link inside private Course storage")
            if stat.S_ISREG(path_stat.st_mode):
                if path_stat.st_nlink > 1:
                    raise OSError("hard link inside private Course storage")
                total += path_stat.st_size
            elif not stat.S_ISDIR(path_stat.st_mode):
                raise OSError("non-regular entry inside private Course storage")
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail="Course storage quota could not be verified",
        ) from exc
    return total


def _admit_source_batch(
    preflight: list[dict[str, int | str | None]],
    *,
    storage_root: Path,
) -> CourseSourceStorageAdmission:
    """Apply the controlled-beta request and per-user lifetime storage caps."""
    if len(preflight) > COURSE_SOURCE_MAX_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"A Course material upload may contain at most {COURSE_SOURCE_MAX_FILES} files",
        )
    if any(str(item.get("path") or "").lower().endswith(".zip") for item in preflight):
        raise HTTPException(
            status_code=400,
            detail="ZIP archives are not accepted for bounded Course material uploads",
        )
    sizes = [item.get("size_bytes") for item in preflight]
    if any(not isinstance(size, int) or isinstance(size, bool) or size < 0 for size in sizes):
        raise HTTPException(status_code=400, detail="Course material size could not be verified")
    batch_bytes = sum(int(size) for size in sizes)
    if batch_bytes > COURSE_SOURCE_MAX_BATCH_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Course material upload exceeds the 10 MiB batch limit",
        )
    tree_bytes_before = _private_tree_size(storage_root)
    reserved_growth_bytes = max(
        COURSE_SOURCE_MIN_STORAGE_RESERVATION_BYTES,
        batch_bytes * COURSE_SOURCE_INDEX_EXPANSION_MULTIPLIER,
    )
    if (
        tree_bytes_before + reserved_growth_bytes
        > COURSE_SOURCE_MAX_USER_STORAGE_BYTES
    ):
        raise HTTPException(
            status_code=413,
            detail="Course material storage quota reached",
        )
    return CourseSourceStorageAdmission(
        input_bytes=batch_bytes,
        tree_bytes_before=tree_bytes_before,
        reserved_growth_bytes=reserved_growth_bytes,
    )


def _owned_kb_dir(task: dict[str, Any]) -> Path:
    required = {"owner_user_id", "course_id", "source_id", "base_dir", "kb_name"}
    if not required.issubset(task):
        raise ValueError("Course Knowledge shard identity is incomplete")
    owner_user_id = str(task["owner_user_id"])
    course_id = str(task["course_id"])
    source_id = str(task["source_id"])
    canonical_base = (
        get_personal_path_service(owner_user_id)
        .get_knowledge_bases_root()
        .absolute()
    )
    base_dir = Path(str(task["base_dir"])).absolute()
    if (
        base_dir != canonical_base
        or base_dir.is_symlink()
        or base_dir.resolve(strict=False) != canonical_base.resolve(strict=False)
    ):
        raise ValueError("Course Knowledge root is unsafe")
    kb_name = str(task["kb_name"])
    expected_name = source_kb_name(course_id, source_id)
    if (
        kb_name != expected_name
        or kb_name in {".", ".."}
        or Path(kb_name).parts != (kb_name,)
    ):
        raise ValueError("Course Knowledge shard name is unsafe")
    candidate = base_dir / kb_name
    if candidate.parent != base_dir:
        raise ValueError("Course Knowledge shard parent is unsafe")
    return candidate


def _remove_owned_kb_shard(task: dict[str, Any]) -> None:
    """Remove only the exact opaque shard owned by this failed operation."""
    if not {
        "owner_user_id",
        "course_id",
        "source_id",
        "base_dir",
        "kb_name",
    }.issubset(task):
        return
    try:
        kb_dir = _owned_kb_dir(task)
        if kb_dir.is_symlink():
            kb_dir.unlink(missing_ok=True)
        elif kb_dir.exists():
            shutil.rmtree(kb_dir)
    except Exception:
        logger.exception("Could not clean failed Course Knowledge shard")


def _seal_and_verify_source_storage(task: dict[str, Any]) -> None:
    """Enforce reserved index growth before a source can become authority."""
    try:
        base_dir = Path(str(task["base_dir"])).absolute()
        kb_dir = _owned_kb_dir(task)
        if kb_dir.exists():
            restrict_private_tree_permissions(kb_dir)
        total_bytes = _private_tree_size(base_dir)
        shard_bytes = _private_tree_size(kb_dir)
        tree_bytes_before = int(task["tree_bytes_before"])
        reserved_growth_bytes = int(task["reserved_growth_bytes"])
        if (
            total_bytes > COURSE_SOURCE_MAX_USER_STORAGE_BYTES
            or shard_bytes > reserved_growth_bytes
            or total_bytes - tree_bytes_before > reserved_growth_bytes
        ):
            raise HTTPException(
                status_code=413,
                detail="Course material index exceeded its storage reservation",
            )
    except Exception:
        _remove_owned_kb_shard(task)
        raise


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(raw_root: Path, paths: list[str]) -> tuple[list[dict[str, Any]], str]:
    entries: list[dict[str, Any]] = []
    for raw_path in sorted({str(Path(item).resolve()) for item in paths}):
        path = Path(raw_path)
        relative = path.resolve().relative_to(raw_root.resolve()).as_posix()
        entries.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    encoded = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return entries, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _logical_kb_name(course_id: str) -> str:
    return f"course_{course_id}"


def _personal_kb_ref(course_id: str) -> str:
    return f"personal:kb:{_logical_kb_name(course_id)}"


def prepare_source_upload(
    *,
    course_id: str,
    files: list[UploadFile],
    kind: str,
    display_name: str,
    rag_provider: str | None,
    rel_paths: list[str] | None,
    supersedes_source_id: str | None,
    idempotency_key: str,
) -> tuple[CourseSource, dict[str, Any] | None]:
    """Validate, persist a processing record, and stage files without indexing."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one source file is required")

    # Course Knowledge is always role-independent personal storage, including for admins.
    install_personal_course_context()
    service = get_current_course_service()
    course = service.get(course_id)
    if course.workspace_kind != "academic_course":
        raise CourseConflictError(
            "General Study cannot accept Course sources or Knowledge"
        )
    if course.state != "active":
        raise CourseConflictError("Archived courses cannot accept sources")

    from deeptutor.api.routers.knowledge import (
        _assert_provider_ready,
        _enforce_provider_formats,
        _save_uploaded_files,
        _validate_registered_provider,
        _validate_upload_batch,
    )
    from deeptutor.knowledge.initializer import KnowledgeBaseInitializer
    from deeptutor.knowledge.manager import KnowledgeBaseManager
    from deeptutor.services.rag.factory import DEFAULT_PROVIDER, has_ready_provider_index
    from deeptutor.services.rag.file_routing import FileTypeRouter

    provider = _validate_registered_provider(rag_provider or DEFAULT_PROVIDER)
    from deeptutor.courses.deterministic_provider import enabled as deterministic_enabled

    if not deterministic_enabled():
        _assert_provider_ready(provider)
    _enforce_provider_formats(provider, files)
    allowed_extensions = FileTypeRouter.get_supported_extensions()
    preflight = _validate_upload_batch(
        files, allowed_extensions=allowed_extensions, rel_paths=rel_paths
    )

    kb_ref = _personal_kb_ref(course.id)
    if course.managed_kb_ref and course.managed_kb_ref != kb_ref:
        raise CourseConflictError("Course Knowledge reference is invalid")
    course = service.repository.ensure_managed_kb_ref(course.id, kb_ref)

    existing = service.repository.get_source_by_idempotency_key(course.id, idempotency_key)
    if existing is not None:
        if (
            existing.kind != " ".join(str(kind or "").split())
            or existing.display_name != " ".join(str(display_name or "").split())
            or existing.supersedes_source_id != supersedes_source_id
        ):
            raise CourseConflictError("Idempotency key was already used for another source")
        return existing, None

    base_dir = get_personal_path_service(service.owner_user_id).get_knowledge_bases_root()
    storage_admission = _admit_source_batch(preflight, storage_root=base_dir)

    source_admission_id = f"csi_{uuid4().hex}"
    try:
        get_course_source_admission_ledger().admit(
            operation_id=source_admission_id,
            owner_user_id=service.owner_user_id,
            provider=provider,
            admitted_input_bytes=storage_admission.input_bytes,
        )
    except CourseSourceAdmissionLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail="Course material upload budget reached",
        ) from exc
    except (CourseSourceAdmissionError, OSError, sqlite3.Error) as exc:
        raise HTTPException(
            status_code=503,
            detail="Course material upload admission is unavailable",
        ) from exc
    operation_id = TaskIDManager.get_instance().generate_task_id(
        "course_source", f"{course.id}:{uuid4().hex}"
    )
    TaskIDManager.get_instance().update_task_status(
        operation_id,
        "running",
        owner_user_id=service.owner_user_id,
        course_id=course.id,
        private_course=True,
        source_admission_id=source_admission_id,
    )
    get_task_stream_manager().ensure_task(operation_id)
    target_dir: Path | None = None
    try:
        source = service.repository.create_source(
            course.id,
            kind=kind,
            display_name=display_name,
            manifest=preflight,
            content_sha256="0" * 64,
            supersedes_source_id=supersedes_source_id,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
        )
    except Exception:
        TaskIDManager.get_instance().update_task_status(
            operation_id, "error", error="Course source record could not be created"
        )
        get_task_stream_manager().emit_failed(
            operation_id, "Course source record could not be created"
        )
        raise
    kb_name = source_kb_name(course.id, source.id)

    manager = KnowledgeBaseManager(base_dir=str(base_dir))
    initializer = KnowledgeBaseInitializer(
        kb_name=kb_name,
        base_dir=str(base_dir),
        rag_provider=provider,
    )
    had_ready_index = has_ready_provider_index(initializer.kb_dir, provider)

    try:
        if kb_name not in manager.list_knowledge_bases():
            initializer.create_directory_structure()
        else:
            manager.config = manager._load_config()
            entry = manager.config.get("knowledge_bases", {}).get(kb_name, {})
            bound_provider = _validate_registered_provider(
                entry.get("rag_provider") or DEFAULT_PROVIDER
            )
            if bound_provider != provider:
                raise HTTPException(
                    status_code=409,
                    detail="Course Knowledge is already bound to a different provider",
                )

        target_dir = initializer.raw_dir / source.id
        target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        target_dir.chmod(0o700)
        _, uploaded_paths = _save_uploaded_files(
            files,
            target_dir,
            allowed_extensions=allowed_extensions,
            rel_paths=rel_paths,
        )
        manifest, fingerprint = _manifest(initializer.raw_dir, uploaded_paths)
        source = service.repository.update_processing_source_manifest(
            course.id,
            source.id,
            operation_id=operation_id,
            expected_revision=source.revision,
            manifest=manifest,
            content_sha256=fingerprint,
        )
        restrict_private_tree_permissions(initializer.kb_dir)
    except Exception:
        if target_dir is not None:
            try:
                target_dir.resolve().relative_to(initializer.raw_dir.resolve())
                shutil.rmtree(target_dir, ignore_errors=True)
            except ValueError:
                logger.error("Refused to clean Course staging path outside its Knowledge shard")
        try:
            service.repository.transition_source(
                course.id,
                source.id,
                operation_id=operation_id,
                expected_source_revision=source.revision,
                expected_course_revision=course.revision,
                expected_write_epoch=course.write_epoch,
                state="failed",
            )
        except CourseConflictError:
            pass
        TaskIDManager.get_instance().update_task_status(
            operation_id, "error", error="Course source staging failed"
        )
        get_task_stream_manager().emit_failed(operation_id, "Course source staging failed")
        raise

    task = {
        "owner_user_id": service.owner_user_id,
        "course_id": course.id,
        "course_revision": course.revision,
        "course_write_epoch": course.write_epoch,
        "source_id": source.id,
        "source_revision": source.revision,
        "operation_id": operation_id,
        "kb_name": kb_name,
        "base_dir": str(base_dir),
        "uploaded_paths": uploaded_paths,
        "source_content_sha256": source.content_sha256,
        "rag_provider": provider,
        "initialize": not had_ready_index,
        "admitted_input_bytes": storage_admission.input_bytes,
        "tree_bytes_before": storage_admission.tree_bytes_before,
        "reserved_growth_bytes": storage_admission.reserved_growth_bytes,
        "source_admission_id": source_admission_id,
    }
    return source, task


def _current_personal_user(owner_user_id: str) -> CurrentUser | None:
    if owner_user_id == LOCAL_ADMIN_ID:
        return CurrentUser(
            id=LOCAL_ADMIN_ID,
            username=LOCAL_ADMIN_USERNAME,
            role="admin",
            scope=personal_scope_for_user(LOCAL_ADMIN_ID),
        )
    found = get_user_by_id(owner_user_id)
    if found is None and owner_user_id == "env-admin":
        settings = load_auth_settings()
        username = str(settings.get("username") or "")
        password_hash = str(settings.get("password_hash") or "")
        if username and password_hash:
            return CurrentUser(
                id=owner_user_id,
                username=username,
                role="admin",
                scope=personal_scope_for_user(owner_user_id),
            )
    if found is None:
        return None
    username, record = found
    if bool(record.get("disabled", False)):
        return None
    role = str(record.get("role") or "user")
    if role not in {"admin", "user"}:
        role = "user"
    return CurrentUser(
        id=owner_user_id,
        username=username,
        role=role,  # type: ignore[arg-type]
        scope=personal_scope_for_user(owner_user_id),
    )


def _course_source_upload_authorized(user: CurrentUser) -> bool:
    """Re-read the live grant; a queued task never carries upload authority."""
    return user.role == "admin" or (
        load_grant(user.id).get("course_source_uploads") is True
    )


def _fail_source_row(task: dict[str, Any]) -> None:
    """Best-effort terminal cleanup for the exact owned source operation."""
    required = {
        "owner_user_id",
        "course_id",
        "source_id",
        "source_revision",
        "operation_id",
    }
    if not required.issubset(task):
        return
    try:
        owner_user_id = str(task["owner_user_id"])
        repo = CourseRepository(
            get_personal_path_service(owner_user_id).get_courses_db(), owner_user_id
        )
        repo.fail_source_operation(
            str(task["course_id"]),
            str(task["source_id"]),
            operation_id=str(task["operation_id"]),
            expected_source_revision=int(task["source_revision"]),
        )
    except Exception:
        # Task/SSE status still becomes terminal even when the exact row has
        # already changed or local storage itself is unavailable.
        logger.exception("Could not terminalize failed Course source operation")


async def _owned_to_thread(function: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Let bounded filesystem work finish before propagating cancellation."""
    worker = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError as cancelled:
        try:
            await worker
        except Exception:
            logger.exception("Course source worker failed while cancellation was draining")
        raise cancelled


async def cancel_source_operation(task: dict[str, Any], message: str) -> None:
    """Clean and terminalize one exact staged Course source operation."""
    await _owned_to_thread(_remove_owned_kb_shard, task)
    await _owned_to_thread(_fail_source_row, task)
    operation_id = str(task.get("operation_id") or "")
    if not operation_id:
        return
    TaskIDManager.get_instance().update_task_status(
        operation_id,
        "cancelled",
        error=message,
    )
    get_task_stream_manager().emit_failed(operation_id, message)


async def run_source_operation(task: dict[str, Any]) -> None:
    """Run the existing provider task, then fence its Course commit."""
    operation_id = str(task["operation_id"])
    stream = get_task_stream_manager()
    user = _current_personal_user(str(task["owner_user_id"]))
    if user is None:
        await cancel_source_operation(task, "Course source owner is no longer active")
        return

    token = set_current_user(user)
    try:
        from deeptutor.api.routers.knowledge import (
            run_initialization_task,
            run_upload_processing_task,
        )
        from deeptutor.courses.deterministic_provider import (
            build_index as build_deterministic_index,
        )
        from deeptutor.courses.deterministic_provider import (
            delay_ingestion_for_runtime_proof,
        )
        from deeptutor.courses.deterministic_provider import enabled as deterministic_enabled
        from deeptutor.knowledge.initializer import KnowledgeBaseInitializer

        source_content_sha256 = task.get("source_content_sha256")
        if not source_content_sha256 and {
            "course_id",
            "source_id",
        }.issubset(task):
            source_repository = CourseRepository(
                get_personal_path_service(str(task["owner_user_id"])).get_courses_db(),
                str(task["owner_user_id"]),
            )
            source_content_sha256 = source_repository.get_source(
                str(task["course_id"]), str(task["source_id"])
            ).content_sha256

        # Re-read account role and the explicit upload grant immediately before
        # provider work.  A grant captured by the request is never authority for
        # a queued task.
        provider_user = _current_personal_user(str(task["owner_user_id"]))
        if provider_user is None or not _course_source_upload_authorized(provider_user):
            await cancel_source_operation(task, "Course material upload access changed")
            return

        provider_token = set_current_user(provider_user)
        try:
            if deterministic_enabled():
                await delay_ingestion_for_runtime_proof()
                provider_succeeded = await _owned_to_thread(
                    build_deterministic_index,
                    Path(str(task["base_dir"])) / str(task["kb_name"]),
                    [str(item) for item in task["uploaded_paths"]],
                    source_content_sha256=str(source_content_sha256),
                )
            elif bool(task["initialize"]):
                initializer = KnowledgeBaseInitializer(
                    kb_name=str(task["kb_name"]),
                    base_dir=str(task["base_dir"]),
                    rag_provider=str(task["rag_provider"]),
                )
                provider_succeeded = await run_initialization_task(
                    initializer, operation_id, finalize_task=False
                )
            else:
                provider_succeeded = await run_upload_processing_task(
                    kb_name=str(task["kb_name"]),
                    base_dir=str(task["base_dir"]),
                    uploaded_file_paths=[str(item) for item in task["uploaded_paths"]],
                    task_id=operation_id,
                    rag_provider=str(task["rag_provider"]),
                    finalize_task=False,
                )
        finally:
            reset_current_user(provider_token)

        metadata = TaskIDManager.get_instance().get_task_metadata(operation_id) or {}
        if provider_succeeded is None:
            # Compatibility for deterministic test fakes and third-party
            # wrappers that predate the explicit provider outcome.
            provider_succeeded = metadata.get("status") == "completed"

        # Course Practice generation reads a small deterministic, exact-text
        # shard in addition to the provider-specific RAG index. Keep that
        # derived artifact in sync for both first-time initialization and later
        # uploads; otherwise a source can be marked ready while grounded
        # Practice and Flashcards cannot resolve its text.
        if provider_succeeded and not deterministic_enabled():
            await _owned_to_thread(
                build_deterministic_index,
                Path(str(task["base_dir"])) / str(task["kb_name"]),
                [str(item) for item in task["uploaded_paths"]],
                source_content_sha256=str(source_content_sha256),
            )

        if provider_succeeded:
            # Provider-created indexes are admitted against the full private
            # tree and this exact shard before any database state can grant
            # retrieval authority.
            await _owned_to_thread(_seal_and_verify_source_storage, task)
        else:
            await _owned_to_thread(_remove_owned_kb_shard, task)

        # Re-read account state, role, and grant immediately before the Course
        # commit.  Revoked work is cleaned and never becomes learner-readable.
        refreshed = _current_personal_user(str(task["owner_user_id"]))
        if refreshed is None or not _course_source_upload_authorized(refreshed):
            await cancel_source_operation(task, "Course material upload access changed")
            return
        final_state = "ready" if provider_succeeded else "failed"
        repo = CourseRepository(
            get_personal_path_service(refreshed.id).get_courses_db(), refreshed.id
        )
        repo.transition_source(
            str(task["course_id"]),
            str(task["source_id"]),
            operation_id=operation_id,
            expected_source_revision=int(task["source_revision"]),
            expected_course_revision=int(task["course_revision"]),
            expected_write_epoch=int(task["course_write_epoch"]),
            state=final_state,
        )
        if provider_succeeded:
            TaskIDManager.get_instance().update_task_status(operation_id, "completed")
            stream.emit_complete(operation_id, "Course source is ready")
        else:
            TaskIDManager.get_instance().update_task_status(
                operation_id, "error", error="Course source processing failed"
            )
            stream.emit_failed(operation_id, "Course source processing failed")
    except asyncio.CancelledError:
        await cancel_source_operation(task, "Course source processing was cancelled")
        raise
    except CourseConflictError:
        # Archive/revision/revocation fences intentionally win over late work.
        await cancel_source_operation(
            task,
            "Course source changed before processing completed",
        )
        return
    except Exception:
        await _owned_to_thread(_remove_owned_kb_shard, task)
        await _owned_to_thread(_fail_source_row, task)
        TaskIDManager.get_instance().update_task_status(
            operation_id, "error", error="Course source processing failed"
        )
        stream.emit_failed(operation_id, "Course source processing failed")
        raise
    finally:
        reset_current_user(token)
