"""Authenticated private-course API."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from deeptutor.courses.repository import CourseConflictError, CourseNotFoundError
from deeptutor.courses.service import (
    CourseUnavailableError,
    course_operation_lock,
    get_current_course_service,
)
from deeptutor.learning.storage import LearningConflictError, LearningDataError

router = APIRouter()


class CreateCourseRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class UpdateCourseRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(ge=1)


class RevisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class InitCourseLearningRequest(BaseModel):
    modules: list[dict]
    session_id: str | None = None


class ResetCourseLearningRequest(BaseModel):
    session_id: str | None = None


def _service():
    try:
        return get_current_course_service()
    except CourseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _call(operation):
    try:
        return operation()
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course resource not found") from exc
    except CourseConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("")
async def create_course(body: CreateCourseRequest):
    return _call(lambda: _service().create(body.title)).model_dump()


@router.get("")
async def list_courses(include_archived: bool = Query(default=True)):
    return {
        "courses": [
            course.model_dump()
            for course in _call(lambda: _service().list(include_archived=include_archived))
        ]
    }


@router.get("/{course_id}")
async def get_course(course_id: str):
    return _call(lambda: _service().get(course_id)).model_dump()


@router.patch("/{course_id}")
async def update_course(course_id: str, body: UpdateCourseRequest):
    async with course_operation_lock(course_id):
        return _call(
            lambda: _service().rename(course_id, body.title, body.expected_revision)
        ).model_dump()


@router.post("/{course_id}/archive")
async def archive_course(course_id: str, body: RevisionRequest):
    try:
        course = await _service().archive(course_id, body.expected_revision)
        return course.model_dump()
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course resource not found") from exc
    except CourseConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{course_id}/restore")
async def restore_course(course_id: str, body: RevisionRequest):
    async with course_operation_lock(course_id):
        return _call(lambda: _service().restore(course_id, body.expected_revision)).model_dump()


def _course_learning_store(course_id: str, *, require_active: bool):
    from deeptutor.courses.service import install_personal_course_context
    from deeptutor.learning.storage import LearningStore
    from deeptutor.multi_user.paths import get_personal_path_service

    service = _service()
    course = service.get(course_id)
    if require_active and course.state != "active":
        raise CourseConflictError("Archived courses cannot change learning state")
    install_personal_course_context()
    paths = get_personal_path_service(service.owner_user_id)
    store = LearningStore(root=paths.get_workspace_dir() / "learning")
    return course, store


async def _cancel_owned_course_session(course_id: str, session_id: str | None) -> None:
    from deeptutor.services.session import (
        get_personal_sqlite_session_store,
        get_turn_runtime_manager,
    )

    store = get_personal_sqlite_session_store()
    runtime = get_turn_runtime_manager(personal=True)
    await runtime.recover_orphan_course_turns(course_id)
    if session_id:
        session = await store.get_session(session_id)
        if session is None or str(session.get("course_id") or "") != course_id:
            raise CourseNotFoundError("Course session not found")
        active = await store.get_active_turn(session_id)
        if active:
            await runtime.cancel_turn(str(active["id"]))
    if await store.has_active_course_turn(course_id):
        raise CourseConflictError(
            "Course learning cannot change while a Course turn is active"
        )


@router.get("/{course_id}/learning")
async def get_course_learning(course_id: str):
    try:
        from deeptutor.learning import policy as learning_policy

        course, store = _course_learning_store(course_id, require_active=False)
        progress = store.load(course.learning_path_id)
        return {
            "course_id": course.id,
            "learning_path_id": course.learning_path_id,
            "initialized": progress is not None and bool(progress.modules),
            "progress": progress.model_dump(mode="json") if progress else None,
            "next": learning_policy.next_objective(progress).to_dict() if progress else None,
            "map": learning_policy.map_summary(progress) if progress else [],
        }
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course resource not found") from exc
    except LearningDataError as exc:
        raise HTTPException(
            status_code=409,
            detail="Course learning state is unreadable; reinitialize it to recover",
        ) from exc


@router.post("/{course_id}/learning/init")
async def init_course_learning(course_id: str, body: InitCourseLearningRequest):
    from deeptutor.api.routers.mastery_path import (
        _parse_modules,
        _validate_runnable_modules,
    )
    from deeptutor.learning.service import LearningService
    try:
        async with course_operation_lock(course_id):
            course, store = _course_learning_store(course_id, require_active=True)
            await _cancel_owned_course_session(course.id, body.session_id)
            modules = _parse_modules(body.modules)
            _validate_runnable_modules(modules)
            service = LearningService(store)
            try:
                progress = service.get_or_create(course.learning_path_id)
            except LearningDataError:
                # Initialization is the explicit repair action. Preserve the
                # unreadable bytes for operator recovery before starting fresh.
                store.quarantine_corrupt(course.learning_path_id)
                progress = service.get_or_create(course.learning_path_id)
            service.init_modules(progress, modules)
            progress.current_module_id = modules[0].id
            progress.current_kp_index = 0
            service.save(progress)
            return {
                "status": "ok",
                "course_id": course.id,
                "learning_path_id": course.learning_path_id,
                "module_count": len(modules),
            }
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course resource not found") from exc
    except CourseConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{course_id}/learning/reset")
async def reset_course_learning(course_id: str, body: ResetCourseLearningRequest):
    from deeptutor.courses.grading_repository import CourseGradingRepository
    from deeptutor.learning.service import LearningService

    try:
        async with course_operation_lock(course_id):
            course, store = _course_learning_store(course_id, require_active=True)
            if CourseGradingRepository(_service().repository).has_course_evidence(course.id):
                raise CourseConflictError(
                    "Course learning with grading evidence cannot be reset"
                )
            await _cancel_owned_course_session(course.id, body.session_id)
            progress = store.load(course.learning_path_id)
            if progress is None:
                raise CourseNotFoundError("Course learning state not found")
            LearningService(store).reset_progress(progress)
            return {
                "status": "ok",
                "course_id": course.id,
                "learning_path_id": course.learning_path_id,
            }
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course resource not found") from exc
    except CourseConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LearningConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LearningDataError as exc:
        raise HTTPException(
            status_code=409,
            detail="Course learning state is unreadable; reinitialize it to recover",
        ) from exc


@router.get("/{course_id}/sources")
async def list_course_sources(course_id: str):
    return {
        "sources": [
            source.model_dump()
            for source in _call(lambda: _service().list_sources(course_id))
        ]
    }


@router.post("/{course_id}/sources", status_code=202)
async def create_course_source(
    course_id: str,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    kind: str = Form("document"),
    display_name: str = Form(...),
    rag_provider: str | None = Form(None),
    rel_paths: list[str] | None = Form(None),
    supersedes_source_id: str | None = Form(None),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=160),
):
    from deeptutor.courses.ingestion import prepare_source_upload, run_source_operation

    try:
        async with course_operation_lock(course_id):
            source, task = prepare_source_upload(
                course_id=course_id,
                files=files,
                kind=kind,
                display_name=display_name,
                rag_provider=rag_provider,
                rel_paths=rel_paths,
                supersedes_source_id=supersedes_source_id,
                idempotency_key=idempotency_key,
            )
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course resource not found") from exc
    except CourseConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if task is not None:
        background_tasks.add_task(run_source_operation, task)
    return source.model_dump()


@router.get("/{course_id}/sources/{source_id}")
async def get_course_source(course_id: str, source_id: str):
    return _call(lambda: _service().get_source(course_id, source_id)).model_dump()


@router.get("/{course_id}/sources/{source_id}/progress")
async def stream_course_source_progress(course_id: str, source_id: str):
    from deeptutor.api.utils.task_log_stream import get_task_stream_manager

    source = _call(lambda: _service().reconcile_source_for_progress(course_id, source_id))
    if not source.operation_id:
        raise HTTPException(status_code=404, detail="Course resource not found")
    manager = get_task_stream_manager()
    manager.ensure_task(source.operation_id)
    if source.state == "ready":
        manager.emit_complete(source.operation_id, "Course source is ready")
    elif source.state in {"failed", "archived"}:
        manager.emit_failed(source.operation_id, f"Course source is {source.state}")
    return StreamingResponse(
        manager.stream(source.operation_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{course_id}/sources/{source_id}/archive")
async def archive_course_source(course_id: str, source_id: str, body: RevisionRequest):
    try:
        async with course_operation_lock(course_id):
            source = await _service().archive_source(
                course_id, source_id, body.expected_revision
            )
            return source.model_dump()
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course resource not found") from exc
    except CourseConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
