"""P4-07 durable grounded Flashcard generation contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
import sqlite3
import threading

import pytest

from deeptutor.courses.flashcard_generation_models import (
    FlashcardCandidatePublication,
    FlashcardCitation,
    FlashcardGenerationOrigin,
    FlashcardSourceReceipt,
    GeneratedFlashcard,
    GeneratedFlashcardOutput,
)
from deeptutor.courses.flashcard_generation_provider import (
    FlashcardGenerationFocusUnsupported,
)
from deeptutor.courses.flashcard_generation_repository import (
    CourseFlashcardGenerationRepository,
    FlashcardGenerationInsufficientCandidates,
)
from deeptutor.courses.flashcard_generation_service import (
    CourseFlashcardGenerationService,
)
from deeptutor.courses.flashcard_repository import CourseFlashcardRepository
from deeptutor.courses.flashcard_service import CourseFlashcardService
from deeptutor.courses.repository import CourseConflictError, CourseNotFoundError, CourseRepository


def _setup(path: Path, owner: str = "u_alice"):
    courses = CourseRepository(path, owner)
    course = courses.create_course("Biology")
    source = courses.create_source(
        course.id, kind="notes", display_name="notes.txt", manifest=[], content_sha256="a" * 64
    )
    source = courses.transition_source(
        course.id,
        source.id,
        operation_id=source.operation_id or "",
        expected_source_revision=source.revision,
        expected_course_revision=course.revision,
        expected_write_epoch=course.write_epoch,
        state="ready",
    )
    return courses, course, source, CourseFlashcardGenerationRepository(courses)


def _output(source) -> GeneratedFlashcardOutput:
    receipt = FlashcardSourceReceipt(
        source_id=source.id, source_revision=source.revision, content_sha256=source.content_sha256
    )
    return GeneratedFlashcardOutput(
        provider_label="deterministic-local",
        cards=[
            GeneratedFlashcard(
                prompt=f"What is ATP? {ordinal}",
                answer=f"Energy {ordinal}",
                citations=[FlashcardCitation(**receipt.model_dump())],
            )
            for ordinal in range(8)
        ],
    )


def test_unsupported_focus_fails_before_any_provider_call(tmp_path: Path) -> None:
    _courses, course, source, repository = _setup(tmp_path / "unsupported-focus.db")
    request = repository.create_generated_deck(
        course.id,
        title="Bread",
        source_ids=[source.id],
        idempotency_key="unsupported-focus",
        expected_course_write_epoch=course.write_epoch,
        generation_brief={
            "focus": "how to bake sourdough bread",
            "desired_count": 8,
            "card_type_mix": ["concept"],
            "difficulty": "mixed",
            "answer_length": "short",
            "include_hints": True,
        },
    )

    class UnsupportedResolver:
        def resolve_for_focus(self, **_kwargs):
            raise FlashcardGenerationFocusUnsupported("not covered")

    class CountingProvider:
        calls = 0

        def generate(self, _request):
            self.calls += 1
            return _output(source)

    provider = CountingProvider()
    service = CourseFlashcardGenerationService(
        repository,
        provider=provider,
        source_text_resolver=UnsupportedResolver(),
        account_active=lambda _owner: True,
        identity_lock=lambda: nullcontext(),
    )

    result = service.run_operation(course.id, request.operation.id)

    assert result.state == "failed"
    assert result.error_code == "invalid_output"
    assert provider.calls == 0


@pytest.mark.parametrize(
    "origin",
    [
        {"kind": "chat", "session_id": "session-a", "message_id": 1},
        {
            "kind": "practice_remediation",
            "practice_attempt_id": "att_" + ("a" * 32),
        },
    ],
)
def test_system_proposals_use_owned_material_without_wrapper_focus_blocking(
    tmp_path: Path,
    origin: dict[str, object],
) -> None:
    _courses, course, source, repository = _setup(
        tmp_path / f"{origin['kind']}.db"
    )
    request = repository.create_generated_deck(
        course.id,
        title="Prepared review",
        source_ids=[source.id],
        idempotency_key=f"prepared-{origin['kind']}",
        expected_course_write_epoch=course.write_epoch,
        origin=origin,
        generation_brief={
            "focus": (
                "Turn the selected Course answer into a reviewable study deck"
                if origin["kind"] == "chat"
                else "Review the concepts missed in this quiz attempt"
            ),
            "desired_count": 8,
            "card_type_mix": ["recall"],
            "difficulty": "mixed",
            "answer_length": "short",
            "include_hints": True,
        },
    )

    class OriginAwareResolver:
        focused_calls = 0
        availability_calls = 0

        def resolve_for_focus(self, **_kwargs):
            self.focused_calls += 1
            raise FlashcardGenerationFocusUnsupported("wrapper is not a topic")

        def resolve(self, *, receipts, **_kwargs):
            self.availability_calls += 1
            from deeptutor.courses.flashcard_generation_models import (
                FlashcardGenerationSourceText,
            )

            return [
                FlashcardGenerationSourceText(
                    receipt=receipt,
                    text="ATP stores cellular energy.",
                )
                for receipt in receipts
            ]

    class CountingProvider:
        calls = 0

        def generate(self, _request):
            self.calls += 1
            return _output(source)

    resolver = OriginAwareResolver()
    provider = CountingProvider()
    service = CourseFlashcardGenerationService(
        repository,
        provider=provider,
        source_text_resolver=resolver,
        account_active=lambda _owner: True,
        identity_lock=lambda: nullcontext(),
    )

    result = service.run_operation(course.id, request.operation.id)

    assert result.state == "awaiting_review"
    assert resolver.focused_calls == 0
    assert resolver.availability_calls == 1
    assert provider.calls == 1


def test_topic_generation_can_run_without_course_material(tmp_path: Path) -> None:
    _courses, course, source, repository = _setup(tmp_path / "topic-only.db")
    request = repository.create_generated_deck(
        course.id,
        title="Cellular energy",
        source_ids=[],
        idempotency_key="topic-only",
        expected_course_write_epoch=course.write_epoch,
        origin={"kind": "topic"},
        generation_brief={
            "focus": "cellular energy",
            "desired_count": 2,
            "card_type_mix": ["concept"],
            "difficulty": "mixed",
            "answer_length": "short",
            "include_hints": True,
        },
        item_limit=2,
    )

    class CountingProvider:
        calls = 0

        def generate(self, generation_input):
            self.calls += 1
            assert generation_input.origin.kind == "topic"
            assert generation_input.source_material == []
            assert generation_input.conversation_context is None
            return GeneratedFlashcardOutput(
                provider_label="deterministic-local",
                cards=[
                    GeneratedFlashcard(
                        prompt=f"What is cellular energy? {ordinal}",
                        answer=f"A cell energy concept {ordinal}.",
                        card_type="concept",
                        citations=[],
                    )
                    for ordinal in range(2)
                ],
            )

    provider = CountingProvider()
    service = CourseFlashcardGenerationService(
        repository,
        provider=provider,
        source_text_resolver=object(),
        account_active=lambda _owner: True,
        identity_lock=lambda: nullcontext(),
    )

    result = service.run_operation(course.id, request.operation.id)

    assert result.state == "awaiting_review"
    assert provider.calls == 1
    with pytest.raises(ValueError, match="cannot claim Course sources"):
        repository.create_generated_deck(
            course.id,
            title="Invalid topic",
            source_ids=[source.id],
            idempotency_key="topic-with-source",
            expected_course_write_epoch=course.write_epoch,
            origin=FlashcardGenerationOrigin(kind="topic"),
        )


def _complete(repo, course, source, request):
    operation, claimed = repo.claim_operation(course.id, request.operation.id)
    assert claimed
    staged = repo.stage_candidates(
        course.id,
        operation.id,
        _output(source),
        account_active=True,
        material_receipts=[
            FlashcardSourceReceipt(
                source_id=source.id,
                source_revision=source.revision,
                content_sha256=source.content_sha256,
            )
        ],
    )
    assert staged.state == "awaiting_review"
    assert staged.candidates
    return repo.publish_candidates(
        course.id,
        operation.id,
        FlashcardCandidatePublication(
            candidate_ids=[candidate.candidate_id for candidate in staged.candidates],
            expected_candidate_revision=staged.candidate_revision,
        ),
        account_active=True,
    )


def test_ready_generated_deck_accepts_user_edits_and_additions(tmp_path: Path) -> None:
    courses, course, source, repository = _setup(tmp_path / "generated-edits.db")
    request = repository.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key="generated-edits",
        expected_course_write_epoch=course.write_epoch,
    )
    assert _complete(repository, course, source, request).state == "completed"

    flashcards = CourseFlashcardService(CourseFlashcardRepository(courses))
    view = flashcards.get_deck(course.id, request.deck_id)
    card = view.cards[0]
    changed = flashcards.update_card(
        course.id,
        request.deck_id,
        card.id,
        prompt="What is ATP?",
        answer="The cell's usable energy currency.",
        objective_ids=("cell_energy",),
        expected_card_revision=card.revision,
        expected_deck_revision=view.deck.revision,
        expected_course_write_epoch=course.write_epoch,
    )

    assert changed.edited_by_user is True
    after_edit = flashcards.get_deck(course.id, request.deck_id)
    added = flashcards.add_card(
        course.id,
        request.deck_id,
        prompt="What does ATP power?",
        answer="Cellular work.",
        expected_deck_revision=after_edit.deck.revision,
        expected_course_write_epoch=course.write_epoch,
    )
    assert added.edited_by_user is False
    assert flashcards.get_deck(course.id, request.deck_id).cards[-1].prompt == (
        "What does ATP power?"
    )


def test_idempotency_atomic_publication_and_successor_lineage(tmp_path: Path) -> None:
    courses, course, source, repo = _setup(tmp_path / "courses.db")
    request = repo.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key="same-request",
        expected_course_write_epoch=course.write_epoch,
    )
    same = repo.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key="same-request",
        expected_course_write_epoch=course.write_epoch,
    )
    assert (same.deck_id, same.operation.id) == (request.deck_id, request.operation.id)
    unavailable_replay = repo.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key="same-request",
        expected_course_write_epoch=course.write_epoch,
        provider_available=False,
    )
    assert (unavailable_replay.deck_id, unavailable_replay.operation.id) == (
        request.deck_id,
        request.operation.id,
    )
    with pytest.raises(CourseConflictError, match="provider is unavailable"):
        repo.create_generated_deck(
            course.id,
            title="Other terms",
            source_ids=[source.id],
            idempotency_key="new-unavailable-request",
            expected_course_write_epoch=course.write_epoch,
            provider_available=False,
        )
    # A same-key replay after the exact source receipt changes is not silently
    # treated as the old request.
    with courses._write_lock, courses._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE course_sources SET revision=revision+1 WHERE id=?", (source.id,))
    with pytest.raises(CourseConflictError, match="Idempotency"):
        repo.create_generated_deck(
            course.id,
            title="Terms",
            source_ids=[source.id],
            idempotency_key="same-request",
            expected_course_write_epoch=course.write_epoch,
        )
    # Restore the exact frozen receipt only for the happy-path publication.
    with courses._write_lock, courses._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE course_sources SET revision=revision-1 WHERE id=?", (source.id,))
    with sqlite3.connect(tmp_path / "courses.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM flashcards").fetchone()[0] == 0
    assert _complete(repo, course, source, request).state == "completed"
    successor = repo.create_generated_deck(
        course.id,
        title="Updated terms",
        source_ids=[source.id],
        idempotency_key="new-request",
        expected_course_write_epoch=course.write_epoch,
        supersedes_deck_id=request.deck_id,
    )
    assert successor.deck_id != request.deck_id
    assert successor.operation.supersedes_deck_id == request.deck_id
    with sqlite3.connect(tmp_path / "courses.db") as conn:
        assert (
            conn.execute(
                "SELECT supersedes_deck_id FROM flashcard_decks WHERE id=?", (successor.deck_id,)
            ).fetchone()[0]
            == request.deck_id
        )


def test_foreign_ids_and_changed_sources_are_safe(tmp_path: Path) -> None:
    courses, course, source, repo = _setup(tmp_path / "alice.db")
    _other_courses, other_course, _other_source, other = _setup(tmp_path / "bob.db", "u_bob")
    request = repo.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key="source-change",
        expected_course_write_epoch=course.write_epoch,
    )
    with pytest.raises(CourseNotFoundError):
        other.get_operation(other_course.id, request.operation.id)
    # Replacing a source revision fences the final publication and leaves no card.
    operation, _ = repo.claim_operation(course.id, request.operation.id)
    with courses._write_lock, courses._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE course_sources SET revision=revision+1 WHERE id=?", (source.id,))
    receipt = FlashcardSourceReceipt(
        source_id=source.id, source_revision=source.revision, content_sha256=source.content_sha256
    )
    with pytest.raises(CourseConflictError, match="sources"):
        repo.stage_candidates(
            course.id,
            operation.id,
            _output(source),
            account_active=True,
            material_receipts=[receipt],
        )
    assert repo.fail_operation(course.id, operation.id, "source_changed").state == "failed"


def test_invalid_citation_and_restart_orphan_never_publish(tmp_path: Path) -> None:
    _courses, course, source, repo = _setup(tmp_path / "courses.db")
    request = repo.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key="bad-output",
        expected_course_write_epoch=course.write_epoch,
    )
    operation, _ = repo.claim_operation(course.id, request.operation.id)
    bad = GeneratedFlashcardOutput(
        provider_label="deterministic-local",
        cards=[
            GeneratedFlashcard(
                prompt="p",
                answer="a",
                citations=[
                    FlashcardCitation(
                        source_id="src_" + "b" * 32, source_revision=1, content_sha256="b" * 64
                    )
                ],
            )
        ],
    )
    receipt = FlashcardSourceReceipt(
        source_id=source.id, source_revision=source.revision, content_sha256=source.content_sha256
    )
    with pytest.raises(ValueError, match="citation"):
        repo.stage_candidates(
            course.id, operation.id, bad, account_active=True, material_receipts=[receipt]
        )
    assert repo.fail_operation(course.id, operation.id, "invalid_output").state == "failed"
    with sqlite3.connect(tmp_path / "courses.db") as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE flashcard_generation_operations SET updated_at=updated_at+1 WHERE id=?",
                (operation.id,),
            )
    orphan = repo.create_generated_deck(
        course.id,
        title="Second",
        source_ids=[source.id],
        idempotency_key="orphan",
        expected_course_write_epoch=course.write_epoch,
    )
    assert repo.reconcile_orphaned_operations(course.id, live_operation_ids=set()) == 1
    assert repo.get_operation(course.id, orphan.operation.id).error_code == "interrupted"


def test_concurrent_same_key_creates_one_operation(tmp_path: Path) -> None:
    path = tmp_path / "courses.db"
    _courses, course, source, _repo = _setup(path)
    barrier = threading.Barrier(2)

    def create() -> str:
        repo = CourseFlashcardGenerationRepository(CourseRepository(path, "u_alice"))
        barrier.wait(timeout=5)
        return repo.create_generated_deck(
            course.id,
            title="Terms",
            source_ids=[source.id],
            idempotency_key="same-key",
            expected_course_write_epoch=course.write_epoch,
        ).operation.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(lambda _: create(), range(2)))) == 1
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM flashcard_generation_operations").fetchone()[0] == 1
        )


def test_direct_sql_cannot_publish_or_mutate_terminal_generated_authority(
    tmp_path: Path,
) -> None:
    path = tmp_path / "courses.db"
    _courses, course, source, repo = _setup(path)
    request = repo.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key="sql-fence",
        expected_course_write_epoch=course.write_epoch,
    )
    with sqlite3.connect(path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE flashcard_decks SET state='ready', ready_at=1 WHERE id=?",
                (request.deck_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO flashcards
                   (id,deck_id,prompt,answer,objective_ids_json,citation_json,ordinal,
                    revision,state,created_at,updated_at,archived_at)
                   VALUES ('crd_forged',?,'p','a','[]','[]',1,1,'active',1,1,NULL)""",
                (request.deck_id,),
            )
    _complete(repo, course, source, request)
    with sqlite3.connect(path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE flashcard_generation_operations SET error_code='provider_failed' WHERE id=?",
                (request.operation.id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE flashcard_generation_operations SET updated_at=updated_at+1 WHERE id=?",
                (request.operation.id,),
            )


def test_source_change_during_resolution_is_fenced_before_provider_call(
    tmp_path: Path,
) -> None:
    courses, course, source, repository = _setup(tmp_path / "courses.db")
    request = repository.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key="pre-call-source-race",
        expected_course_write_epoch=course.write_epoch,
    )

    class RacingResolver:
        def resolve(
            self,
            *,
            owner_user_id,
            course_id,
            receipts,
            context_char_limit,
        ):
            del owner_user_id, course_id, context_char_limit
            with courses._write_lock, courses._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE course_sources SET revision=revision+1 WHERE id=?",
                    (source.id,),
                )
            from deeptutor.courses.flashcard_generation_models import (
                FlashcardGenerationSourceText,
            )

            return [
                FlashcardGenerationSourceText(receipt=receipt, text="ATP stores energy.")
                for receipt in receipts
            ]

    class CountingProvider:
        calls = 0

        def generate(self, _request):
            self.calls += 1
            return _output(source)

    provider = CountingProvider()
    service = CourseFlashcardGenerationService(
        repository,
        provider=provider,
        source_text_resolver=RacingResolver(),
        account_active=lambda _owner: True,
        identity_lock=lambda: nullcontext(),
    )

    result = service.run_operation(course.id, request.operation.id)

    assert result.state == "failed"
    assert result.error_code == "source_changed"
    assert provider.calls == 0


