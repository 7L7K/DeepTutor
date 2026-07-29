"""Durable owner-scoped authority for grounded generated Flashcard decks."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from typing import Any, Iterable
from uuid import uuid4

from .flashcard_generation_models import (
    FlashcardCandidate,
    FlashcardCandidatePublication,
    FlashcardGenerationBrief,
    FlashcardGenerationBriefReceipt,
    FlashcardGenerationOperation,
    FlashcardGenerationOrigin,
    FlashcardGenerationRequest,
    FlashcardProviderReceipt,
    FlashcardSourceReceipt,
    GeneratedFlashcard,
    GeneratedFlashcardOutput,
)
from .generation_governance import admit_generation_allocation
from .repository import CourseConflictError, CourseNotFoundError, CourseRepository


class FlashcardGenerationInsufficientCandidates(ValueError):
    pass


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class CourseFlashcardGenerationRepository:
    def __init__(self, course_repository: CourseRepository) -> None:
        self.course_repository = course_repository

    @property
    def owner_user_id(self) -> str:
        return self.course_repository.owner_user_id

    @staticmethod
    def _not_found() -> CourseNotFoundError:
        return CourseNotFoundError("Flashcard generation resource not found")

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    @staticmethod
    def _clean(value: str, field: str, maximum: int) -> str:
        result = " ".join(str(value or "").split())
        if not result:
            raise ValueError(f"{field} is required")
        if len(result) > maximum:
            raise ValueError(f"{field} must be {maximum} characters or fewer")
        return result

    def _source_ids(self, values: Iterable[str]) -> list[str]:
        if isinstance(values, (str, bytes)):
            raise ValueError("source_ids must be a list")
        values = list(values)
        if not values or len(values) > 64 or len(values) != len(set(values)):
            raise ValueError("source_ids must contain between one and 64 unique opaque IDs")
        if any(
            not isinstance(item, str) or not item.startswith("src_") or len(item) > 80
            for item in values
        ):
            raise ValueError("source_ids must be opaque Course source IDs")
        return values

    def _objectives(self, values: Iterable[str]) -> list[str]:
        if isinstance(values, (str, bytes)):
            raise ValueError("objective_ids must be a list")
        result = [self._clean(item, "Objective ID", 160) for item in values]
        if len(result) > 64 or len(result) != len(set(result)):
            raise ValueError("objective_ids must be unique and bounded")
        return result

    def _course_for_write(self, conn: sqlite3.Connection, course_id: str, epoch: int) -> None:
        row = conn.execute(
            "SELECT state, write_epoch FROM courses WHERE id=? AND owner_user_id=?",
            (course_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        if row["state"] != "active" or int(row["write_epoch"]) != epoch:
            raise CourseConflictError("Course authority is stale or archived")

    def _snapshot(
        self, conn: sqlite3.Connection, course_id: str, source_ids: list[str]
    ) -> list[FlashcardSourceReceipt]:
        rows = conn.execute(
            f"SELECT id, revision, content_sha256, state FROM course_sources WHERE course_id=? AND id IN ({','.join('?' for _ in source_ids)})",
            [course_id, *source_ids],
        ).fetchall()
        by_id = {str(row["id"]): row for row in rows}
        if len(by_id) != len(source_ids) or any(
            by_id[item]["state"] != "ready" for item in source_ids
        ):
            raise self._not_found()
        return [
            FlashcardSourceReceipt(
                source_id=item,
                source_revision=int(by_id[item]["revision"]),
                content_sha256=str(by_id[item]["content_sha256"]),
            )
            for item in source_ids
        ]

    def _verify_snapshot(
        self, conn: sqlite3.Connection, course_id: str, snapshot: list[FlashcardSourceReceipt]
    ) -> None:
        actual = self._snapshot(conn, course_id, [item.source_id for item in snapshot])
        if [item.model_dump() for item in actual] != [item.model_dump() for item in snapshot]:
            raise CourseConflictError("Course sources changed during generation")

    @staticmethod
    def _operation(row: sqlite3.Row) -> FlashcardGenerationOperation:
        data = dict(row)
        data["source_snapshot"] = json.loads(data.pop("source_snapshot_json"))
        data["objective_ids"] = json.loads(data.pop("objective_ids_json"))
        data["generation_brief"] = json.loads(data.pop("generation_brief_json"))
        data["origin"] = json.loads(data.pop("origin_json"))
        candidates = data.pop("candidate_output_json")
        data["candidates"] = json.loads(candidates) if candidates else None
        provider_receipt = data.pop("provider_receipt_json")
        data["provider_receipt"] = (
            json.loads(provider_receipt) if provider_receipt else None
        )
        return FlashcardGenerationOperation.model_validate(data)

    def _owned_op(self, conn: sqlite3.Connection, course_id: str, operation_id: str) -> sqlite3.Row:
        row = conn.execute(
            """SELECT o.* FROM flashcard_generation_operations o JOIN courses c ON c.id=o.course_id
            WHERE o.id=? AND o.course_id=? AND o.owner_user_id=? AND c.owner_user_id=?""",
            (operation_id, course_id, self.owner_user_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        return row

    def _owned_deck(self, conn: sqlite3.Connection, course_id: str, deck_id: str) -> sqlite3.Row:
        row = conn.execute(
            """SELECT d.* FROM flashcard_decks d JOIN courses c ON c.id=d.course_id
            WHERE d.id=? AND d.course_id=? AND d.owner_user_id=? AND c.owner_user_id=?""",
            (deck_id, course_id, self.owner_user_id, self.owner_user_id),
        ).fetchone()
        if row is None:
            raise self._not_found()
        return row

    def _fingerprint(
        self,
        *,
        title: str,
        source_snapshot: list[FlashcardSourceReceipt],
        objective_ids: list[str],
        item_limit: int,
        context_char_limit: int,
        supersedes_deck_id: str | None,
        generation_brief: FlashcardGenerationBrief,
        origin: FlashcardGenerationOrigin,
    ) -> str:
        return hashlib.sha256(
            self._json(
                {
                    "title": title,
                    "source_snapshot": [item.model_dump() for item in source_snapshot],
                    "objective_ids": objective_ids,
                    "item_limit": item_limit,
                    "context_char_limit": context_char_limit,
                    "supersedes_deck_id": supersedes_deck_id,
                    "generation_brief": generation_brief.model_dump(mode="json"),
                    "origin": origin.model_dump(mode="json"),
                }
            ).encode()
        ).hexdigest()

    def create_generated_deck(
        self,
        course_id: str,
        *,
        title: str,
        source_ids: Iterable[str],
        objective_ids: Iterable[str] = (),
        idempotency_key: str,
        expected_course_write_epoch: int,
        item_limit: int = 8,
        context_char_limit: int = 24_000,
        supersedes_deck_id: str | None = None,
        provider_available: bool = True,
        generation_brief: FlashcardGenerationBrief | dict[str, Any] | None = None,
        origin: FlashcardGenerationOrigin | dict[str, Any] | None = None,
    ) -> FlashcardGenerationRequest:
        title, source_ids, objectives = (
            self._clean(title, "Deck title", 160),
            self._source_ids(source_ids),
            self._objectives(objective_ids),
        )
        idempotency_key = self._clean(idempotency_key, "Idempotency key", 160)
        if (
            not isinstance(item_limit, int)
            or not 3 <= item_limit <= 48
            or not isinstance(context_char_limit, int)
            or not 1 <= context_char_limit <= 48_000
        ):
            raise ValueError("generation limits are invalid")
        brief = FlashcardGenerationBrief.model_validate(
            generation_brief
            or {
                "focus": title,
                "desired_count": item_limit,
                "card_type_mix": ["recall"],
                "difficulty": "mixed",
                "answer_length": "short",
                "include_hints": True,
            }
        )
        if brief.desired_count != item_limit:
            raise ValueError("generation brief count must match item_limit")
        generation_origin = FlashcardGenerationOrigin.model_validate(
            origin or {"kind": "workspace"}
        )
        deck_id, operation_id, now = _id("dck"), _id("ofg"), time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            prior = conn.execute(
                "SELECT * FROM flashcard_generation_operations WHERE course_id=? AND idempotency_key=?",
                (course_id, idempotency_key),
            ).fetchone()
            if prior:
                # A replay is exact only while the caller's source IDs still
                # resolve to the same immutable revision/fingerprint snapshot.
                snapshot = self._snapshot(conn, course_id, source_ids)
                fingerprint = self._fingerprint(
                    title=title,
                    source_snapshot=snapshot,
                    objective_ids=objectives,
                    item_limit=item_limit,
                    context_char_limit=context_char_limit,
                    supersedes_deck_id=supersedes_deck_id,
                    generation_brief=brief,
                    origin=generation_origin,
                )
                operation = self._operation(prior)
                if operation.request_fingerprint != fingerprint:
                    raise CourseConflictError(
                        "Idempotency key was already used for another generation request"
                    )
                return FlashcardGenerationRequest(deck_id=operation.deck_id, operation=operation)
            if not provider_available:
                raise CourseConflictError("Generation provider is unavailable")
            snapshot = self._snapshot(conn, course_id, source_ids)
            fingerprint = self._fingerprint(
                title=title,
                source_snapshot=snapshot,
                objective_ids=objectives,
                item_limit=item_limit,
                context_char_limit=context_char_limit,
                supersedes_deck_id=supersedes_deck_id,
                generation_brief=brief,
                origin=generation_origin,
            )
            if supersedes_deck_id:
                old = self._owned_deck(conn, course_id, supersedes_deck_id)
                if old["mode"] != "generated" or old["state"] != "ready":
                    raise CourseConflictError("Flashcard generation successor authority is stale")
            admit_generation_allocation(conn, self.owner_user_id)
            snapshot_json, objectives_json, brief_json, origin_json = (
                self._json([item.model_dump() for item in snapshot]),
                self._json(objectives),
                self._json(brief.model_dump(mode="json")),
                self._json(generation_origin.model_dump(mode="json")),
            )
            receipt = self._json(
                {
                    "operation_id": operation_id,
                    "source_count": len(snapshot),
                    "item_limit": item_limit,
                }
            )
            conn.execute(
                """INSERT INTO flashcard_decks (id,owner_user_id,course_id,title,mode,state,source_snapshot_json,generation_receipt_json,revision,write_epoch,created_at,updated_at,ready_at,archived_at,supersedes_deck_id)
                VALUES (?,?,?,?,'generated','draft',?,?,1,1,?,?,NULL,NULL,?)""",
                (
                    deck_id,
                    self.owner_user_id,
                    course_id,
                    title,
                    snapshot_json,
                    receipt,
                    now,
                    now,
                    supersedes_deck_id,
                ),
            )
            conn.execute(
                """INSERT INTO flashcard_generation_operations
                (id,owner_user_id,course_id,deck_id,supersedes_deck_id,
                 idempotency_key,request_fingerprint,source_snapshot_json,
                 objective_ids_json,generation_brief_json,origin_json,
                 candidate_output_json,candidate_revision,provider_receipt_json,
                 cancel_requested_at,review_expires_at,course_write_epoch,
                 deck_write_epoch,item_limit,context_char_limit,state,error_code,
                 created_at,started_at,completed_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,0,NULL,NULL,NULL,?,1,?,?,
                        'queued',NULL,?,NULL,NULL,?)""",
                (
                    operation_id,
                    self.owner_user_id,
                    course_id,
                    deck_id,
                    supersedes_deck_id,
                    idempotency_key,
                    fingerprint,
                    snapshot_json,
                    objectives_json,
                    brief_json,
                    origin_json,
                    expected_course_write_epoch,
                    item_limit,
                    context_char_limit,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM flashcard_generation_operations WHERE id=?", (operation_id,)
            ).fetchone()
        assert row is not None
        return FlashcardGenerationRequest(deck_id=deck_id, operation=self._operation(row))

    def prepare_brief(
        self,
        course_id: str,
        *,
        focus: str,
        source_ids: Iterable[str],
        objective_ids: Iterable[str],
        expected_course_write_epoch: int,
        item_limit: int,
        card_type_mix: list[str],
        difficulty: str,
        answer_length: str,
        include_hints: bool,
        origin: FlashcardGenerationOrigin | dict[str, Any] | None,
        provider_available: bool,
    ) -> FlashcardGenerationBriefReceipt:
        sources = self._source_ids(source_ids)
        objectives = self._objectives(objective_ids)
        brief = FlashcardGenerationBrief.model_validate(
            {
                "focus": focus,
                "desired_count": item_limit,
                "card_type_mix": card_type_mix,
                "difficulty": difficulty,
                "answer_length": answer_length,
                "include_hints": include_hints,
            }
        )
        generation_origin = FlashcardGenerationOrigin.model_validate(
            origin or {"kind": "workspace"}
        )
        with self.course_repository._connect() as conn:
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            snapshot = self._snapshot(conn, course_id, sources)
        warnings = [] if provider_available else ["provider_unavailable"]
        return FlashcardGenerationBriefReceipt(
            course_id=course_id,
            course_write_epoch=expected_course_write_epoch,
            brief=brief,
            source_snapshot=snapshot,
            objective_ids=objectives,
            origin=generation_origin,
            provider_available=provider_available,
            warnings=warnings,
        )

    def get_operation(self, course_id: str, operation_id: str) -> FlashcardGenerationOperation:
        with self.course_repository._connect() as conn:
            return self._operation(self._owned_op(conn, course_id, operation_id))

    def list_operations(self, course_id: str) -> list[FlashcardGenerationOperation]:
        self.course_repository.get_course(course_id)
        with self.course_repository._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM flashcard_generation_operations WHERE course_id=? AND owner_user_id=? ORDER BY updated_at DESC,id",
                (course_id, self.owner_user_id),
            ).fetchall()
        return [self._operation(row) for row in rows]

    def claim_operation(
        self, course_id: str, operation_id: str
    ) -> tuple[FlashcardGenerationOperation, bool]:
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            operation = self._operation(self._owned_op(conn, course_id, operation_id))
            if operation.state != "queued":
                return operation, False
            conn.execute(
                "UPDATE flashcard_generation_operations SET state='running',started_at=?,updated_at=? WHERE id=? AND state='queued'",
                (now, now, operation_id),
            )
            return self._operation(self._owned_op(conn, course_id, operation_id)), True

    def preflight_provider_call(
        self,
        course_id: str,
        operation_id: str,
        *,
        account_active: bool,
    ) -> FlashcardGenerationOperation:
        """Re-resolve every durable authority immediately before provider use."""

        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            operation = self._operation(self._owned_op(conn, course_id, operation_id))
            if not account_active or operation.state != "running":
                raise CourseConflictError("Generation authority is stale")
            self._course_for_write(conn, course_id, operation.course_write_epoch)
            deck = self._owned_deck(conn, course_id, operation.deck_id)
            if (
                deck["mode"] != "generated"
                or deck["state"] != "draft"
                or int(deck["write_epoch"]) != operation.deck_write_epoch
                or json.loads(deck["source_snapshot_json"])
                != [item.model_dump() for item in operation.source_snapshot]
            ):
                raise CourseConflictError("Flashcard generation authority is stale")
            self._verify_snapshot(conn, course_id, operation.source_snapshot)
            now = time.time()
            conn.execute(
                """UPDATE flashcard_generation_operations
                   SET provider_invoked_at=?,updated_at=?
                   WHERE id=? AND state='running' AND provider_invoked_at IS NULL""",
                (now, now, operation_id),
            )
            return self._operation(self._owned_op(conn, course_id, operation_id))

    def stage_candidates(
        self,
        course_id: str,
        operation_id: str,
        output: GeneratedFlashcardOutput,
        *,
        account_active: bool,
        material_receipts: list[FlashcardSourceReceipt],
    ) -> FlashcardGenerationOperation:
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            operation = self._operation(self._owned_op(conn, course_id, operation_id))
            if operation.state == "awaiting_review":
                return operation
            if operation.state != "running" or not account_active:
                raise CourseConflictError("Generation authority is stale")
            self._course_for_write(conn, course_id, operation.course_write_epoch)
            deck = self._owned_deck(conn, course_id, operation.deck_id)
            if (
                deck["mode"] != "generated"
                or deck["state"] != "draft"
                or int(deck["write_epoch"]) != operation.deck_write_epoch
            ):
                raise CourseConflictError("Flashcard generation authority is stale")
            if json.loads(deck["source_snapshot_json"]) != [
                item.model_dump() for item in operation.source_snapshot
            ]:
                raise CourseConflictError("Flashcard generation authority is stale")
            self._verify_snapshot(conn, course_id, operation.source_snapshot)
            encoded = self._json(output.model_dump(mode="json")).encode()
            snapshot = {
                (x.source_id, x.source_revision, x.content_sha256)
                for x in operation.source_snapshot
            }
            material = {
                (x.source_id, x.source_revision, x.content_sha256) for x in material_receipts
            }
            if (
                len(encoded) > 48_000
                or not output.cards
                or len(output.cards) > operation.item_limit
                or not material
                or not material.issubset(snapshot)
            ):
                raise ValueError("Generated output is invalid")
            for card in output.cards:
                if any(item not in operation.objective_ids for item in card.objective_ids):
                    raise ValueError("Generated objective is invalid")
                if card.card_type not in operation.generation_brief.card_type_mix:
                    raise ValueError("Generated card type is invalid")
                if any(
                    (c.source_id, c.source_revision, c.content_sha256) not in snapshot
                    or (c.source_id, c.source_revision, c.content_sha256) not in material
                    for c in card.citations
                ):
                    raise ValueError("Generated citation is invalid")
            valid_cards: list[GeneratedFlashcard] = []
            seen_prompts: set[str] = set()
            meaningless_answers = {
                "n/a",
                "na",
                "none",
                "unknown",
                "not available",
                "no answer",
            }
            for card in output.cards:
                normalized_prompt = " ".join(card.prompt.casefold().split())
                normalized_answer = " ".join(card.answer.casefold().split())
                if (
                    normalized_prompt in seen_prompts
                    or normalized_answer in meaningless_answers
                    or (
                        len(normalized_answer) >= 4
                        and normalized_answer in normalized_prompt
                    )
                ):
                    continue
                seen_prompts.add(normalized_prompt)
                valid_cards.append(card)
            minimum_valid = max(3, math.ceil(operation.item_limit * 0.6))
            if len(valid_cards) < minimum_valid:
                raise FlashcardGenerationInsufficientCandidates(
                    "Generated output has insufficient valid cards"
                )
            candidates = [
                FlashcardCandidate(
                    candidate_id=_id("fcd"),
                    **card.model_dump(mode="json"),
                )
                for card in valid_cards
            ]
            provider_receipt = FlashcardProviderReceipt(
                provider=output.provider_label,
                requested_model=output.requested_model,
                actual_model=output.actual_model,
                request_id=output.request_id,
                input_tokens=output.input_tokens,
                cached_input_tokens=output.cached_input_tokens,
                output_tokens=output.output_tokens,
                reasoning_output_tokens=output.reasoning_output_tokens,
                estimated_cost_microusd=output.estimated_cost_microusd,
                response_status=output.response_status,
                service_tier=output.service_tier,
                prompt_version=output.prompt_version,
                store=output.store,
                latency_ms=output.latency_ms,
                returned_count=len(output.cards),
                valid_count=len(valid_cards),
                generated_at=output.generated_at,
            )
            expires = now + 7 * 24 * 60 * 60
            conn.execute(
                """UPDATE flashcard_generation_operations
                   SET state='awaiting_review',candidate_output_json=?,
                       candidate_revision=candidate_revision+1,
                       provider_receipt_json=?,review_expires_at=?,updated_at=?
                   WHERE id=? AND state='running'""",
                (
                    self._json([item.model_dump(mode="json") for item in candidates]),
                    self._json(provider_receipt.model_dump(mode="json")),
                    expires,
                    now,
                    operation_id,
                ),
            )
            return self._operation(self._owned_op(conn, course_id, operation_id))

    def publish_candidates(
        self,
        course_id: str,
        operation_id: str,
        publication: FlashcardCandidatePublication,
        *,
        account_active: bool,
    ) -> FlashcardGenerationOperation:
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            operation = self._operation(self._owned_op(conn, course_id, operation_id))
            if operation.state == "completed":
                return operation
            if (
                operation.state != "awaiting_review"
                or not account_active
                or operation.candidate_revision != publication.expected_candidate_revision
                or operation.review_expires_at is None
                or operation.review_expires_at <= now
                or not operation.candidates
            ):
                raise CourseConflictError("Candidate review authority is stale")
            self._course_for_write(conn, course_id, operation.course_write_epoch)
            deck = self._owned_deck(conn, course_id, operation.deck_id)
            if (
                deck["mode"] != "generated"
                or deck["state"] != "draft"
                or int(deck["write_epoch"]) != operation.deck_write_epoch
            ):
                raise CourseConflictError("Flashcard generation authority is stale")
            self._verify_snapshot(conn, course_id, operation.source_snapshot)
            by_id = {candidate.candidate_id: candidate for candidate in operation.candidates}
            if any(candidate_id not in by_id for candidate_id in publication.candidate_ids):
                raise self._not_found()
            card_ids: list[str] = []
            for ordinal, candidate_id in enumerate(publication.candidate_ids, 1):
                candidate = by_id[candidate_id]
                card_id = _id("crd")
                card_ids.append(card_id)
                conn.execute(
                    """INSERT INTO flashcards
                       (id,deck_id,prompt,answer,hint,card_type,objective_ids_json,
                        citation_json,ordinal,revision,state,created_at,updated_at,archived_at)
                       VALUES (?,?,?,?,?,?,?,?,?,1,'active',?,?,NULL)""",
                    (
                        card_id,
                        operation.deck_id,
                        candidate.prompt,
                        candidate.answer,
                        candidate.hint,
                        candidate.card_type,
                        self._json(candidate.objective_ids),
                        self._json(
                            [citation.model_dump(mode="json") for citation in candidate.citations]
                        ),
                        ordinal,
                        now,
                        now,
                    ),
                )
            conn.execute(
                """UPDATE flashcard_decks
                   SET state='ready',revision=revision+1,write_epoch=write_epoch+1,
                       ready_at=?,updated_at=?
                   WHERE id=? AND state='draft'""",
                (now, now, operation.deck_id),
            )
            for card_id in card_ids:
                conn.execute(
                    """INSERT INTO flashcard_review_states
                       (card_id,owner_user_id,course_id,deck_id,review_count,
                        interval_seconds,next_review_at,last_review_id,updated_at)
                       VALUES (?,?,?,?,0,0,?,NULL,?)""",
                    (
                        card_id,
                        self.owner_user_id,
                        course_id,
                        operation.deck_id,
                        now,
                        now,
                    ),
                )
            conn.execute(
                """UPDATE flashcard_generation_operations
                   SET state='completed',completed_at=?,updated_at=?
                   WHERE id=? AND state='awaiting_review'""",
                (now, now, operation_id),
            )
            return self._operation(self._owned_op(conn, course_id, operation_id))

    def cancel_operation(
        self, course_id: str, operation_id: str
    ) -> FlashcardGenerationOperation:
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            operation = self._operation(self._owned_op(conn, course_id, operation_id))
            if operation.state in {"completed", "failed", "cancelled"}:
                return operation
            target = (
                "cancelling"
                if operation.state == "running"
                and operation.provider_invoked_at is not None
                else "cancelled"
            )
            completed_at = None if target == "cancelling" else now
            error_code = None if target == "cancelling" else "cancelled"
            conn.execute(
                """UPDATE flashcard_generation_operations
                   SET state=?,error_code=?,cancel_requested_at=?,
                       completed_at=?,updated_at=? WHERE id=?""",
                (target, error_code, now, completed_at, now, operation_id),
            )
            if target == "cancelled":
                self._archive_draft_deck(conn, operation.deck_id, now)
            return self._operation(self._owned_op(conn, course_id, operation_id))

    @staticmethod
    def _archive_draft_deck(
        conn: sqlite3.Connection, deck_id: str, now: float
    ) -> None:
        conn.execute(
            """UPDATE flashcard_decks
               SET state='archived',revision=revision+1,
                   write_epoch=write_epoch+1,archived_at=?,updated_at=?
               WHERE id=? AND mode='generated' AND state='draft'""",
            (now, now, deck_id),
        )

    def finalize_cancellation(
        self, course_id: str, operation_id: str
    ) -> FlashcardGenerationOperation:
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            operation = self._operation(self._owned_op(conn, course_id, operation_id))
            if operation.state != "cancelling":
                return operation
            conn.execute(
                """UPDATE flashcard_generation_operations
                   SET state='cancelled',error_code='cancelled',
                       completed_at=?,updated_at=? WHERE id=?""",
                (now, now, operation_id),
            )
            self._archive_draft_deck(conn, operation.deck_id, now)
            return self._operation(self._owned_op(conn, course_id, operation_id))

    def fail_operation(
        self, course_id: str, operation_id: str, code: str
    ) -> FlashcardGenerationOperation:
        if code not in {
            "provider_unavailable",
            "provider_failed",
            "invalid_output",
            "source_changed",
            "authority_changed",
            "interrupted",
            "provider_timed_out",
            "configuration_error",
            "quota_exceeded",
            "insufficient_valid_cards",
        }:
            raise ValueError("invalid generation failure code")
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            operation = self._operation(self._owned_op(conn, course_id, operation_id))
            if operation.state in {"completed", "failed", "cancelled"}:
                return operation
            if operation.state == "cancelling":
                conn.execute(
                    """UPDATE flashcard_generation_operations
                       SET state='cancelled',error_code='cancelled',
                           completed_at=?,updated_at=? WHERE id=?""",
                    (now, now, operation_id),
                )
                self._archive_draft_deck(conn, operation.deck_id, now)
                return self._operation(
                    self._owned_op(conn, course_id, operation_id)
                )
            if operation.state == "awaiting_review":
                raise CourseConflictError("Reviewed candidates cannot fail retroactively")
            conn.execute(
                "UPDATE flashcard_generation_operations SET state='failed',error_code=?,completed_at=?,updated_at=? WHERE id=?",
                (code, now, now, operation_id),
            )
            return self._operation(self._owned_op(conn, course_id, operation_id))

    def expire_review_candidates(self, course_id: str) -> int:
        """Cancel expired review queues and archive their unpublished drafts."""

        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """SELECT id,deck_id FROM flashcard_generation_operations
                   WHERE course_id=? AND owner_user_id=?
                     AND state='awaiting_review'
                     AND review_expires_at IS NOT NULL
                     AND review_expires_at<=?""",
                (course_id, self.owner_user_id, now),
            ).fetchall()
            for row in rows:
                self._archive_draft_deck(conn, str(row["deck_id"]), now)
                conn.execute(
                    """UPDATE flashcard_generation_operations
                       SET state='cancelled',error_code='cancelled',
                           cancel_requested_at=?,completed_at=?,updated_at=?
                       WHERE id=? AND state='awaiting_review'""",
                    (now, now, now, str(row["id"])),
                )
            return len(rows)

    def reconcile_orphaned_operations(self, course_id: str, *, live_operation_ids: set[str]) -> int:
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """SELECT id FROM flashcard_generation_operations
                   WHERE course_id=? AND owner_user_id=?
                     AND state IN ('queued','running','cancelling')""",
                (course_id, self.owner_user_id),
            ).fetchall()
            lost = [str(row["id"]) for row in rows if str(row["id"]) not in live_operation_ids]
            if lost:
                now = time.time()
                conn.execute(
                    f"UPDATE flashcard_generation_operations SET state='failed',error_code='interrupted',completed_at=?,updated_at=? WHERE id IN ({','.join('?' for _ in lost)})",
                    [now, now, *lost],
                )
            return len(lost)
