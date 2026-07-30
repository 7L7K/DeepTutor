from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from deeptutor.courses.conversation_flashcards import select_conversation_context
from deeptutor.courses.flashcard_generation_models import (
    FlashcardCandidatePublication,
    FlashcardCitation,
    FlashcardSourceReceipt,
    GeneratedFlashcard,
    GeneratedFlashcardOutput,
)
from deeptutor.courses.flashcard_generation_repository import (
    CourseFlashcardGenerationRepository,
)
from deeptutor.courses.flashcard_generation_provider import (
    DeterministicFlashcardGenerationProvider,
)
from deeptutor.courses.flashcard_generation_service import (
    CourseFlashcardGenerationService,
)
from deeptutor.courses.repository import CourseConflictError, CourseRepository
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def test_conversation_selector_freezes_relevant_branch_without_system_text() -> None:
    selected = select_conversation_context(
        [
            {"id": 1, "role": "system", "content": "hidden system instruction"},
            {"id": 2, "role": "user", "content": "Plan a weekend trip"},
            {"id": 3, "role": "assistant", "content": "Visit the museum"},
            {"id": 4, "role": "user", "content": "Explain slope and y intercept"},
            {
                "id": 5,
                "role": "assistant",
                "content": "Slope is the rate of change and the y-intercept is where x is zero.",
            },
        ],
        assistant_message_id=5,
        max_messages=4,
    )

    assert selected.message_ids[-2:] == (4, 5)
    assert "system instruction" not in selected.text
    assert len(selected.context_sha256) == 64
    assert selected.summary == "Explain slope and y intercept"


def test_conversation_selector_requires_a_real_user_assistant_exchange() -> None:
    with pytest.raises(ValueError, match="user and assistant"):
        select_conversation_context(
            [{"id": 1, "role": "assistant", "content": "Unpaired response"}],
            assistant_message_id=1,
        )


def _general_operation(path: Path, *, idempotency_key: str = "conversation-linear-equations"):
    courses = CourseRepository(path, "u_alice")
    general = courses.get_or_create_general_study()
    repository = CourseFlashcardGenerationRepository(courses)
    request = repository.create_generated_deck(
        general.id,
        title="Linear equations",
        source_ids=[],
        idempotency_key=idempotency_key,
        expected_course_write_epoch=general.write_epoch,
        item_limit=1,
        generation_brief={
            "focus": "Understand slope and intercepts",
            "desired_count": 1,
            "card_type_mix": ["concept"],
            "difficulty": "mixed",
            "answer_length": "short",
            "include_hints": True,
        },
        origin={
            "kind": "general_chat",
            "session_id": "unified_general",
            "message_id": 4,
            "selected_message_ids": [3, 4],
            "context_sha256": "a" * 64,
            "context_summary": "slope and intercepts",
        },
    )
    operation, claimed = repository.claim_operation(general.id, request.operation.id)
    assert claimed
    return courses, general, repository, operation


def test_general_chat_candidates_publish_without_fake_course_citations(
    tmp_path: Path,
) -> None:
    _courses, general, repository, operation = _general_operation(
        tmp_path / "courses.db"
    )
    staged = repository.stage_candidates(
        general.id,
        operation.id,
        GeneratedFlashcardOutput(
            provider_label="deterministic-local",
            cards=[
                GeneratedFlashcard(
                    prompt="What does slope measure?",
                    answer="The rate of change.",
                    card_type="concept",
                    citations=[],
                )
            ],
        ),
        account_active=True,
        material_receipts=[],
    )
    assert staged.state == "awaiting_review"
    completed = repository.publish_candidates(
        general.id,
        operation.id,
        FlashcardCandidatePublication(
            candidate_ids=[staged.candidates[0].candidate_id],
            expected_candidate_revision=staged.candidate_revision,
        ),
        account_active=True,
    )
    assert completed.state == "completed"
    assert repository.course_repository.get_course(general.id).workspace_kind == (
        "general_study"
    )