@pytest.mark.parametrize("race", ["account_revoked", "cancelled"])
def test_final_preflight_blocks_revocation_and_cancellation_before_provider(
    tmp_path: Path, race: str
) -> None:
    courses, course, source, repository = _setup(tmp_path / f"{race}.db")
    request = repository.create_generated_deck(
        course.id,
        title="Terms",
        source_ids=[source.id],
        idempotency_key=f"pre-call-{race}",
        expected_course_write_epoch=course.write_epoch,
    )
    authority = {"active": True}

    class RacingResolver:
        def resolve(self, *, receipts, **_kwargs):
            if race == "account_revoked":
                authority["active"] = False
            else:
                assert (
                    repository.cancel_operation(course.id, request.operation.id).state
                    == "cancelled"
                )
            from deeptutor.courses.flashcard_generation_models import (
                FlashcardGenerationSourceText,
            )

            return [
                FlashcardGenerationSourceText(receipt=receipt, text="ATP stores energy.")
                for receipt in receipts
            ]

    class CountingProvider:
        calls = 0

        def generate(self, _request):
            self.calls += 1
            return _output(source)

    provider = CountingProvider()
    service = CourseFlashcardGenerationService(
        repository,
        provider=provider,
        source_text_resolver=RacingResolver(),
        account_active=lambda _owner: authority["active"],
        identity_lock=lambda: nullcontext(),
    )

    result = service.run_operation(course.id, request.operation.id)

    assert provider.calls == 0
    assert result.state == ("failed" if race == "account_revoked" else "cancelled")


