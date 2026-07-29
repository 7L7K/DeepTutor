"""Authenticated private-course API."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from deeptutor.courses.practice_models import ExactAnswerContract
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


class _PracticeRequest(BaseModel):
    """Reject UI-only and authority-bearing fields at the API boundary."""

    model_config = ConfigDict(extra="forbid")


class CreatePracticeSetRequest(_PracticeRequest):
    title: str = Field(min_length=1, max_length=160)
    expected_course_write_epoch: int = Field(ge=1)


class CreatePracticeRevisionRequest(_PracticeRequest):
    expected_course_write_epoch: int = Field(ge=1)


class PracticeSetMutationRequest(_PracticeRequest):
    expected_revision: int = Field(ge=1)
    expected_course_write_epoch: int = Field(ge=1)


class ReadyPracticeRevisionRequest(_PracticeRequest):
    expected_course_write_epoch: int = Field(ge=1)


class ExactAnswerResponse(_PracticeRequest):
    answer: str = Field(max_length=4_000)


class AddPracticeQuestionRequest(_PracticeRequest):
    question_type: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=12_000)
    answer_contract: ExactAnswerContract
    explanation: str = Field(default="", max_length=12_000)
    objective_ids: list[str] = Field(default_factory=list, max_length=128)
    expected_course_write_epoch: int = Field(ge=1)


class StartPracticeAttemptRequest(_PracticeRequest):
    practice_set_revision_id: str = Field(min_length=1, max_length=80)
    expected_course_write_epoch: int = Field(ge=1)
    expected_practice_set_write_epoch: int = Field(ge=1)


class AutosavePracticeAnswerRequest(_PracticeRequest):
    attempt_item_id: str = Field(min_length=1, max_length=80)
    response: ExactAnswerResponse
    expected_answer_revision: int = Field(ge=1)
    expected_course_write_epoch: int = Field(ge=1)
    expected_practice_set_write_epoch: int = Field(ge=1)


class AttemptMutationRequest(_PracticeRequest):
    expected_course_write_epoch: int = Field(ge=1)
    expected_practice_set_write_epoch: int = Field(ge=1)


class CreateGeneratedPracticeRequest(_PracticeRequest):
    """The deliberately narrow public input for grounded Practice generation.

    The server resolves every source receipt, provider choice, retrieval context,
    and provenance record.  This body is intentionally not a prompt or provider
    configuration surface.
    """

    title: str = Field(min_length=1, max_length=160)
    source_ids: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        min_length=1, max_length=32
    )
    objective_ids: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(
        default_factory=list, max_length=128
    )
    expected_course_write_epoch: int = Field(ge=1)
    item_limit: int = Field(default=5, ge=1, le=12)
    context_char_limit: int = Field(default=12_000, ge=1, le=48_000)


class GeneratePracticeRevisionRequest(_PracticeRequest):
    """Bounded successor-generation request for an existing generated set."""

    source_ids: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        min_length=1, max_length=32
    )
    objective_ids: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(
        default_factory=list, max_length=128
    )
    expected_course_write_epoch: int = Field(ge=1)
    expected_practice_set_write_epoch: int = Field(ge=1)
    item_limit: int = Field(default=5, ge=1, le=12)
    context_char_limit: int = Field(default=12_000, ge=1, le=48_000)


class CreateFlashcardDeckRequest(_PracticeRequest):
    title: str = Field(min_length=1, max_length=160)
    expected_course_write_epoch: int = Field(ge=1)


class FlashcardDeckMutationRequest(_PracticeRequest):
    expected_revision: int = Field(ge=1)
    expected_course_write_epoch: int = Field(ge=1)


class RenameFlashcardDeckRequest(FlashcardDeckMutationRequest):
    title: str = Field(min_length=1, max_length=160)


class CreateFlashcardCardRequest(_PracticeRequest):
    prompt: str = Field(min_length=1, max_length=12_000)
    answer: str = Field(min_length=1, max_length=12_000)
    objective_ids: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(
        default_factory=list, max_length=64
    )
    expected_deck_revision: int = Field(ge=1)
    expected_course_write_epoch: int = Field(ge=1)


class UpdateFlashcardCardRequest(CreateFlashcardCardRequest):
    expected_card_revision: int = Field(ge=1)


class ArchiveFlashcardCardRequest(_PracticeRequest):
    expected_card_revision: int = Field(ge=1)
    expected_deck_revision: int = Field(ge=1)
    expected_course_write_epoch: int = Field(ge=1)


class RecordFlashcardReviewRequest(_PracticeRequest):
    card_id: str = Field(min_length=1, max_length=80)
    rating: str = Field(pattern="^(again|hard|good|easy)$")
    idempotency_key: str = Field(min_length=1, max_length=160)
    expected_deck_revision: int = Field(ge=1)
    expected_card_revision: int = Field(ge=1)
    expected_course_write_epoch: int = Field(ge=1)


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


def _practice_call(operation):
    """Translate Course-owned Practice failures without leaking foreign IDs."""

    try:
        return operation()
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Practice resource not found") from exc
    except (CourseConflictError, LearningConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        # Persistence fences are part of the Course ownership contract.  Never
        # surface SQLite trigger text (which can reveal internal table shape).
        raise HTTPException(status_code=409, detail="Practice resource conflict") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _practice_services():
    from deeptutor.courses.attempt_repository import CourseAssessmentRepository
    from deeptutor.courses.attempt_service import CourseAssessmentService
    from deeptutor.courses.practice_repository import CoursePracticeRepository
    from deeptutor.courses.practice_service import CoursePracticeService

    course_service = _service()
    repository = course_service.repository
    return (
        CoursePracticeService(CoursePracticeRepository(repository)),
        CourseAssessmentService(CourseAssessmentRepository(repository)),
    )


def _flashcard_service():
    from deeptutor.courses.flashcard_repository import CourseFlashcardRepository
    from deeptutor.courses.flashcard_service import CourseFlashcardService

    return CourseFlashcardService(CourseFlashcardRepository(_service().repository))


def _practice_grading_service():
    from deeptutor.courses.grading_repository import CourseGradingRepository
    from deeptutor.courses.grading_service import CourseGradingService
    from deeptutor.courses.mastery_adapter import CourseMasteryAdapter
    from deeptutor.learning.storage import LearningStore
    from deeptutor.multi_user.paths import get_personal_path_service

    course_service = _service()
    paths = get_personal_path_service(course_service.owner_user_id)
    adapter = CourseMasteryAdapter(LearningStore(root=paths.get_workspace_dir() / "learning"))
    return CourseGradingService(CourseGradingRepository(course_service.repository), adapter)


def _practice_generation_service():
    """Build the generation seam from the authenticated private Course root."""

    from deeptutor.courses.generation_service import build_practice_generation_service

    return build_practice_generation_service(_service())


def _run_practice_generation(
    owner_user_id: str, course_id: str, operation_id: str
) -> None:
    """Run exactly one persisted operation outside the request lifecycle.

    Background execution rebuilds the private repository from the immutable
    operation owner instead of relying on a request ``ContextVar`` that could
    disappear or fall back to the local-admin workspace.  The generation service
    still revalidates account authority before provider work and final commit.
    """

    from deeptutor.courses.generation_service import (
        unregister_live_practice_generation,
    )
    from deeptutor.courses.repository import CourseRepository
    from deeptutor.courses.service import CourseService
    from deeptutor.multi_user.paths import get_personal_path_service

    try:
        paths = get_personal_path_service(owner_user_id)
        service = CourseService(CourseRepository(paths.get_courses_db(), owner_user_id))
        _practice_generation_service_for(service).run_operation(course_id, operation_id)
    finally:
        # ``run_operation`` normally removes the marker itself. This boundary
        # also covers failures while rebuilding the owner path, repository, or
        # service before ``run_operation`` can begin.
        unregister_live_practice_generation(owner_user_id, course_id, operation_id)


def _practice_generation_service_for(course_service):
    """Indirection keeps the background path injectable in deterministic tests."""

    from deeptutor.courses.generation_service import build_practice_generation_service

    return build_practice_generation_service(course_service)


def _practice_question_payload(question, *, include_answer_contract: bool) -> dict:
    payload = question.model_dump(mode="json")
    if not include_answer_contract:
        payload.pop("answer_contract", None)
        # Explanations are answer-adjacent provider/author content. They are
        # revealed with the frozen answer contract only after durable grading.
        payload.pop("explanation", None)
    return payload


@router.post("/{course_id}/practice")
async def create_practice_set(course_id: str, body: CreatePracticeSetRequest):
    async with course_operation_lock(course_id):
        practice, _attempts = _practice_services()
        return _practice_call(
            lambda: practice.create_practice_set(
                course_id,
                title=body.title,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.get("/{course_id}/practice")
async def list_practice_sets(
    course_id: str, include_archived: bool = Query(default=True)
):
    practice, _attempts = _practice_services()
    return {
        "practice_sets": [
            item.model_dump(mode="json")
            for item in _practice_call(
                lambda: practice.list_practice_sets(
                    course_id, include_archived=include_archived
                )
            )
        ]
    }


@router.post("/{course_id}/practice-generation", status_code=202)
async def create_generated_practice(
    course_id: str,
    body: CreateGeneratedPracticeRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=8, max_length=160
    ),
):
    """Queue one server-owned grounded Practice operation.

    The response is the durable queued record.  It is intentionally not a
    generated question preview, a prompt surface, or proof that generation has
    succeeded; callers must fetch the operation for its terminal state.
    """

    async with course_operation_lock(course_id):
        generation = _practice_generation_service()
        request = _practice_call(
            lambda: generation.create_generated_practice(
                course_id,
                title=body.title,
                source_ids=body.source_ids,
                objective_ids=body.objective_ids,
                idempotency_key=idempotency_key,
                expected_course_write_epoch=body.expected_course_write_epoch,
                item_limit=body.item_limit,
                context_char_limit=body.context_char_limit,
            )
        )
    from deeptutor.courses.generation_service import register_live_practice_generation

    register_live_practice_generation(
        request.operation.owner_user_id, course_id, request.operation.id
    )
    background_tasks.add_task(
        _run_practice_generation,
        request.operation.owner_user_id,
        course_id,
        request.operation.id,
    )
    return request.model_dump(mode="json")


@router.get("/{course_id}/practice-generation")
async def list_practice_generation_operations(course_id: str):
    generation = _practice_generation_service()
    return {
        "operations": [
            item.model_dump(mode="json")
            for item in _practice_call(lambda: generation.list_operations(course_id))
        ]
    }


@router.get("/{course_id}/practice-generation/{operation_id}")
async def get_practice_generation_operation(course_id: str, operation_id: str):
    generation = _practice_generation_service()
    return _practice_call(
        lambda: generation.get_operation(course_id, operation_id)
    ).model_dump(mode="json")


@router.post("/{course_id}/practice/{practice_set_id}/generation", status_code=202)
async def request_practice_generation_successor(
    course_id: str,
    practice_set_id: str,
    body: GeneratePracticeRevisionRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=8, max_length=160
    ),
):
    """Queue a new immutable generated revision for an owned generated set."""

    async with course_operation_lock(course_id):
        generation = _practice_generation_service()
        request = _practice_call(
            lambda: generation.request_generation(
                course_id,
                practice_set_id,
                source_ids=body.source_ids,
                objective_ids=body.objective_ids,
                idempotency_key=idempotency_key,
                expected_course_write_epoch=body.expected_course_write_epoch,
                expected_practice_set_write_epoch=body.expected_practice_set_write_epoch,
                item_limit=body.item_limit,
                context_char_limit=body.context_char_limit,
            )
        )
    from deeptutor.courses.generation_service import register_live_practice_generation

    register_live_practice_generation(
        request.operation.owner_user_id, course_id, request.operation.id
    )
    background_tasks.add_task(
        _run_practice_generation,
        request.operation.owner_user_id,
        course_id,
        request.operation.id,
    )
    return request.model_dump(mode="json")


@router.get("/{course_id}/practice/{practice_set_id}")
async def get_practice_set(course_id: str, practice_set_id: str):
    practice, _attempts = _practice_services()
    return _practice_call(
        lambda: practice.get_practice_set(course_id, practice_set_id)
    ).model_dump(mode="json")


@router.post("/{course_id}/practice/{practice_set_id}/archive")
async def archive_practice_set(
    course_id: str, practice_set_id: str, body: PracticeSetMutationRequest
):
    async with course_operation_lock(course_id):
        practice, _attempts = _practice_services()
        return _practice_call(
            lambda: practice.archive_practice_set(
                course_id,
                practice_set_id,
                expected_revision=body.expected_revision,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.post("/{course_id}/practice/{practice_set_id}/restore")
async def restore_practice_set(
    course_id: str, practice_set_id: str, body: PracticeSetMutationRequest
):
    async with course_operation_lock(course_id):
        practice, _attempts = _practice_services()
        return _practice_call(
            lambda: practice.restore_practice_set(
                course_id,
                practice_set_id,
                expected_revision=body.expected_revision,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.post("/{course_id}/practice/{practice_set_id}/revisions")
async def create_practice_revision(
    course_id: str, practice_set_id: str, body: CreatePracticeRevisionRequest
):
    async with course_operation_lock(course_id):
        practice, _attempts = _practice_services()
        return _practice_call(
            lambda: practice.create_draft_revision(
                course_id,
                practice_set_id,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.post("/{course_id}/practice/{practice_set_id}/revisions/successor")
async def create_practice_successor_revision(
    course_id: str, practice_set_id: str, body: CreatePracticeRevisionRequest
):
    async with course_operation_lock(course_id):
        practice, _attempts = _practice_services()
        return _practice_call(
            lambda: practice.create_successor_revision(
                course_id,
                practice_set_id,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.get("/{course_id}/practice/{practice_set_id}/revisions/{revision_id}")
async def get_practice_revision(
    course_id: str, practice_set_id: str, revision_id: str
):
    practice, _attempts = _practice_services()
    return _practice_call(
        lambda: practice.get_revision(course_id, practice_set_id, revision_id)
    ).model_dump(mode="json")


@router.post(
    "/{course_id}/practice/{practice_set_id}/revisions/{revision_id}/questions"
)
async def add_practice_question(
    course_id: str,
    practice_set_id: str,
    revision_id: str,
    body: AddPracticeQuestionRequest,
):
    async with course_operation_lock(course_id):
        practice, _attempts = _practice_services()
        return _practice_call(
            lambda: practice.add_question(
                course_id,
                practice_set_id,
                revision_id,
                question_type=body.question_type,
                prompt=body.prompt,
                answer_contract=body.answer_contract,
                explanation=body.explanation,
                objective_ids=body.objective_ids,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.get(
    "/{course_id}/practice/{practice_set_id}/revisions/{revision_id}/questions"
)
async def list_practice_questions(
    course_id: str, practice_set_id: str, revision_id: str
):
    practice, _attempts = _practice_services()
    revision = _practice_call(
        lambda: practice.get_revision(course_id, practice_set_id, revision_id)
    )
    return {
        "questions": [
            _practice_question_payload(
                item, include_answer_contract=revision.state == "draft"
            )
            for item in _practice_call(
                lambda: practice.list_questions(course_id, practice_set_id, revision_id)
            )
        ]
    }


@router.post("/{course_id}/practice/{practice_set_id}/revisions/{revision_id}/ready")
async def ready_practice_revision(
    course_id: str,
    practice_set_id: str,
    revision_id: str,
    body: ReadyPracticeRevisionRequest,
):
    async with course_operation_lock(course_id):
        practice, _attempts = _practice_services()
        return _practice_call(
            lambda: practice.ready_revision(
                course_id,
                practice_set_id,
                revision_id,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.post("/{course_id}/practice/{practice_set_id}/attempts")
async def start_or_resume_practice_attempt(
    course_id: str, practice_set_id: str, body: StartPracticeAttemptRequest
):
    async with course_operation_lock(course_id):
        _practice, attempts = _practice_services()
        return _practice_call(
            lambda: attempts.start_or_resume_attempt(
                course_id,
                practice_set_id,
                body.practice_set_revision_id,
                expected_course_write_epoch=body.expected_course_write_epoch,
                expected_practice_set_write_epoch=body.expected_practice_set_write_epoch,
            )
        ).model_dump(mode="json")


@router.get("/{course_id}/practice/{practice_set_id}/attempts")
async def list_practice_attempts(
    course_id: str,
    practice_set_id: str,
    include_archived: bool = Query(default=True),
):
    _practice, attempts = _practice_services()
    return {
        "attempts": [
            item.model_dump(mode="json")
            for item in _practice_call(
                lambda: attempts.list_attempts(
                    course_id, practice_set_id, include_archived=include_archived
                )
            )
        ]
    }


@router.get("/{course_id}/practice/{practice_set_id}/attempts/{attempt_id}")
async def get_practice_attempt(
    course_id: str, practice_set_id: str, attempt_id: str
):
    _practice, attempts = _practice_services()
    return _practice_call(
        lambda: attempts.get_attempt(course_id, practice_set_id, attempt_id)
    ).model_dump(mode="json")


@router.patch("/{course_id}/practice/{practice_set_id}/attempts/{attempt_id}")
async def autosave_practice_answer(
    course_id: str,
    practice_set_id: str,
    attempt_id: str,
    body: AutosavePracticeAnswerRequest,
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=8, max_length=160
    ),
):
    async with course_operation_lock(course_id):
        _practice, attempts = _practice_services()
        return _practice_call(
            lambda: attempts.autosave_answer(
                course_id,
                practice_set_id,
                attempt_id,
                body.attempt_item_id,
                response=body.response.model_dump(mode="json"),
                expected_answer_revision=body.expected_answer_revision,
                idempotency_token=idempotency_key,
                expected_course_write_epoch=body.expected_course_write_epoch,
                expected_practice_set_write_epoch=body.expected_practice_set_write_epoch,
            )
        ).model_dump(mode="json")


@router.post("/{course_id}/practice/{practice_set_id}/attempts/{attempt_id}/submit")
async def submit_practice_attempt(
    course_id: str,
    practice_set_id: str,
    attempt_id: str,
    body: AttemptMutationRequest,
):
    async with course_operation_lock(course_id):
        _practice, attempts = _practice_services()
        return _practice_call(
            lambda: attempts.submit_attempt(
                course_id,
                practice_set_id,
                attempt_id,
                expected_course_write_epoch=body.expected_course_write_epoch,
                expected_practice_set_write_epoch=body.expected_practice_set_write_epoch,
            )
        ).model_dump(mode="json")


@router.post("/{course_id}/practice/{practice_set_id}/attempts/{attempt_id}/abandon")
async def abandon_practice_attempt(
    course_id: str,
    practice_set_id: str,
    attempt_id: str,
    body: AttemptMutationRequest,
):
    async with course_operation_lock(course_id):
        _practice, attempts = _practice_services()
        return _practice_call(
            lambda: attempts.abandon_attempt(
                course_id,
                practice_set_id,
                attempt_id,
                expected_course_write_epoch=body.expected_course_write_epoch,
                expected_practice_set_write_epoch=body.expected_practice_set_write_epoch,
            )
        ).model_dump(mode="json")


@router.post("/{course_id}/practice/{practice_set_id}/attempts/{attempt_id}/grade")
async def grade_practice_attempt(
    course_id: str,
    practice_set_id: str,
    attempt_id: str,
    body: AttemptMutationRequest,
):
    async with course_operation_lock(course_id):
        grading = _practice_grading_service()
        return _practice_call(
            lambda: grading.grade_attempt(
                course_id,
                practice_set_id,
                attempt_id,
                expected_course_write_epoch=body.expected_course_write_epoch,
                expected_practice_set_write_epoch=body.expected_practice_set_write_epoch,
            )
        ).model_dump(mode="json")


@router.get("/{course_id}/practice/{practice_set_id}/attempts/{attempt_id}/results")
async def get_practice_attempt_results(
    course_id: str, practice_set_id: str, attempt_id: str
):
    practice, attempts = _practice_services()
    view = _practice_call(
        lambda: attempts.get_attempt(course_id, practice_set_id, attempt_id)
    )
    if view.attempt.state != "graded":
        raise HTTPException(status_code=409, detail="Quiz attempt has not been graded")
    questions = _practice_call(
        lambda: practice.list_questions(
            course_id,
            practice_set_id,
            view.attempt.practice_set_revision_id,
        )
    )
    return {
        **view.model_dump(mode="json"),
        "questions": [
            _practice_question_payload(item, include_answer_contract=True)
            for item in questions
        ],
    }


@router.post("/{course_id}/flashcards")
async def create_flashcard_deck(course_id: str, body: CreateFlashcardDeckRequest):
    async with course_operation_lock(course_id):
        return _practice_call(
            lambda: _flashcard_service().create_deck(
                course_id, title=body.title,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.get("/{course_id}/flashcards")
async def list_flashcard_decks(course_id: str, include_archived: bool = Query(default=True)):
    return {"flashcard_decks": [
        item.model_dump(mode="json")
        for item in _practice_call(
            lambda: _flashcard_service().list_decks(course_id, include_archived=include_archived)
        )
    ]}


@router.get("/{course_id}/flashcards/{deck_id}")
async def get_flashcard_deck(course_id: str, deck_id: str):
    return _practice_call(lambda: _flashcard_service().get_deck(course_id, deck_id)).model_dump(mode="json")


@router.patch("/{course_id}/flashcards/{deck_id}")
async def rename_flashcard_deck(course_id: str, deck_id: str, body: RenameFlashcardDeckRequest):
    async with course_operation_lock(course_id):
        return _practice_call(
            lambda: _flashcard_service().rename_deck(
                course_id, deck_id, title=body.title, expected_revision=body.expected_revision,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.post("/{course_id}/flashcards/{deck_id}/ready")
async def ready_flashcard_deck(course_id: str, deck_id: str, body: FlashcardDeckMutationRequest):
    async with course_operation_lock(course_id):
        return _practice_call(
            lambda: _flashcard_service().ready_deck(
                course_id, deck_id, expected_revision=body.expected_revision,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.post("/{course_id}/flashcards/{deck_id}/archive")
async def archive_flashcard_deck(course_id: str, deck_id: str, body: FlashcardDeckMutationRequest):
    async with course_operation_lock(course_id):
        return _practice_call(
            lambda: _flashcard_service().archive_deck(
                course_id, deck_id, expected_revision=body.expected_revision,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.post("/{course_id}/flashcards/{deck_id}/restore")
async def restore_flashcard_deck(course_id: str, deck_id: str, body: FlashcardDeckMutationRequest):
    async with course_operation_lock(course_id):
        return _practice_call(
            lambda: _flashcard_service().restore_deck(
                course_id, deck_id, expected_revision=body.expected_revision,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.post("/{course_id}/flashcards/{deck_id}/cards")
async def add_flashcard(course_id: str, deck_id: str, body: CreateFlashcardCardRequest):
    async with course_operation_lock(course_id):
        return _practice_call(
            lambda: _flashcard_service().add_card(
                course_id, deck_id, prompt=body.prompt, answer=body.answer,
                objective_ids=body.objective_ids, expected_deck_revision=body.expected_deck_revision,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.patch("/{course_id}/flashcards/{deck_id}/cards/{card_id}")
async def update_flashcard(course_id: str, deck_id: str, card_id: str, body: UpdateFlashcardCardRequest):
    async with course_operation_lock(course_id):
        return _practice_call(
            lambda: _flashcard_service().update_card(
                course_id, deck_id, card_id, prompt=body.prompt, answer=body.answer,
                objective_ids=body.objective_ids, expected_card_revision=body.expected_card_revision,
                expected_deck_revision=body.expected_deck_revision,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.post("/{course_id}/flashcards/{deck_id}/cards/{card_id}/archive")
async def archive_flashcard(course_id: str, deck_id: str, card_id: str, body: ArchiveFlashcardCardRequest):
    async with course_operation_lock(course_id):
        return _practice_call(
            lambda: _flashcard_service().archive_card(
                course_id, deck_id, card_id, expected_card_revision=body.expected_card_revision,
                expected_deck_revision=body.expected_deck_revision,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.get("/{course_id}/flashcards/{deck_id}/reviews")
async def due_flashcards(course_id: str, deck_id: str):
    return _practice_call(
        lambda: _flashcard_service().due_cards(course_id, deck_id)
    ).model_dump(mode="json")


@router.post("/{course_id}/flashcards/{deck_id}/reviews")
async def record_flashcard_review(course_id: str, deck_id: str, body: RecordFlashcardReviewRequest):
    async with course_operation_lock(course_id):
        review, schedule, summary = _practice_call(
            lambda: _flashcard_service().record_review(
                course_id, deck_id, card_id=body.card_id, rating=body.rating,
                idempotency_key=body.idempotency_key,
                expected_deck_revision=body.expected_deck_revision,
                expected_card_revision=body.expected_card_revision,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        )
    return {
        "review": review.model_dump(mode="json"),
        "schedule": schedule.model_dump(mode="json"),
        "review_summary": summary.model_dump(mode="json"),
    }


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