def test_general_chat_candidates_cannot_claim_course_source_citations(
    tmp_path: Path,
) -> None:
    _courses, general, repository, operation = _general_operation(
        tmp_path / "courses.db"
    )
    receipt = FlashcardSourceReceipt(
        source_id="src_" + ("b" * 32),
        source_revision=1,
        content_sha256="c" * 64,
    )
    with pytest.raises(ValueError, match="cannot claim Course citations"):
        repository.stage_candidates(
            general.id,
            operation.id,
            GeneratedFlashcardOutput(
                provider_label="deterministic-local",
                cards=[
                    GeneratedFlashcard(
                        prompt="What does slope measure?",
                        answer="The rate of change.",
                        card_type="concept",
                        citations=[FlashcardCitation(**receipt.model_dump())],
                    )
                ],
            ),
            account_active=True,
            material_receipts=[],
        )


def test_academic_course_accepts_general_chat_without_course_grounding(
    tmp_path: Path,
) -> None:
    courses = CourseRepository(tmp_path / "courses.db", "u_alice")
    course = courses.create_course("Math")
    repository = CourseFlashcardGenerationRepository(courses)

    request = repository.create_generated_deck(
        course.id,
        title="Conversation cards saved to Math",
        source_ids=[],
        idempotency_key="conversation-saved-to-course",
        expected_course_write_epoch=course.write_epoch,
        origin={
            "kind": "general_chat",
            "session_id": "unified_general",
            "message_id": 4,
            "selected_message_ids": [3, 4],
            "context_sha256": "a" * 64,
            "context_summary": "slope",
        },
    )
    assert request.operation.course_id == course.id
    assert request.operation.source_snapshot == []
    assert request.operation.objective_ids == []


def test_general_study_filters_duplicates_from_existing_ready_decks(
    tmp_path: Path,
) -> None:
    path = tmp_path / "courses.db"
    _courses, general, repository, first = _general_operation(
        path, idempotency_key="first-linear-equations"
    )
    output = GeneratedFlashcardOutput(
        provider_label="deterministic-local",
        cards=[
            GeneratedFlashcard(
                prompt="What does slope measure?",
                answer="The rate of change.",
                card_type="concept",
            )
        ],
    )
    staged = repository.stage_candidates(
        general.id,
        first.id,
        output,
        account_active=True,
        material_receipts=[],
    )
    repository.publish_candidates(
        general.id,
        first.id,
        FlashcardCandidatePublication(
            candidate_ids=[staged.candidates[0].candidate_id],
            expected_candidate_revision=staged.candidate_revision,
        ),
        account_active=True,
    )
    _courses, general, repository, second = _general_operation(
        path, idempotency_key="second-linear-equations"
    )

    from deeptutor.courses.flashcard_generation_repository import (
        FlashcardGenerationInsufficientCandidates,
    )

    with pytest.raises(FlashcardGenerationInsufficientCandidates):
        repository.stage_candidates(
            general.id,
            second.id,
            output,
            account_active=True,
            material_receipts=[],
        )