def test_cancel_archives_unpublished_draft_and_running_cancel_wins(
    tmp_path: Path,
) -> None:
    path = tmp_path / "courses.db"
    courses, course, source, repo = _setup(path)
    queued = repo.create_generated_deck(
        course.id,
        title="Queued",
        source_ids=[source.id],
        idempotency_key="cancel-queued",
        expected_course_write_epoch=course.write_epoch,
    )
    assert repo.cancel_operation(course.id, queued.operation.id).state == "cancelled"

    pre_admission = repo.create_generated_deck(
        course.id,
        title="Pre-admission",
        source_ids=[source.id],
        idempotency_key="cancel-running",
        expected_course_write_epoch=course.write_epoch,
    )
    repo.claim_operation(course.id, pre_admission.operation.id)
    assert repo.cancel_operation(course.id, pre_admission.operation.id).state == "cancelled"

    admitted = repo.create_generated_deck(
        course.id,
        title="Provider admitted",
        source_ids=[source.id],
        idempotency_key="cancel-admitted",
        expected_course_write_epoch=course.write_epoch,
    )
    repo.claim_operation(course.id, admitted.operation.id)
    invoked = repo.preflight_provider_call(course.id, admitted.operation.id, account_active=True)
    assert invoked.provider_invoked_at is not None
    assert repo.cancel_operation(course.id, admitted.operation.id).state == "cancelling"
    cancelled = repo.fail_operation(course.id, admitted.operation.id, "provider_failed")
    assert cancelled.state == "cancelled"
    assert cancelled.error_code == "cancelled"

    with sqlite3.connect(path) as conn:
        assert {
            row[0]
            for row in conn.execute(
                "SELECT state FROM flashcard_decks WHERE id IN (?,?)",
                (queued.deck_id, pre_admission.deck_id),
            ).fetchall()
        } == {"archived"}
        assert (
            conn.execute(
                "SELECT state FROM flashcard_decks WHERE id=?", (admitted.deck_id,)
            ).fetchone()[0]
            == "archived"
        )


