"""Shared owner-wide admission limits for durable generated learning assets.

The limits intentionally count durable rows, rather than process-local worker
markers.  Both generation repositories hold ``BEGIN IMMEDIATE`` while calling
this module, making the decision atomic across Practice and Flashcard requests
that share an owner's Course database.
"""

from __future__ import annotations

import sqlite3

from .repository import CourseConflictError

# These are deliberately modest local-beta ceilings.  Terminal operations and
# failed drafts are retained for learner-visible history; allocation stops at a
# ceiling instead of deleting that history behind the learner's back.
MAX_OUTSTANDING_GENERATION_OPERATIONS_PER_OWNER = 4
MAX_RETAINED_GENERATION_OPERATIONS_PER_OWNER = 64
MAX_RETAINED_GENERATION_DRAFTS_PER_OWNER = 16


def _count_operations(
    conn: sqlite3.Connection, owner_user_id: str, *, states: tuple[str, ...] | None
) -> int:
    condition = ""
    params: list[object] = [owner_user_id, owner_user_id]
    if states is not None:
        placeholders = ", ".join("?" for _ in states)
        condition = f" AND state IN ({placeholders})"
        params = [owner_user_id, *states, owner_user_id, *states]
    row = conn.execute(
        f"""SELECT COUNT(*) FROM (
                SELECT 1 FROM practice_generation_operations
                WHERE owner_user_id = ?{condition}
                UNION ALL
                SELECT 1 FROM flashcard_generation_operations
                WHERE owner_user_id = ?{condition}
            )""",
        params,
    ).fetchone()
    assert row is not None
    return int(row[0])


def _count_generated_drafts(conn: sqlite3.Connection, owner_user_id: str) -> int:
    row = conn.execute(
        """SELECT COUNT(*) FROM (
                SELECT 1 FROM practice_set_revisions AS revisions
                JOIN practice_sets AS sets ON sets.id = revisions.practice_set_id
                WHERE sets.owner_user_id = ? AND sets.mode = 'generated'
                  AND revisions.state = 'draft'
                UNION ALL
                SELECT 1 FROM flashcard_decks
                WHERE owner_user_id = ? AND mode = 'generated' AND state = 'draft'
            )""",
        (owner_user_id, owner_user_id),
    ).fetchone()
    assert row is not None
    return int(row[0])


def admit_generation_allocation(conn: sqlite3.Connection, owner_user_id: str) -> None:
    """Reject a new allocation before it creates any durable draft rows.

    Exact idempotency replays must be resolved by the caller before this check.
    That preserves their original operation even after a later request reaches a
    budget ceiling.
    """

    if _count_operations(
        conn,
        owner_user_id,
        states=("queued", "running", "cancelling", "awaiting_review"),
    ) >= (
        MAX_OUTSTANDING_GENERATION_OPERATIONS_PER_OWNER
    ):
        raise CourseConflictError("Generation outstanding-operation limit reached")
    if _count_operations(conn, owner_user_id, states=None) >= (
        MAX_RETAINED_GENERATION_OPERATIONS_PER_OWNER
    ):
        raise CourseConflictError("Generation retained-operation limit reached")
    if _count_generated_drafts(conn, owner_user_id) >= MAX_RETAINED_GENERATION_DRAFTS_PER_OWNER:
        raise CourseConflictError("Generation retained-draft limit reached")