def test_general_chat_generation_rechecks_personal_session_before_candidates(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEEECHR_TEST_DETERMINISTIC_PROVIDER", "1")
    session_path = tmp_path / "chat_history.db"
    store = SQLiteSessionStore(db_path=session_path)

    async def seed():
        await store.create_session(
            title="Linear equations", session_id="unified_general", course_id=None
        )
        parent_id = None
        assistant_id = None
        for index in range(15):
            user_id = await store.add_message(
                "unified_general",
                "user",
                f"Explain linear-equation idea {index}",
                parent_message_id=parent_id,
            )
            assistant_id = await store.add_message(
                "unified_general",
                "assistant",
                f"Idea {index}: slope is a rate and an intercept is a starting value.",
                parent_message_id=user_id,
            )
            parent_id = assistant_id
        assert assistant_id is not None
        return assistant_id, await store.get_messages_for_context(
            "unified_general", leaf_message_id=assistant_id
        )

    assistant_id, messages = asyncio.run(seed())
    selected = select_conversation_context(
        messages, assistant_message_id=assistant_id
    )
    courses = CourseRepository(tmp_path / "courses.db", "u_alice")
    general = courses.get_or_create_general_study()
    repository = CourseFlashcardGenerationRepository(courses)
    request = repository.create_generated_deck(
        general.id,
        title="Linear equations",
        source_ids=[],
        idempotency_key="full-conversation-run",
        expected_course_write_epoch=general.write_epoch,
        item_limit=1,
        generation_brief={
            # Deliberately differs from the selector's initial empty focus.
            # Execution must reload the frozen IDs, not silently re-rank them.
            "focus": "Compare early and late slope examples",
            "desired_count": 1,
            "card_type_mix": ["concept"],
            "difficulty": "mixed",
            "answer_length": "short",
            "include_hints": True,
        },
        origin={
            "kind": "general_chat",
            "session_id": "unified_general",
            "message_id": assistant_id,
            "selected_message_ids": list(selected.message_ids),
            "context_sha256": selected.context_sha256,
            "context_summary": selected.summary,
        },
    )
    monkeypatch.setattr(
        "deeptutor.multi_user.paths.get_personal_path_service",
        lambda _owner=None: SimpleNamespace(
            get_chat_history_db=lambda: session_path
        ),
    )
    service = CourseFlashcardGenerationService(
        repository,
        provider=DeterministicFlashcardGenerationProvider(),
        account_active=lambda _owner: True,
    )

    operation = service.run_operation(general.id, request.operation.id)

    assert operation.state == "awaiting_review"
    assert operation.candidates is not None
    assert len(operation.candidates) == 1
    assert operation.candidates[0].citations == []
    assert len(selected.message_ids) == 12


def test_general_chat_generation_stops_before_provider_when_frozen_context_changes(
    tmp_path: Path, monkeypatch
) -> None:
    session_path = tmp_path / "chat_history.db"
    store = SQLiteSessionStore(db_path=session_path)

    async def seed():
        await store.create_session(
            title="Cell energy", session_id="unified_changed", course_id=None
        )
        user_id = await store.add_message(
            "unified_changed", "user", "How do mitochondria make ATP?"
        )
        assistant_id = await store.add_message(
            "unified_changed",
            "assistant",
            "They use a proton gradient to power ATP synthase.",
            parent_message_id=user_id,
        )
        return assistant_id, await store.get_messages_for_context(
            "unified_changed", leaf_message_id=assistant_id
        )

    assistant_id, messages = asyncio.run(seed())
    selected = select_conversation_context(
        messages, assistant_message_id=assistant_id
    )
    courses = CourseRepository(tmp_path / "courses.db", "u_alice")
    general = courses.get_or_create_general_study()
    repository = CourseFlashcardGenerationRepository(courses)
    request = repository.create_generated_deck(
        general.id,
        title="Cell energy",
        source_ids=[],
        idempotency_key="changed-conversation-run",
        expected_course_write_epoch=general.write_epoch,
        item_limit=1,
        generation_brief={
            "focus": "Understand ATP production",
            "desired_count": 1,
            "card_type_mix": ["concept"],
            "difficulty": "mixed",
            "answer_length": "short",
            "include_hints": True,
        },
        origin={
            "kind": "general_chat",
            "session_id": "unified_changed",
            "message_id": assistant_id,
            "selected_message_ids": list(selected.message_ids),
            "context_sha256": selected.context_sha256,
            "context_summary": selected.summary,
        },
    )
    with sqlite3.connect(session_path) as conn:
        conn.execute(
            "UPDATE messages SET content = ? WHERE id = ?",
            ("This message changed after review.", assistant_id),
        )
    monkeypatch.setattr(
        "deeptutor.multi_user.paths.get_personal_path_service",
        lambda _owner=None: SimpleNamespace(
            get_chat_history_db=lambda: session_path
        ),
    )

    class ProviderSpy:
        called = False

        def generate(self, _request):
            self.called = True
            raise AssertionError("provider must not be called")

    provider = ProviderSpy()
    service = CourseFlashcardGenerationService(
        repository,
        provider=provider,
        account_active=lambda _owner: True,
    )

    operation = service.run_operation(general.id, request.operation.id)

    assert operation.state == "failed"
    assert operation.error_code == "authority_changed"
    assert provider.called is False