def test_cancel_after_provider_admission_is_truthful_and_discards_output(
    tmp_path: Path,
) -> None:
    courses, course, source, repository = _setup(tmp_path / "courses.db")
    request = repository.create_generated_deck(
        course.id,
        title="Admitted race",
        source_ids=[source.id],
        idempotency_key="cancel-after-admission",
        expected_course_write_epoch=course.write_epoch,
    )

    class Resolver:
        def resolve(self, *, receipts, **_kwargs):
            from deeptutor.courses.flashcard_generation_models import (
                FlashcardGenerationSourceText,
            )

            return [
                FlashcardGenerationSourceText(receipt=receipt, text="ATP stores energy.")
                for receipt in receipts
            ]

    class CancellingProvider:
        calls = 0

        def generate(self, _request):
            self.calls += 1
            assert (
                repository.cancel_operation(course.id, request.operation.id).state == "cancelling"
            )
            return _output(source)

    provider = CancellingProvider()
    service = CourseFlashcardGenerationService(
        repository,
        provider=provider,
        source_text_resolver=Resolver(),
        account_active=lambda _owner: True,
        identity_lock=lambda: nullcontext(),
    )

    result = service.run_operation(course.id, request.operation.id)

    assert provider.calls == 1
    assert result.state == "cancelled"
    assert result.error_code == "cancelled"
    assert result.provider_invoked_at is not None
    assert result.candidates is None
    with courses._connect() as connection:
        deck = connection.execute(
            "SELECT state FROM flashcard_decks WHERE id=?", (request.deck_id,)
        ).fetchone()
    assert deck is not None and deck["state"] == "archived"


