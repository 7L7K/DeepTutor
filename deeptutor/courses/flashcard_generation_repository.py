"""Durable owner-scoped authority for grounded generated Flashcard decks."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any, Iterable
from uuid import uuid4

from .flashcard_generation_models import (
    FlashcardGenerationOperation,
    FlashcardGenerationRequest,
    FlashcardSourceReceipt,
    GeneratedFlashcardOutput,
)
from .repository import CourseConflictError, CourseNotFoundError, CourseRepository


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
    ) -> FlashcardGenerationRequest:
        title, source_ids, objectives = (
            self._clean(title, "Deck title", 160),
            self._source_ids(source_ids),
            self._objectives(objective_ids),
        )
        idempotency_key = self._clean(idempotency_key, "Idempotency key", 160)
        if (
            not isinstance(item_limit, int)
            or not 1 <= item_limit <= 48
            or not isinstance(context_char_limit, int)
            or not 1 <= context_char_limit <= 48_000
        ):
            raise ValueError("generation limits are invalid")
        deck_id, operation_id, now = _id("dck"), _id("ofg"), time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._course_for_write(conn, course_id, expected_course_write_epoch)
            # A source identity includes revision and content fingerprint, not
            # merely a caller-provided opaque ID. Re-snapshot before replay.
            snapshot = self._snapshot(conn, course_id, source_ids)
            fingerprint = self._fingerprint(
                title=title,
                source_snapshot=snapshot,
                objective_ids=objectives,
                item_limit=item_limit,
                context_char_limit=context_char_limit,
                supersedes_deck_id=supersedes_deck_id,
            )
            prior = conn.execute(
                "SELECT * FROM flashcard_generation_operations WHERE course_id=? AND idempotency_key=?",
                (course_id, idempotency_key),
            ).fetchone()
            if prior:
                operation = self._operation(prior)
                if operation.request_fingerprint != fingerprint:
                    raise CourseConflictError(
                        "Idempotency key was already used for another generation request"
                    )
                return FlashcardGenerationRequest(deck_id=operation.deck_id, operation=operation)
            if supersedes_deck_id:
                old = self._owned_deck(conn, course_id, supersedes_deck_id)
                if old["mode"] != "generated" or old["state"] != "ready":
                    raise CourseConflictError("Flashcard generation successor authority is stale")
            snapshot_json, objectives_json = (
                self._json([item.model_dump() for item in snapshot]),
                self._json(objectives),
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
                """INSERT INTO flashcard_generation_operations (id,owner_user_id,course_id,deck_id,supersedes_deck_id,idempotency_key,request_fingerprint,source_snapshot_json,objective_ids_json,course_write_epoch,deck_write_epoch,item_limit,context_char_limit,state,error_code,created_at,started_at,completed_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?,'queued',NULL,?,NULL,NULL,?)""",
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

    def complete_operation(
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
            if operation.state == "completed":
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
            encoded = self._json(output.model_dump()).encode()
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
                if any(
                    (c.source_id, c.source_revision, c.content_sha256) not in snapshot
                    or (c.source_id, c.source_revision, c.content_sha256) not in material
                    for c in card.citations
                ):
                    raise ValueError("Generated citation is invalid")
            card_ids: list[str] = []
            for ordinal, card in enumerate(output.cards, 1):
                card_id = _id("crd")
                card_ids.append(card_id)
                conn.execute(
                    "INSERT INTO flashcards (id,deck_id,prompt,answer,objective_ids_json,citation_json,ordinal,revision,state,created_at,updated_at,archived_at) VALUES (?,?,?,?,?,?,?,1,'active',?,?,NULL)",
                    (
                        card_id,
                        operation.deck_id,
                        card.prompt,
                        card.answer,
                        self._json(card.objective_ids),
                        self._json([c.model_dump() for c in card.citations]),
                        ordinal,
                        now,
                        now,
                    ),
                )
            conn.execute(
                "UPDATE flashcard_decks SET state='ready',revision=revision+1,write_epoch=write_epoch+1,ready_at=?,updated_at=? WHERE id=? AND state='draft'",
                (now, now, operation.deck_id),
            )
            for card_id in card_ids:
                conn.execute(
                    """INSERT INTO flashcard_review_states
                       (card_id, owner_user_id, course_id, deck_id, review_count,
                        interval_seconds, next_review_at, last_review_id, updated_at)
                       VALUES (?, ?, ?, ?, 0, 0, ?, NULL, ?)""",
                    (card_id, self.owner_user_id, course_id, operation.deck_id, now, now),
                )
            conn.execute(
                "UPDATE flashcard_generation_operations SET state='completed',completed_at=?,updated_at=? WHERE id=? AND state='running'",
                (now, now, operation_id),
            )
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
        }:
            raise ValueError("invalid generation failure code")
        now = time.time()
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            operation = self._operation(self._owned_op(conn, course_id, operation_id))
            if operation.state in {"completed", "failed"}:
                return operation
            conn.execute(
                "UPDATE flashcard_generation_operations SET state='failed',error_code=?,completed_at=?,updated_at=? WHERE id=?",
                (code, now, now, operation_id),
            )
            return self._operation(self._owned_op(conn, course_id, operation_id))

    def reconcile_orphaned_operations(self, course_id: str, *, live_operation_ids: set[str]) -> int:
        with self.course_repository._write_lock, self.course_repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT id FROM flashcard_generation_operations WHERE course_id=? AND owner_user_id=? AND state IN ('queued','running')",
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
