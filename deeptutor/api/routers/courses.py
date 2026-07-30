"""Authenticated private-course API."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any, Literal

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


class CreateGeneratedFlashcardDeckRequest(_PracticeRequest):
    """No prompt/provider/KB authority reaches the generated-deck backend."""
    title: str = Field(min_length=1, max_length=160)
    source_ids: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=32
    )
    objective_ids: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(default_factory=list, max_length=64)
    focus: str = Field(default="Review the selected Course material", min_length=1, max_length=1000)
    card_type_mix: list[
        Literal["definition", "concept", "comparison", "application", "process", "recall"]
    ] = Field(default_factory=lambda: ["recall"], min_length=1, max_length=6)
    difficulty: Literal["introductory", "intermediate", "advanced", "mixed"] = "mixed"
    answer_length: Literal["short", "medium"] = "short"
    include_hints: bool = True
    origin: dict[str, Any] | None = None
    expected_course_write_epoch: int = Field(ge=1)
    item_limit: int = Field(default=8, ge=1, le=48)
    context_char_limit: int = Field(default=12_000, ge=1, le=48_000)


async def _authoritative_flashcard_generation_arguments(
    course_id: str,
    body: CreateGeneratedFlashcardDeckRequest,
    *,
    allow_system_origin: bool = True,
) -> dict[str, Any]:
    from deeptutor.courses.flashcard_generation_models import (
        FlashcardGenerationOrigin,
    )

    try:
        parsed = FlashcardGenerationOrigin.model_validate(
            body.origin or {"kind": "workspace"}
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="Flashcard generation origin is invalid"
        ) from exc

    def arguments(
        *,
        origin: FlashcardGenerationOrigin,
        source_ids: list[str],
        objective_ids: list[str],
        focus: str,
        item_limit: int,
        card_type_mix: list[str],
        difficulty: str,
        answer_length: str,
        include_hints: bool,
        context_char_limit: int,
    ) -> dict[str, Any]:
        return {
            "origin": origin.model_dump(mode="json"),
            "source_ids": source_ids,
            "objective_ids": objective_ids,
            "focus": focus,
            "item_limit": item_limit,
            "card_type_mix": card_type_mix,
            "difficulty": difficulty,
            "answer_length": answer_length,
            "include_hints": include_hints,
            "context_char_limit": context_char_limit,
        }

    if parsed.kind == "workspace":
        if not body.source_ids:
            raise HTTPException(
                status_code=422, detail="Course generation requires ready materials"
            )
        return arguments(
            origin=parsed,
            source_ids=body.source_ids,
            objective_ids=body.objective_ids,
            focus=body.focus,
            item_limit=body.item_limit,
            card_type_mix=list(body.card_type_mix),
            difficulty=body.difficulty,
            answer_length=body.answer_length,
            include_hints=body.include_hints,
            context_char_limit=body.context_char_limit,
        )
    if not allow_system_origin:
        raise HTTPException(
            status_code=422,
            detail="Successor generation requires a workspace request",
        )

    canonical: dict[str, Any] | None = None
    if (
        parsed.kind == "general_chat"
        and parsed.session_id
        and parsed.message_id is not None
        and parsed.practice_attempt_id is None
    ):
        destination = _service().get(course_id)
        if destination.state != "active" or destination.workspace_kind not in {
            "general_study",
            "academic_course",
        }:
            raise HTTPException(status_code=404, detail="Flashcard workspace not found")
        selected = await _resolve_general_chat_context(
            session_id=parsed.session_id,
            assistant_message_id=parsed.message_id,
        )
        from deeptutor.multi_user.context import get_current_user

        session_scope = (
            "admin" if get_current_user().scope.kind == "admin" else "personal"
        )
        canonical = arguments(
            origin=FlashcardGenerationOrigin(
                kind="general_chat",
                session_id=parsed.session_id,
                message_id=parsed.message_id,
                selected_message_ids=list(selected.message_ids),
                context_sha256=selected.context_sha256,
                context_summary=selected.summary,
                context_title=selected.title,
                context_topics=list(selected.topics),
                session_scope=session_scope,
            ),
            source_ids=[],
            objective_ids=[],
            focus=body.focus,
            item_limit=body.item_limit,
            card_type_mix=list(body.card_type_mix),
            difficulty=body.difficulty,
            answer_length=body.answer_length,
            include_hints=body.include_hints,
            context_char_limit=body.context_char_limit,
        )
    elif (
        parsed.kind == "chat"
        and parsed.session_id
        and parsed.message_id is not None
        and parsed.practice_attempt_id is None
    ):
        session_id, message_id = await _resolve_learner_action_binding(
            course_id,
            session_id=parsed.session_id,
            assistant_message_id=parsed.message_id,
        )
        from deeptutor.courses.learner_actions import ready_current_source_ids

        source_ids = ready_current_source_ids(_service().list_sources(course_id))
        if not source_ids:
            raise HTTPException(
                status_code=409, detail="Course has no current ready sources"
            )
        canonical = arguments(
            origin=FlashcardGenerationOrigin(
                kind="chat",
                session_id=session_id,
                message_id=message_id,
            ),
            source_ids=source_ids,
            objective_ids=[],
            focus="Turn the selected Course answer into a reviewable study deck",
            item_limit=8,
            card_type_mix=["definition", "concept", "application"],
            difficulty="mixed",
            answer_length="short",
            include_hints=True,
            context_char_limit=12_000,
        )
    elif (
        parsed.kind == "practice_remediation"
        and parsed.practice_attempt_id
        and parsed.session_id is None
        and parsed.message_id is None
    ):
        _practice_set_id, objective_ids, source_ids = _practice_call(
            lambda: _practice_grading_service().remediation_scope(
                course_id, parsed.practice_attempt_id or ""
            )
        )
        canonical = arguments(
            origin=FlashcardGenerationOrigin(
                kind="practice_remediation",
                practice_attempt_id=parsed.practice_attempt_id,
            ),
            source_ids=source_ids,
            objective_ids=objective_ids,
            focus="Review the concepts missed in this quiz attempt",
            item_limit=8,
            card_type_mix=["recall", "application"],
            difficulty="mixed",
            answer_length="short",
            include_hints=True,
            context_char_limit=12_000,
        )
    if canonical is None:
        raise HTTPException(
            status_code=422, detail="Flashcard generation origin is invalid"
        )

    supplied = arguments(
        origin=parsed,
        source_ids=body.source_ids,
        objective_ids=body.objective_ids,
        focus=body.focus,
        item_limit=body.item_limit,
        card_type_mix=list(body.card_type_mix),
        difficulty=body.difficulty,
        answer_length=body.answer_length,
        include_hints=body.include_hints,
        context_char_limit=body.context_char_limit,
    )
    if supplied != canonical:
        raise HTTPException(
            status_code=422,
            detail="Flashcard proposal does not match server authority",
        )
    return canonical


class PublishFlashcardCandidatesRequest(_PracticeRequest):
    candidate_ids: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        min_length=1, max_length=48
    )
    expected_candidate_revision: int = Field(ge=1)


class LearnerActionRequest(_PracticeRequest):
    """A deliberately non-authoritative learner shortcut.

    There is no prompt, source, provider, tool, ownership, or path authority in
    this body.  The authenticated Course aggregate resolves all of that state.
    """

    action: Literal[
        "quiz_me", "explain_simpler", "make_flashcards", "review_weak_topics"
    ]
    session_id: str = Field(min_length=1, max_length=160)
    assistant_message_id: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=160)
    expected_course_revision: int = Field(ge=1)
    expected_course_write_epoch: int = Field(ge=1)


class GeneralStudyLearnerActionRequest(_PracticeRequest):
    action: Literal["make_flashcards"]
    session_id: str = Field(min_length=1, max_length=160)
    assistant_message_id: int = Field(ge=1)
    desired_count: int = Field(default=8, ge=1, le=48)
    destination_course_id: str | None = Field(default=None, min_length=1, max_length=80)


class LearnerActionResponse(_PracticeRequest):
    """Redacted, fixed-shape receipt for a server-owned learner action."""

    action: Literal[
        "quiz_me", "explain_simpler", "make_flashcards", "review_weak_topics"
    ]
    destination: Literal["practice", "flashcards", "chat_followup", "learning"]
    course_id: str
    course_revision: int = Field(ge=1)
    course_write_epoch: int = Field(ge=1)
    session_id: str
    parent_message_id: int
    objective_ids: list[str] = Field(default_factory=list, max_length=16)
    source_ids: list[str] = Field(default_factory=list, max_length=32)
    reason_code: Literal[
        "course_sources", "active_error", "low_mastery", "due_review", "no_targets", "message_context"
    ]
    operation_id: str | None = None
    operation_state: Literal[
        "queued",
        "running",
        "awaiting_review",
        "completed",
        "failed",
        "cancelling",
        "cancelled",
    ] | None = None
    practice_set_id: str | None = None
    practice_set_revision_id: str | None = None
    deck_id: str | None = None
    generation_brief: dict[str, Any] | None = None
    followup_text: str | None = Field(default=None, max_length=280)


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


def _generation_capabilities() -> dict[str, bool | str | None]:
    """Expose the same fail-closed provider decision used before allocation."""

    from deeptutor.courses.flashcard_generation_provider import (
        flashcard_generation_provider_available,
    )
    from deeptutor.courses.generation_provider import (
        practice_generation_provider_available,
    )

    practice = practice_generation_provider_available()
    flashcards = flashcard_generation_provider_available()
    grounded = practice and flashcards
    return {
        "grounded_generation": grounded,
        "practice_generation": practice,
        "flashcard_generation": flashcards,
        "flashcard_generation_reason": (
            None
            if flashcards
            else "Flashcard generation is not enabled on this server"
        ),
        "grounded_generation_reason": (
            None if grounded else "Grounded generation is not enabled on this server"
        ),
    }


@router.post("")
async def create_course(body: CreateCourseRequest):
    return _call(lambda: _service().create(body.title)).model_dump()


@router.get("")
async def list_courses(include_archived: bool = Query(default=True)):
    return {
        "courses": [
            course.model_dump()
            for course in _call(lambda: _service().list(include_archived=include_archived))
        ],
        "capabilities": _generation_capabilities(),
    }

@router.post("/general-study")
async def get_or_create_general_study():
    return _call(lambda: _service().general_study()).model_dump()


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


def _flashcard_generation_service():
    from deeptutor.courses.flashcard_generation_service import build_flashcard_generation_service
    return build_flashcard_generation_service(_service())


def _flashcard_generation_service_for(course_service):
    from deeptutor.courses.flashcard_generation_service import build_flashcard_generation_service
    return build_flashcard_generation_service(course_service)


def _run_flashcard_generation(owner_user_id: str, course_id: str, operation_id: str) -> None:
    from deeptutor.courses.flashcard_generation_service import unregister_live_flashcard_generation
    from deeptutor.courses.repository import CourseRepository
    from deeptutor.courses.service import CourseService
    from deeptutor.multi_user.paths import get_personal_path_service
    try:
        paths = get_personal_path_service(owner_user_id)
        service = CourseService(CourseRepository(paths.get_courses_db(), owner_user_id))
        _flashcard_generation_service_for(service).run_operation(course_id, operation_id)
    finally:
        unregister_live_flashcard_generation(owner_user_id, course_id, operation_id)


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

    if (
        request.operation.state == "queued"
        and register_live_practice_generation(
            request.operation.owner_user_id, course_id, request.operation.id
        )
    ):
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

    if (
        request.operation.state == "queued"
        and register_live_practice_generation(
            request.operation.owner_user_id, course_id, request.operation.id
        )
    ):
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
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    _practice, attempts = _practice_services()
    page = _practice_call(
        lambda: attempts.list_attempts(
            course_id,
            practice_set_id,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
    )
    return {
        "attempts": [
            item.model_dump(mode="json")
            for item in page
        ],
        "next_offset": offset + len(page) if len(page) == limit else None,
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


@router.post(
    "/{course_id}/practice/{practice_set_id}/attempts/{attempt_id}/flashcard-brief"
)
async def prepare_practice_remediation_flashcard_brief(
    course_id: str, practice_set_id: str, attempt_id: str
):
    course = _practice_call(lambda: _service().get(course_id))
    resolved_set_id, objective_ids, source_ids = _practice_call(
        lambda: _practice_grading_service().remediation_scope(
            course_id, attempt_id
        )
    )
    if resolved_set_id != practice_set_id:
        raise HTTPException(
            status_code=404, detail="Practice remediation resource not found"
        )
    receipt = _practice_call(
        lambda: _flashcard_generation_service().prepare_brief(
            course_id,
            focus="Review the concepts missed in this quiz attempt",
            source_ids=source_ids,
            objective_ids=objective_ids,
            expected_course_write_epoch=course.write_epoch,
            item_limit=8,
            card_type_mix=["recall", "application"],
            difficulty="mixed",
            answer_length="short",
            include_hints=True,
            origin={
                "kind": "practice_remediation",
                "practice_attempt_id": attempt_id,
            },
        )
    )
    return receipt.model_dump(mode="json")


@router.post("/{course_id}/flashcards")
async def create_flashcard_deck(course_id: str, body: CreateFlashcardDeckRequest):
    async with course_operation_lock(course_id):
        return _practice_call(
            lambda: _flashcard_service().create_deck(
                course_id, title=body.title,
                expected_course_write_epoch=body.expected_course_write_epoch,
            )
        ).model_dump(mode="json")


@router.post("/{course_id}/flashcard-generation", status_code=202)
async def create_generated_flashcard_deck(course_id: str, body: CreateGeneratedFlashcardDeckRequest, background_tasks: BackgroundTasks, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=160)):
    """Queue a source-grounded generated deck; output is never a request body."""
    authority = await _authoritative_flashcard_generation_arguments(course_id, body)
    async with course_operation_lock(course_id):
        request = _practice_call(lambda: _flashcard_generation_service().create_generated_deck(
            course_id, title=body.title, source_ids=authority["source_ids"], objective_ids=authority["objective_ids"],
            idempotency_key=idempotency_key, expected_course_write_epoch=body.expected_course_write_epoch,
            item_limit=authority["item_limit"], context_char_limit=authority["context_char_limit"],
            generation_brief={
                "focus": authority["focus"],
                "desired_count": authority["item_limit"],
                "card_type_mix": authority["card_type_mix"],
                "difficulty": authority["difficulty"],
                "answer_length": authority["answer_length"],
                "include_hints": authority["include_hints"],
            },
            origin=authority["origin"],
        ))
    from deeptutor.courses.flashcard_generation_service import register_live_flashcard_generation
    if (
        request.operation.state == "queued"
        and register_live_flashcard_generation(
            request.operation.owner_user_id, course_id, request.operation.id
        )
    ):
        background_tasks.add_task(
            _run_flashcard_generation,
            request.operation.owner_user_id,
            course_id,
            request.operation.id,
        )
    return request.model_dump(mode="json")


@router.post("/{course_id}/flashcard-generation/brief")
async def prepare_flashcard_generation_brief(
    course_id: str,
    body: CreateGeneratedFlashcardDeckRequest,
):
    authority = await _authoritative_flashcard_generation_arguments(course_id, body)
    receipt = _practice_call(
        lambda: _flashcard_generation_service().prepare_brief(
            course_id,
            focus=authority["focus"],
            source_ids=authority["source_ids"],
            objective_ids=authority["objective_ids"],
            expected_course_write_epoch=body.expected_course_write_epoch,
            item_limit=authority["item_limit"],
            card_type_mix=authority["card_type_mix"],
            difficulty=authority["difficulty"],
            answer_length=authority["answer_length"],
            include_hints=authority["include_hints"],
            origin=authority["origin"],
        )
    )
    return receipt.model_dump(mode="json")


@router.get("/{course_id}/flashcard-generation")
async def list_flashcard_generation_operations(course_id: str):
    return {"operations": [item.model_dump(mode="json") for item in _practice_call(lambda: _flashcard_generation_service().list_operations(course_id))]}


@router.get("/{course_id}/flashcard-generation/{operation_id}")
async def get_flashcard_generation_operation(course_id: str, operation_id: str):
    return _practice_call(lambda: _flashcard_generation_service().get_operation(course_id, operation_id)).model_dump(mode="json")


@router.post("/{course_id}/flashcard-generation/{operation_id}/publish")
async def publish_flashcard_generation_candidates(
    course_id: str,
    operation_id: str,
    body: PublishFlashcardCandidatesRequest,
):
    from deeptutor.courses.flashcard_generation_models import (
        FlashcardCandidatePublication,
    )

    async with course_operation_lock(course_id):
        operation = _practice_call(
            lambda: _flashcard_generation_service().publish_candidates(
                course_id,
                operation_id,
                FlashcardCandidatePublication(
                    candidate_ids=body.candidate_ids,
                    expected_candidate_revision=body.expected_candidate_revision,
                ),
            )
        )
    return operation.model_dump(mode="json")


@router.post("/{course_id}/flashcard-generation/{operation_id}/cancel")
async def cancel_flashcard_generation(course_id: str, operation_id: str):
    async with course_operation_lock(course_id):
        operation = _practice_call(
            lambda: _flashcard_generation_service().cancel_operation(
                course_id, operation_id
            )
        )
    return operation.model_dump(mode="json")


@router.post("/{course_id}/flashcards/{deck_id}/flashcard-generation", status_code=202)
async def create_flashcard_generation_successor(course_id: str, deck_id: str, body: CreateGeneratedFlashcardDeckRequest, background_tasks: BackgroundTasks, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=160)):
    authority = await _authoritative_flashcard_generation_arguments(
        course_id,
        body,
        allow_system_origin=False,
    )
    async with course_operation_lock(course_id):
        request = _practice_call(lambda: _flashcard_generation_service().request_successor(
            course_id, deck_id, title=body.title, source_ids=authority["source_ids"], objective_ids=authority["objective_ids"],
            idempotency_key=idempotency_key, expected_course_write_epoch=body.expected_course_write_epoch,
            item_limit=authority["item_limit"], context_char_limit=authority["context_char_limit"],
            generation_brief={
                "focus": authority["focus"],
                "desired_count": authority["item_limit"],
                "card_type_mix": authority["card_type_mix"],
                "difficulty": authority["difficulty"],
                "answer_length": authority["answer_length"],
                "include_hints": authority["include_hints"],
            },
            origin=authority["origin"],
        ))
    from deeptutor.courses.flashcard_generation_service import register_live_flashcard_generation
    if (
        request.operation.state == "queued"
        and register_live_flashcard_generation(
            request.operation.owner_user_id, course_id, request.operation.id
        )
    ):
        background_tasks.add_task(
            _run_flashcard_generation,
            request.operation.owner_user_id,
            course_id,
            request.operation.id,
        )
    return request.model_dump(mode="json")


@router.get("/{course_id}/flashcards")
async def list_flashcard_decks(
    course_id: str,
    include_archived: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    page = _practice_call(
        lambda: _flashcard_service().list_decks(
            course_id,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
    )
    return {
        "flashcard_decks": [item.model_dump(mode="json") for item in page],
        "next_offset": offset + len(page) if len(page) == limit else None,
    }


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


async def _resolve_learner_action_binding(
    course_id: str,
    *,
    session_id: str,
    assistant_message_id: int,
) -> tuple[str, int]:
    """Validate optional persisted conversation references in the owner scope.

    The personal session database is already namespaced by the authenticated
    identity.  Missing, foreign, wrong-Course, or wrong-role references all map
    to the same not-found outcome, so this action surface cannot become an ID
    oracle.
    """

    from deeptutor.services.session import get_personal_sqlite_session_store

    store = get_personal_sqlite_session_store()
    session = await store.get_session(session_id)
    if session is None or str(session.get("course_id") or "") != course_id:
        raise CourseNotFoundError("Course session not found")
    messages = await store.get_messages(str(session["id"]))
    message = next(
        (item for item in messages if int(item.get("id") or 0) == assistant_message_id),
        None,
    )
    if message is None or str(message.get("role") or "") != "assistant":
        raise CourseNotFoundError("Course assistant message not found")
    return str(session["id"]), int(message["id"])


async def _resolve_general_chat_context(
    *,
    session_id: str,
    assistant_message_id: int,
):
    """Resolve one owner-scoped course-less branch into bounded provenance."""

    from deeptutor.courses.conversation_flashcards import (
        select_conversation_context,
    )
    from deeptutor.services.session import get_session_store

    # General Chat is persisted by the generic turn runtime. For ordinary
    # users that store is already personal; for administrators it remains the
    # deployment admin workspace while Course and General Study data stay in
    # the administrator's separate personal workspace.
    store = get_session_store()
    session = await store.get_session(session_id)
    if session is None or session.get("course_id") is not None:
        raise CourseNotFoundError("General Chat session not found")
    messages = await store.get_messages_for_context(
        str(session["id"]), leaf_message_id=assistant_message_id
    )
    try:
        return select_conversation_context(
            messages,
            assistant_message_id=assistant_message_id,
        )
    except ValueError as exc:
        raise CourseNotFoundError("General Chat message not found") from exc


@router.post("/general-study/learner-actions")
async def prepare_general_study_learner_action(
    body: GeneralStudyLearnerActionRequest,
):
    """Prepare an editable, provider-free General Chat Flashcard proposal."""

    try:
        selected = await _resolve_general_chat_context(
            session_id=body.session_id,
            assistant_message_id=body.assistant_message_id,
        )
        general = _service().general_study()
        destination = (
            general
            if body.destination_course_id is None
            else _service().get(body.destination_course_id)
        )
        if destination.state != "active":
            raise CourseConflictError("Archived Courses cannot receive Flashcards")
        from deeptutor.multi_user.context import get_current_user

        session_scope = (
            "admin" if get_current_user().scope.kind == "admin" else "personal"
        )
        receipt = _flashcard_generation_service().prepare_brief(
            destination.id,
            focus=selected.focus,
            source_ids=[],
            objective_ids=[],
            expected_course_write_epoch=destination.write_epoch,
            item_limit=body.desired_count,
            card_type_mix=["definition", "concept", "application"],
            difficulty="mixed",
            answer_length="short",
            include_hints=True,
            origin={
                "kind": "general_chat",
                "session_id": body.session_id,
                "message_id": body.assistant_message_id,
                "selected_message_ids": list(selected.message_ids),
                "context_sha256": selected.context_sha256,
                "context_summary": selected.summary,
                "context_title": selected.title,
                "context_topics": list(selected.topics),
                "session_scope": session_scope,
            },
        )
        return {
            "action": body.action,
            "destination": "flashcards",
            "course_id": destination.id,
            "course_revision": destination.revision,
            "course_write_epoch": destination.write_epoch,
            "session_id": body.session_id,
            "parent_message_id": body.assistant_message_id,
            "generation_brief": receipt.model_dump(mode="json"),
        }
    except CourseNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="General Chat learner action not found"
        ) from exc
    except CourseConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _learner_action_response(
    *,
    action: str,
    destination: str,
    course,
    session_id: str,
    assistant_message_id: int,
    objective_ids: list[str],
    source_ids: list[str],
    reason_code: str,
    operation=None,
    practice_set_id: str | None = None,
    practice_set_revision_id: str | None = None,
    deck_id: str | None = None,
    generation_brief: dict[str, Any] | None = None,
    followup_text: str | None = None,
) -> LearnerActionResponse:
    """Return a deliberately small action receipt, never a generation record."""

    return LearnerActionResponse(
        action=action,
        destination=destination,
        course_id=course.id,
        course_revision=course.revision,
        course_write_epoch=course.write_epoch,
        session_id=session_id,
        parent_message_id=assistant_message_id,
        objective_ids=objective_ids,
        source_ids=source_ids,
        reason_code=reason_code,
        operation_id=getattr(operation, "id", None),
        operation_state=getattr(operation, "state", None),
        practice_set_id=practice_set_id,
        practice_set_revision_id=practice_set_revision_id,
        deck_id=deck_id,
        generation_brief=generation_brief,
        followup_text=followup_text,
    )


@router.post(
    "/{course_id}/learner-actions",
    status_code=202,
    response_model=LearnerActionResponse,
)
async def create_course_learner_action(
    course_id: str, body: LearnerActionRequest, background_tasks: BackgroundTasks
):
    """Resolve a learner shortcut entirely from owned persisted Course state.

    Generated resources use the existing fenced background runners.  The only
    chat action returns a fixed server-owned follow-up instruction; it does not
    copy or transform the selected assistant message into a client-controlled
    prompt.
    """

    try:
        async with course_operation_lock(course_id):
            service = _service()
            course = service.get(course_id)
            if course.state != "active":
                raise CourseConflictError("Archived courses cannot accept learner actions")
            if (
                course.revision != body.expected_course_revision
                or course.write_epoch != body.expected_course_write_epoch
            ):
                raise CourseConflictError("Course authority is stale")

            session_id, assistant_message_id = await _resolve_learner_action_binding(
                course.id,
                session_id=body.session_id,
                assistant_message_id=body.assistant_message_id,
            )
            if body.action == "explain_simpler":
                return _learner_action_response(
                    action=body.action,
                    destination="chat_followup",
                    course=course,
                    session_id=session_id,
                    assistant_message_id=assistant_message_id,
                    objective_ids=[],
                    source_ids=[],
                    reason_code="message_context",
                    followup_text=(
                        "Explain the selected Course answer more simply, using one short "
                        "example and preserving its Course grounding."
                    ),
                )

            from deeptutor.courses.learner_actions import (
                ready_current_source_ids,
                weak_objective_ids,
                weak_objective_reason_code,
            )

            objective_ids: list[str] = []
            progress = None
            if body.action == "review_weak_topics":
                _course, store = _course_learning_store(course.id, require_active=False)
                progress = store.load(course.learning_path_id)
                objective_ids = weak_objective_ids(progress)
                source_ids = ready_current_source_ids(service.list_sources(course.id))
                if not objective_ids:
                    return _learner_action_response(
                        action=body.action,
                        destination="learning",
                        course=course,
                        session_id=session_id,
                        assistant_message_id=assistant_message_id,
                        objective_ids=[],
                        source_ids=source_ids,
                        reason_code="no_targets",
                    )
            else:
                source_ids = ready_current_source_ids(service.list_sources(course.id))

            if not source_ids:
                raise CourseConflictError("Course has no current ready sources")

            if body.action in {"quiz_me", "review_weak_topics"}:
                title = (
                    "Course quiz"
                    if body.action == "quiz_me"
                    else "Weak-topic Course review"
                )
                request = _practice_generation_service().create_generated_practice(
                    course.id,
                    title=title,
                    source_ids=source_ids,
                    objective_ids=objective_ids,
                    idempotency_key=body.idempotency_key,
                    expected_course_write_epoch=course.write_epoch,
                    item_limit=5,
                    context_char_limit=12_000,
                )
                operation = request.operation
                from deeptutor.courses.generation_service import register_live_practice_generation

                if (
                    operation.state == "queued"
                    and register_live_practice_generation(
                        operation.owner_user_id, course.id, operation.id
                    )
                ):
                    background_tasks.add_task(
                        _run_practice_generation,
                        operation.owner_user_id,
                        course.id,
                        operation.id,
                    )
                return _learner_action_response(
                    action=body.action,
                    destination="practice",
                    course=course,
                    session_id=session_id,
                    assistant_message_id=assistant_message_id,
                    objective_ids=objective_ids,
                    source_ids=source_ids,
                    reason_code=(
                        "course_sources"
                        if body.action == "quiz_me"
                        else weak_objective_reason_code(progress)
                    ),
                    operation=operation,
                    practice_set_id=request.practice_set_id,
                    practice_set_revision_id=request.practice_set_revision_id,
                )

            brief = _flashcard_generation_service().prepare_brief(
                course.id,
                focus="Turn the selected Course answer into a reviewable study deck",
                source_ids=source_ids,
                objective_ids=[],
                expected_course_write_epoch=course.write_epoch,
                item_limit=8,
                card_type_mix=["definition", "concept", "application"],
                difficulty="mixed",
                answer_length="short",
                include_hints=True,
                origin={
                    "kind": "chat",
                    "session_id": session_id,
                    "message_id": assistant_message_id,
                },
            )
            return _learner_action_response(
                action=body.action,
                destination="flashcards",
                course=course,
                session_id=session_id,
                assistant_message_id=assistant_message_id,
                objective_ids=[],
                source_ids=source_ids,
                reason_code="course_sources",
                generation_brief=brief.model_dump(mode="json"),
            )
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course learner action not found") from exc
    except (CourseConflictError, LearningConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _course_learning_store(course_id: str, *, require_active: bool):
    from deeptutor.courses.service import install_personal_course_context
    from deeptutor.learning.storage import LearningStore
    from deeptutor.multi_user.paths import get_personal_path_service

    service = _service()
    course = service.get(course_id)
    if course.workspace_kind != "academic_course":
        raise CourseConflictError("General Study does not have Course mastery")
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
        from deeptutor.courses.learner_actions import (
            learner_safe_next,
            learner_safe_progress,
        )
        from deeptutor.learning import policy as learning_policy

        course, store = _course_learning_store(course_id, require_active=False)
        progress = store.load(course.learning_path_id)
        return {
            "course_id": course.id,
            "learning_path_id": course.learning_path_id,
            "initialized": progress is not None and bool(progress.modules),
            "progress": learner_safe_progress(progress) if progress else None,
            "next": learner_safe_next(progress),
            "map": learning_policy.map_summary(progress) if progress else [],
        }
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course resource not found") from exc
    except CourseConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    from deeptutor.courses.grading_repository import CourseGradingRepository
    from deeptutor.learning.service import LearningService
    try:
        async with course_operation_lock(course_id):
            course, store = _course_learning_store(course_id, require_active=True)
            modules = _parse_modules(body.modules)
            _validate_runnable_modules(modules)
            retained_grading_evidence = CourseGradingRepository(
                _service().repository
            ).has_course_evidence(course.id)
            service = LearningService(store)
            try:
                progress = service.get_or_create(course.learning_path_id)
            except LearningDataError:
                if retained_grading_evidence:
                    raise LearningConflictError(
                        "Course learning plan with grading evidence cannot be replaced"
                    )
                # Initialization is the explicit repair action. Preserve the
                # unreadable bytes for operator recovery before starting fresh.
                store.quarantine_corrupt(course.learning_path_id)
                progress = service.get_or_create(course.learning_path_id)
            replaced = service.init_modules(
                progress,
                modules,
                retained_grading_evidence=retained_grading_evidence,
            )
            if replaced:
                await _cancel_owned_course_session(course.id, body.session_id)
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
    except LearningConflictError as exc:
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