def test_expired_candidate_review_is_cancelled_and_archived(tmp_path: Path, monkeypatch) -> None:
    from deeptutor.courses import flashcard_generation_repository as module

    path = tmp_path / "courses.db"
    _courses, course, source, repo = _setup(path)
    request = repo.create_generated_deck(
        course.id,
        title="Expires",
        source_ids=[source.id],
        idempotency_key="review-expiry",
        expected_course_write_epoch=course.write_epoch,
    )
    operation, claimed = repo.claim_operation(course.id, request.operation.id)
    assert claimed
    base = 10_000_000_000.0
    monkeypatch.setattr(module.time, "time", lambda: base)
    staged = repo.stage_candidates(
        course.id,
        operation.id,
        _output(source),
        account_active=True,
        material_receipts=[
            FlashcardSourceReceipt(
                source_id=source.id,
                source_revision=source.revision,
                content_sha256=source.content_sha256,
            )
        ],
    )
    assert staged.state == "awaiting_review"
    monkeypatch.setattr(module.time, "time", lambda: base + 8 * 24 * 60 * 60)

    assert repo.expire_review_candidates(course.id) == 1
    assert repo.get_operation(course.id, operation.id).state == "cancelled"
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute(
                "SELECT state FROM flashcard_decks WHERE id=?", (request.deck_id,)
            ).fetchone()[0]
            == "archived"
        )


def test_course_archive_reconciles_expired_candidate_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from deeptutor.courses import flashcard_generation_repository as generation_module
    from deeptutor.courses import repository as course_module

    path = tmp_path / "courses.db"
    courses, course, source, repo = _setup(path)
    request = repo.create_generated_deck(
        course.id,
        title="Expired before archive",
        source_ids=[source.id],
        idempotency_key="archive-expired-review",
        expected_course_write_epoch=course.write_epoch,
    )
    operation, claimed = repo.claim_operation(course.id, request.operation.id)
    assert claimed
    base = 10_000_000_000.0
    monkeypatch.setattr(generation_module.time, "time", lambda: base)
    staged = repo.stage_candidates(
        course.id,
        operation.id,
        _output(source),
        account_active=True,
        material_receipts=[
            FlashcardSourceReceipt(
                source_id=source.id,
                source_revision=source.revision,
                content_sha256=source.content_sha256,
            )
        ],
    )
    assert staged.state == "awaiting_review"
    monkeypatch.setattr(course_module.time, "time", lambda: base + 8 * 24 * 60 * 60)

    archived = courses.archive_course(
        course.id, expected_revision=courses.get_course(course.id).revision
    )

    assert archived.state == "archived"
    assert repo.get_operation(course.id, operation.id).state == "cancelled"


def test_unrequested_card_type_cannot_reach_candidate_review(
    tmp_path: Path,
) -> None:
    _courses, course, source, repo = _setup(tmp_path / "courses.db")
    request = repo.create_generated_deck(
        course.id,
        title="Definitions only",
        source_ids=[source.id],
        idempotency_key="card-type-fence",
        expected_course_write_epoch=course.write_epoch,
        generation_brief={
            "focus": "Definitions",
            "desired_count": 8,
            "card_type_mix": ["definition"],
            "difficulty": "mixed",
            "answer_length": "short",
            "include_hints": True,
        },
    )
    operation, claimed = repo.claim_operation(course.id, request.operation.id)
    assert claimed
    output = _output(source)
    output.cards[0].card_type = "application"

    with pytest.raises(ValueError, match="card type"):
        repo.stage_candidates(
            course.id,
            operation.id,
            output,
            account_active=True,
            material_receipts=[
                FlashcardSourceReceipt(
                    source_id=source.id,
                    source_revision=source.revision,
                    content_sha256=source.content_sha256,
                )
            ],
        )


def test_semantic_validation_filters_duplicates_and_answer_leakage(
    tmp_path: Path,
) -> None:
    _courses, course, source, repo = _setup(tmp_path / "courses.db")
    request = repo.create_generated_deck(
        course.id,
        title="Validated",
        source_ids=[source.id],
        idempotency_key="semantic-validation",
        expected_course_write_epoch=course.write_epoch,
        item_limit=5,
    )
    operation, claimed = repo.claim_operation(course.id, request.operation.id)
    assert claimed
    receipt = FlashcardSourceReceipt(
        source_id=source.id,
        source_revision=source.revision,
        content_sha256=source.content_sha256,
    )
    cards = [
        GeneratedFlashcard(
            prompt=f"Distinct grounded prompt {index}?",
            answer=f"Grounded answer {index}",
            citations=[FlashcardCitation(**receipt.model_dump())],
        )
        for index in range(3)
    ]
    cards.extend(
        [
            cards[0].model_copy(),
            GeneratedFlashcard(
                prompt="The leaked answer is visible here",
                answer="leaked answer",
                citations=[FlashcardCitation(**receipt.model_dump())],
            ),
        ]
    )
    staged = repo.stage_candidates(
        course.id,
        operation.id,
        GeneratedFlashcardOutput(provider_label="deterministic-local", cards=cards),
        account_active=True,
        material_receipts=[receipt],
    )
    assert staged.candidates is not None
    assert len(staged.candidates) == 3
    assert staged.provider_receipt is not None
    assert staged.provider_receipt.returned_count == 5
    assert staged.provider_receipt.valid_count == 3
    assert staged.provider_receipt.store is False


def test_semantic_validation_fails_when_too_few_candidates_survive(
    tmp_path: Path,
) -> None:
    _courses, course, source, repo = _setup(tmp_path / "courses.db")
    request = repo.create_generated_deck(
        course.id,
        title="Too few",
        source_ids=[source.id],
        idempotency_key="too-few-valid",
        expected_course_write_epoch=course.write_epoch,
        item_limit=5,
    )
    operation, _claimed = repo.claim_operation(course.id, request.operation.id)
    receipt = FlashcardSourceReceipt(
        source_id=source.id,
        source_revision=source.revision,
        content_sha256=source.content_sha256,
    )
    duplicate = GeneratedFlashcard(
        prompt="Same prompt",
        answer="Useful answer",
        citations=[FlashcardCitation(**receipt.model_dump())],
    )
    with pytest.raises(FlashcardGenerationInsufficientCandidates):
        repo.stage_candidates(
            course.id,
            operation.id,
            GeneratedFlashcardOutput(
                provider_label="deterministic-local",
                cards=[duplicate.model_copy() for _ in range(5)],
            ),
            account_active=True,
            material_receipts=[receipt],
        )
