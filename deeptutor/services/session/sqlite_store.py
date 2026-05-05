"""
SQLite-backed unified chat session store.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deeptutor.services.path_service import get_path_service
from deeptutor.services.practice.domain_normalization import normalize_practice_domain


DEFAULT_TESTER_ID = "local-default"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


@dataclass
class TurnRecord:
    id: str
    session_id: str
    capability: str
    status: str
    error: str
    created_at: float
    updated_at: float
    finished_at: float | None
    last_seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "turn_id": self.id,
            "session_id": self.session_id,
            "capability": self.capability,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "last_seq": self.last_seq,
        }


class SQLiteSessionStore:
    """Persist unified chat sessions and messages in a SQLite database."""

    def __init__(self, db_path: Path | None = None) -> None:
        path_service = get_path_service()
        self.db_path = db_path or path_service.get_chat_history_db()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_db(path_service)
        self._lock = asyncio.Lock()
        self._initialize()

    def _migrate_legacy_db(self, path_service) -> None:
        """Move the legacy ``data/chat_history.db`` into ``data/user/`` once."""
        legacy_path = path_service.project_root / "data" / "chat_history.db"
        if self.db_path.exists() or not legacy_path.exists() or legacy_path == self.db_path:
            return
        try:
            os.replace(legacy_path, self.db_path)
        except OSError:
            # Fall back to leaving the legacy DB in place if an OS-level move
            # is not possible; the new DB path will be initialized empty.
            pass

    def _initialize(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    tester_id TEXT NOT NULL DEFAULT 'local-default',
                    title TEXT NOT NULL DEFAULT 'New conversation',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    compressed_summary TEXT DEFAULT '',
                    summary_up_to_msg_id INTEGER DEFAULT 0,
                    preferences_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS testers (
                    id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_seen_at REAL,
                    disabled_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_testers_disabled
                    ON testers(disabled_at, created_at DESC);

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    capability TEXT DEFAULT '',
                    events_json TEXT DEFAULT '',
                    attachments_json TEXT DEFAULT '',
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_created
                    ON messages(session_id, created_at, id);

                CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
                    ON sessions(updated_at DESC);

                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    capability TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'running',
                    error TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    finished_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_turns_session_updated
                    ON turns(session_id, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_turns_session_status
                    ON turns(session_id, status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS turn_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    stage TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    metadata_json TEXT DEFAULT '',
                    timestamp REAL NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(turn_id, seq)
                );

                CREATE INDEX IF NOT EXISTS idx_turn_events_turn_seq
                    ON turn_events(turn_id, seq);

                CREATE TABLE IF NOT EXISTS notebook_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tester_id TEXT NOT NULL DEFAULT 'local-default',
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    question_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    question_type TEXT DEFAULT '',
                    options_json TEXT DEFAULT '{}',
                    correct_answer TEXT DEFAULT '',
                    explanation TEXT DEFAULT '',
                    difficulty TEXT DEFAULT '',
                    user_answer TEXT DEFAULT '',
                    is_correct INTEGER DEFAULT 0,
                    bookmarked INTEGER DEFAULT 0,
                    followup_session_id TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(session_id, question_id)
                );

                CREATE INDEX IF NOT EXISTS idx_notebook_entries_session
                    ON notebook_entries(session_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_notebook_entries_bookmarked
                    ON notebook_entries(bookmarked, created_at DESC);

                CREATE TABLE IF NOT EXISTS notebook_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notebook_entry_categories (
                    entry_id INTEGER NOT NULL REFERENCES notebook_entries(id) ON DELETE CASCADE,
                    category_id INTEGER NOT NULL REFERENCES notebook_categories(id) ON DELETE CASCADE,
                    PRIMARY KEY (entry_id, category_id)
                );

                CREATE TABLE IF NOT EXISTS practice_attempts (
                    id TEXT PRIMARY KEY,
                    tester_id TEXT NOT NULL DEFAULT 'local-default',
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    source_type TEXT DEFAULT 'practice',
                    source_session_id TEXT DEFAULT '',
                    source_message_id INTEGER,
                    title TEXT NOT NULL DEFAULT 'Practice Quiz',
                    topic TEXT DEFAULT '',
                    knowledge_base TEXT DEFAULT '',
                    mode TEXT DEFAULT 'untimed',
                    status TEXT NOT NULL DEFAULT 'in_progress',
                    time_limit_seconds REAL,
                    question_count INTEGER NOT NULL DEFAULT 0,
                    quiz_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    result_summary_json TEXT NOT NULL DEFAULT '{}',
                    started_at REAL NOT NULL,
                    submitted_at REAL,
                    duration_seconds REAL,
                    timed_out INTEGER NOT NULL DEFAULT 0,
                    score_correct INTEGER,
                    score_total INTEGER,
                    score_percent REAL
                );

                CREATE INDEX IF NOT EXISTS idx_practice_attempts_started
                    ON practice_attempts(started_at DESC);

                CREATE INDEX IF NOT EXISTS idx_practice_attempts_session
                    ON practice_attempts(session_id, started_at DESC);

                CREATE INDEX IF NOT EXISTS idx_practice_attempts_source_session
                    ON practice_attempts(source_session_id, started_at DESC);

                CREATE TABLE IF NOT EXISTS practice_attempt_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id TEXT NOT NULL REFERENCES practice_attempts(id) ON DELETE CASCADE,
                    display_order INTEGER NOT NULL,
                    question_id TEXT NOT NULL,
                    question_text TEXT NOT NULL DEFAULT '',
                    question_type TEXT DEFAULT '',
                    options_json TEXT DEFAULT '{}',
                    domain TEXT DEFAULT '',
                    difficulty TEXT DEFAULT '',
                    correct_answer TEXT DEFAULT '',
                    user_answer TEXT DEFAULT '',
                    is_correct INTEGER NOT NULL DEFAULT 0,
                    is_answered INTEGER NOT NULL DEFAULT 0,
                    explanation TEXT DEFAULT '',
                    coaching_note TEXT DEFAULT '',
                    UNIQUE(attempt_id, question_id)
                );

                CREATE INDEX IF NOT EXISTS idx_practice_attempt_items_attempt
                    ON practice_attempt_items(attempt_id, display_order, id);

                CREATE TABLE IF NOT EXISTS flashcard_decks (
                    id TEXT PRIMARY KEY,
                    tester_id TEXT NOT NULL DEFAULT 'local-default',
                    source_type TEXT NOT NULL DEFAULT 'topic',
                    title TEXT NOT NULL,
                    topic TEXT DEFAULT '',
                    source_summary TEXT DEFAULT '',
                    source_kb_names_json TEXT NOT NULL DEFAULT '[]',
                    style TEXT DEFAULT 'mixed',
                    card_count INTEGER NOT NULL DEFAULT 0,
                    generation_fingerprint TEXT NOT NULL DEFAULT '',
                    generation_settings_json TEXT NOT NULL DEFAULT '{}',
                    source_context_json TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_reviewed_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_flashcard_decks_updated
                    ON flashcard_decks(updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_flashcard_decks_fingerprint
                    ON flashcard_decks(generation_fingerprint, updated_at DESC);

                CREATE TABLE IF NOT EXISTS flashcard_cards (
                    id TEXT PRIMARY KEY,
                    deck_id TEXT NOT NULL REFERENCES flashcard_decks(id) ON DELETE CASCADE,
                    display_order INTEGER NOT NULL,
                    front TEXT NOT NULL,
                    back TEXT NOT NULL,
                    hint TEXT DEFAULT '',
                    tag TEXT DEFAULT '',
                    source_ref TEXT DEFAULT '',
                    UNIQUE(deck_id, display_order)
                );

                CREATE INDEX IF NOT EXISTS idx_flashcard_cards_deck
                    ON flashcard_cards(deck_id, display_order, id);

                CREATE TABLE IF NOT EXISTS flashcard_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deck_id TEXT NOT NULL REFERENCES flashcard_decks(id) ON DELETE CASCADE,
                    card_id TEXT NOT NULL REFERENCES flashcard_cards(id) ON DELETE CASCADE,
                    rating TEXT NOT NULL,
                    reviewed_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_flashcard_reviews_deck_time
                    ON flashcard_reviews(deck_id, reviewed_at DESC, id DESC);

                CREATE INDEX IF NOT EXISTS idx_flashcard_reviews_card_time
                    ON flashcard_reviews(card_id, reviewed_at DESC, id DESC);

                CREATE TABLE IF NOT EXISTS flashcard_session_reviews (
                    id TEXT PRIMARY KEY,
                    deck_id TEXT NOT NULL REFERENCES flashcard_decks(id) ON DELETE CASCADE,
                    review_mode TEXT NOT NULL DEFAULT 'full_deck',
                    card_ids_json TEXT NOT NULL DEFAULT '[]',
                    cards_reviewed INTEGER NOT NULL DEFAULT 0,
                    got_it_count INTEGER NOT NULL DEFAULT 0,
                    missed_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    analysis_summary TEXT DEFAULT '',
                    analysis_strengths_json TEXT NOT NULL DEFAULT '[]',
                    analysis_weak_spots_json TEXT NOT NULL DEFAULT '[]',
                    analysis_recommended_next_step TEXT DEFAULT '',
                    analysis_focus_topics_json TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_flashcard_session_reviews_deck_created
                    ON flashcard_session_reviews(deck_id, created_at DESC);
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
            if "preferences_json" not in columns:
                conn.execute(
                    "ALTER TABLE sessions ADD COLUMN preferences_json TEXT DEFAULT '{}'"
                )
            self._ensure_owner_columns(conn)
            conn.commit()

    def _ensure_owner_columns(self, conn: sqlite3.Connection) -> None:
        """Idempotently add private-tester owner columns to legacy local DBs."""
        now = time.time()
        conn.execute(
            """
            INSERT OR IGNORE INTO testers (
                id, display_name, code_hash, created_at, last_seen_at, disabled_at
            )
            VALUES (?, ?, ?, ?, NULL, ?)
            """,
            (DEFAULT_TESTER_ID, "Local Default", "system$local-default", now, now),
        )
        owner_tables = {
            "sessions": "updated_at",
            "notebook_entries": "created_at",
            "practice_attempts": "started_at",
            "flashcard_decks": "updated_at",
        }
        for table, order_column in owner_tables.items():
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "tester_id" not in columns:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN tester_id TEXT NOT NULL DEFAULT '{DEFAULT_TESTER_ID}'"
                )
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{table}_tester_owner
                    ON {table}(tester_id, {order_column} DESC)
                """
            )

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _serialize_tester(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "tester_id": row["id"],
            "display_name": row["display_name"],
            "created_at": row["created_at"],
            "last_seen_at": row["last_seen_at"],
            "disabled_at": row["disabled_at"],
            "disabled": row["disabled_at"] is not None,
        }

    def _upsert_tester_sync(
        self,
        tester_id: str,
        display_name: str,
        code_hash: str,
        disabled_at: float | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        resolved_id = str(tester_id or "").strip()
        resolved_name = str(display_name or "").strip()
        resolved_hash = str(code_hash or "").strip()
        if not resolved_id:
            raise ValueError("tester_id is required")
        if not resolved_name:
            raise ValueError("display_name is required")
        if not resolved_hash:
            raise ValueError("code_hash is required")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO testers (id, display_name, code_hash, created_at, last_seen_at, disabled_at)
                VALUES (?, ?, ?, ?, NULL, ?)
                ON CONFLICT(id) DO UPDATE SET
                    display_name = excluded.display_name,
                    code_hash = excluded.code_hash,
                    disabled_at = excluded.disabled_at
                """,
                (resolved_id, resolved_name[:120], resolved_hash, now, disabled_at),
            )
            row = conn.execute("SELECT * FROM testers WHERE id = ?", (resolved_id,)).fetchone()
            conn.commit()
        return self._serialize_tester(row)

    async def upsert_tester(
        self,
        tester_id: str,
        display_name: str,
        code_hash: str,
        disabled_at: float | None = None,
    ) -> dict[str, Any]:
        return await self._run(
            self._upsert_tester_sync,
            tester_id,
            display_name,
            code_hash,
            disabled_at,
        )

    def _list_testers_for_access_sync(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM testers
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [
            {
                **self._serialize_tester(row),
                "code_hash": row["code_hash"],
            }
            for row in rows
        ]

    async def list_testers_for_access(self) -> list[dict[str, Any]]:
        return await self._run(self._list_testers_for_access_sync)

    def _get_tester_sync(self, tester_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM testers WHERE id = ?",
                (tester_id,),
            ).fetchone()
        return self._serialize_tester(row) if row is not None else None

    async def get_tester(self, tester_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_tester_sync, tester_id)

    def _touch_tester_seen_sync(self, tester_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE testers SET last_seen_at = ? WHERE id = ? AND disabled_at IS NULL",
                (now, tester_id),
            )
            row = conn.execute(
                "SELECT * FROM testers WHERE id = ?",
                (tester_id,),
            ).fetchone()
            conn.commit()
        return self._serialize_tester(row) if row is not None else None

    async def touch_tester_seen(self, tester_id: str) -> dict[str, Any] | None:
        return await self._run(self._touch_tester_seen_sync, tester_id)

    def _create_session_sync(
        self,
        title: str | None = None,
        session_id: str | None = None,
        tester_id: str = DEFAULT_TESTER_ID,
    ) -> dict[str, Any]:
        now = time.time()
        resolved_id = session_id or f"unified_{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
        resolved_title = (title or "New conversation").strip() or "New conversation"
        resolved_tester_id = str(tester_id or DEFAULT_TESTER_ID).strip() or DEFAULT_TESTER_ID
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    id, tester_id, title, created_at, updated_at, compressed_summary, summary_up_to_msg_id
                )
                VALUES (?, ?, ?, ?, ?, '', 0)
                """,
                (resolved_id, resolved_tester_id, resolved_title[:100], now, now),
            )
            conn.commit()
        return {
            "id": resolved_id,
            "session_id": resolved_id,
            "tester_id": resolved_tester_id,
            "title": resolved_title[:100],
            "created_at": now,
            "updated_at": now,
            "compressed_summary": "",
            "summary_up_to_msg_id": 0,
        }

    async def create_session(
        self,
        title: str | None = None,
        session_id: str | None = None,
        tester_id: str = DEFAULT_TESTER_ID,
    ) -> dict[str, Any]:
        return await self._run(self._create_session_sync, title, session_id, tester_id)

    def _get_session_sync(self, session_id: str, tester_id: str | None = None) -> dict[str, Any] | None:
        clauses = ["s.id = ?"]
        params: list[Any] = [session_id]
        if tester_id:
            clauses.append("s.tester_id = ?")
            params.append(tester_id)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                    s.id,
                    s.tester_id,
                    s.title,
                    s.created_at,
                    s.updated_at,
                    s.compressed_summary,
                    s.summary_up_to_msg_id,
                    s.preferences_json,
                    COALESCE(
                        (
                            SELECT t.status
                            FROM turns t
                            WHERE t.session_id = s.id
                            ORDER BY t.updated_at DESC
                            LIMIT 1
                        ),
                        'idle'
                    ) AS status,
                    COALESCE(
                        (
                            SELECT t.id
                            FROM turns t
                            WHERE t.session_id = s.id AND t.status = 'running'
                            ORDER BY t.updated_at DESC
                            LIMIT 1
                        ),
                        ''
                    ) AS active_turn_id,
                    COALESCE(
                        (
                            SELECT t.capability
                            FROM turns t
                            WHERE t.session_id = s.id
                            ORDER BY t.updated_at DESC
                            LIMIT 1
                        ),
                        ''
                    ) AS capability
                FROM sessions
                s
                WHERE {" AND ".join(clauses)}
                """,
                params,
            ).fetchone()
        if not row:
            return None
        payload = dict(row)
        payload["session_id"] = payload["id"]
        payload["preferences"] = _json_loads(payload.pop("preferences_json", ""), {})
        return payload

    async def get_session(self, session_id: str, tester_id: str | None = None) -> dict[str, Any] | None:
        return await self._run(self._get_session_sync, session_id, tester_id)

    async def ensure_session(
        self,
        session_id: str | None = None,
        tester_id: str = DEFAULT_TESTER_ID,
    ) -> dict[str, Any]:
        if session_id:
            session = await self.get_session(session_id, tester_id=tester_id)
            if session is not None:
                return session
            raise ValueError(f"Session not found: {session_id}")
        return await self.create_session(tester_id=tester_id)

    @staticmethod
    def _serialize_turn(row: sqlite3.Row) -> dict[str, Any]:
        return TurnRecord(
            id=row["id"],
            session_id=row["session_id"],
            capability=row["capability"] or "",
            status=row["status"] or "running",
            error=row["error"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            finished_at=row["finished_at"],
            last_seq=row["last_seq"] if "last_seq" in row.keys() else 0,
        ).to_dict()

    def _create_turn_sync(self, session_id: str, capability: str = "") -> dict[str, Any]:
        now = time.time()
        turn_id = f"turn_{int(now * 1000)}_{uuid.uuid4().hex[:10]}"
        with self._connect() as conn:
            session = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise ValueError(f"Session not found: {session_id}")
            active = conn.execute(
                """
                SELECT id
                FROM turns
                WHERE session_id = ? AND status = 'running'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if active is not None:
                raise RuntimeError(f"Session already has an active turn: {active['id']}")
            conn.execute(
                """
                INSERT INTO turns (id, session_id, capability, status, error, created_at, updated_at, finished_at)
                VALUES (?, ?, ?, 'running', '', ?, ?, NULL)
                """,
                (turn_id, session_id, capability or "", now, now),
            )
            conn.commit()
        return {
            "id": turn_id,
            "turn_id": turn_id,
            "session_id": session_id,
            "capability": capability or "",
            "status": "running",
            "error": "",
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "last_seq": 0,
        }

    async def create_turn(self, session_id: str, capability: str = "") -> dict[str, Any]:
        return await self._run(self._create_turn_sync, session_id, capability)

    def _get_turn_sync(self, turn_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    t.*,
                    s.tester_id AS tester_id,
                    COALESCE((SELECT MAX(seq) FROM turn_events te WHERE te.turn_id = t.id), 0) AS last_seq
                FROM turns t
                INNER JOIN sessions s ON s.id = t.session_id
                WHERE t.id = ?
                """,
                (turn_id,),
            ).fetchone()
        if row is None:
            return None
        return self._serialize_turn(row)

    async def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_turn_sync, turn_id)

    async def turn_belongs_to_tester(self, turn_id: str, tester_id: str) -> bool:
        return await self._run(self._turn_belongs_to_tester_sync, turn_id, tester_id)

    def _turn_belongs_to_tester_sync(self, turn_id: str, tester_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM turns t
                INNER JOIN sessions s ON s.id = t.session_id
                WHERE t.id = ? AND s.tester_id = ?
                LIMIT 1
                """,
                (turn_id, tester_id),
            ).fetchone()
        return row is not None

    def _get_active_turn_sync(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    t.*,
                    COALESCE((SELECT MAX(seq) FROM turn_events te WHERE te.turn_id = t.id), 0) AS last_seq
                FROM turns t
                WHERE t.session_id = ? AND t.status = 'running'
                ORDER BY t.updated_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._serialize_turn(row)

    async def get_active_turn(self, session_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_active_turn_sync, session_id)

    def _list_active_turns_sync(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    t.*,
                    COALESCE((SELECT MAX(seq) FROM turn_events te WHERE te.turn_id = t.id), 0) AS last_seq
                FROM turns t
                WHERE t.session_id = ? AND t.status = 'running'
                ORDER BY t.updated_at DESC
                """,
                (session_id,),
            ).fetchall()
        return [self._serialize_turn(row) for row in rows]

    async def list_active_turns(self, session_id: str) -> list[dict[str, Any]]:
        return await self._run(self._list_active_turns_sync, session_id)

    def _update_turn_status_sync(self, turn_id: str, status: str, error: str = "") -> bool:
        now = time.time()
        finished_at = now if status in {"completed", "failed", "cancelled"} else None
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE turns
                SET status = ?, error = ?, updated_at = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, error or "", now, finished_at, turn_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_turn_status(self, turn_id: str, status: str, error: str = "") -> bool:
        return await self._run(self._update_turn_status_sync, turn_id, status, error)

    def _append_turn_event_sync(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            turn = conn.execute("SELECT id, session_id FROM turns WHERE id = ?", (turn_id,)).fetchone()
            if turn is None:
                raise ValueError(f"Turn not found: {turn_id}")
            provided_seq = int(event.get("seq") or 0)
            if provided_seq > 0:
                seq = provided_seq
            else:
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) AS last_seq FROM turn_events WHERE turn_id = ?",
                    (turn_id,),
                ).fetchone()
                seq = int(row["last_seq"]) + 1 if row else 1
            payload = dict(event)
            payload["seq"] = seq
            payload["turn_id"] = payload.get("turn_id") or turn_id
            payload["session_id"] = payload.get("session_id") or turn["session_id"]
            conn.execute(
                """
                INSERT OR REPLACE INTO turn_events (
                    turn_id, seq, type, source, stage, content, metadata_json, timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    seq,
                    payload.get("type", ""),
                    payload.get("source", ""),
                    payload.get("stage", ""),
                    payload.get("content", "") or "",
                    _json_dumps(payload.get("metadata", {})),
                    float(payload.get("timestamp") or now),
                    now,
                ),
            )
            conn.execute(
                "UPDATE turns SET updated_at = ? WHERE id = ?",
                (now, turn_id),
            )
            conn.commit()
        return payload

    async def append_turn_event(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]:
        return await self._run(self._append_turn_event_sync, turn_id, event)

    def _get_turn_events_sync(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT turn_id, seq, type, source, stage, content, metadata_json, timestamp
                FROM turn_events
                WHERE turn_id = ? AND seq > ?
                ORDER BY seq ASC
                """,
                (turn_id, max(0, int(after_seq))),
            ).fetchall()
            turn = conn.execute("SELECT session_id FROM turns WHERE id = ?", (turn_id,)).fetchone()
        session_id = turn["session_id"] if turn else ""
        return [
            {
                "type": row["type"],
                "source": row["source"] or "",
                "stage": row["stage"] or "",
                "content": row["content"] or "",
                "metadata": _json_loads(row["metadata_json"], {}),
                "session_id": session_id,
                "turn_id": row["turn_id"],
                "seq": row["seq"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    async def get_turn_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        return await self._run(self._get_turn_events_sync, turn_id, after_seq)

    @staticmethod
    def _normalize_question_count(snapshot: dict[str, Any]) -> int:
        questions = snapshot.get("questions")
        return len(questions) if isinstance(questions, list) else 0

    @staticmethod
    def _serialize_practice_attempt(row: sqlite3.Row) -> dict[str, Any]:
        payload = {
            "id": row["id"],
            "attempt_id": row["id"],
            "tester_id": row["tester_id"] if "tester_id" in row.keys() else DEFAULT_TESTER_ID,
            "session_id": row["session_id"],
            "source_type": row["source_type"] or "practice",
            "source_session_id": row["source_session_id"] or None,
            "source_message_id": row["source_message_id"],
            "title": row["title"] or "Practice Quiz",
            "topic": row["topic"] or "",
            "knowledge_base": row["knowledge_base"] or "",
            "mode": row["mode"] or "untimed",
            "status": row["status"] or "in_progress",
            "time_limit_seconds": row["time_limit_seconds"],
            "question_count": int(row["question_count"] or 0),
            "quiz_snapshot": _json_loads(row["quiz_snapshot_json"], {}),
            "result_summary": _json_loads(row["result_summary_json"], {}),
            "started_at": row["started_at"],
            "submitted_at": row["submitted_at"],
            "duration_seconds": row["duration_seconds"],
            "timed_out": bool(row["timed_out"]),
            "score_correct": row["score_correct"],
            "score_total": row["score_total"],
            "score_percent": row["score_percent"],
        }
        return payload

    @staticmethod
    def _serialize_practice_item(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "attempt_id": row["attempt_id"],
            "display_order": int(row["display_order"] or 0),
            "question_id": row["question_id"] or "",
            "question_text": row["question_text"] or "",
            "question_type": row["question_type"] or "",
            "options": _json_loads(row["options_json"], {}),
            "domain": normalize_practice_domain(row["domain"] or ""),
            "difficulty": row["difficulty"] or "",
            "correct_answer": row["correct_answer"] or "",
            "user_answer": row["user_answer"] or "",
            "is_correct": bool(row["is_correct"]),
            "is_answered": bool(row["is_answered"]),
            "explanation": row["explanation"] or "",
            "coaching_note": row["coaching_note"] or "",
        }

    def _create_quiz_attempt_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id is required")
        quiz_snapshot = payload.get("quiz_snapshot")
        if not isinstance(quiz_snapshot, dict):
            raise ValueError("quiz_snapshot must be an object")

        attempt_id = f"practice_{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
        question_count = self._normalize_question_count(quiz_snapshot)

        with self._connect() as conn:
            session = conn.execute("SELECT id, tester_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise ValueError(f"Session not found: {session_id}")
            tester_id = str(payload.get("tester_id") or session["tester_id"] or DEFAULT_TESTER_ID)

            conn.execute(
                """
                INSERT INTO practice_attempts (
                    id, tester_id, session_id, source_type, source_session_id, source_message_id, title,
                    topic, knowledge_base, mode, status, time_limit_seconds, question_count,
                    quiz_snapshot_json, result_summary_json, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?)
                """,
                (
                    attempt_id,
                    tester_id,
                    session_id,
                    str(payload.get("source_type") or "practice"),
                    str(payload.get("source_session_id") or ""),
                    payload.get("source_message_id"),
                    str(payload.get("title") or "Practice Quiz")[:100],
                    str(payload.get("topic") or ""),
                    str(payload.get("knowledge_base") or ""),
                    str(payload.get("mode") or "untimed"),
                    str(payload.get("status") or "in_progress"),
                    payload.get("time_limit_seconds"),
                    question_count,
                    _json_dumps(quiz_snapshot),
                    now,
                ),
            )
            conn.commit()

            row = conn.execute("SELECT * FROM practice_attempts WHERE id = ?", (attempt_id,)).fetchone()
        if row is None:
            raise ValueError("Failed to create practice attempt")
        return self._serialize_practice_attempt(row)

    async def create_quiz_attempt(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._run(self._create_quiz_attempt_sync, payload)

    def _get_quiz_attempt_sync(self, attempt_id: str, tester_id: str | None = None) -> dict[str, Any] | None:
        clauses = ["id = ?"]
        params: list[Any] = [attempt_id]
        if tester_id:
            clauses.append("tester_id = ?")
            params.append(tester_id)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM practice_attempts WHERE {' AND '.join(clauses)}",
                params,
            ).fetchone()
        return self._serialize_practice_attempt(row) if row is not None else None

    async def get_quiz_attempt(self, attempt_id: str, tester_id: str | None = None) -> dict[str, Any] | None:
        return await self._run(self._get_quiz_attempt_sync, attempt_id, tester_id)

    def _get_quiz_attempt_items_sync(self, attempt_id: str, tester_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM practice_attempt_items i
                INNER JOIN practice_attempts a ON a.id = i.attempt_id
                WHERE i.attempt_id = ?
                  AND (? IS NULL OR a.tester_id = ?)
                ORDER BY i.display_order ASC, i.id ASC
                """,
                (attempt_id, tester_id, tester_id),
            ).fetchall()
        return [self._serialize_practice_item(row) for row in rows]

    async def get_quiz_attempt_items(self, attempt_id: str, tester_id: str | None = None) -> list[dict[str, Any]]:
        return await self._run(self._get_quiz_attempt_items_sync, attempt_id, tester_id)

    def _save_quiz_attempt_results_sync(
        self, attempt_id: str, payload: dict[str, Any], tester_id: str | None = None
    ) -> dict[str, Any]:
        structured_result = payload.get("structured_result")
        if not isinstance(structured_result, dict):
            raise ValueError("structured_result must be an object")

        question_results = structured_result.get("question_results")
        if not isinstance(question_results, list):
            question_results = []

        score = structured_result.get("score")
        if not isinstance(score, dict):
            score = {}

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM practice_attempts WHERE id = ? AND (? IS NULL OR tester_id = ?)",
                (attempt_id, tester_id, tester_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"Practice attempt not found: {attempt_id}")

            conn.execute("DELETE FROM practice_attempt_items WHERE attempt_id = ?", (attempt_id,))

            for index, item in enumerate(question_results, start=1):
                if not isinstance(item, dict):
                    continue
                normalized_domain = normalize_practice_domain(str(item.get("domain") or ""))
                conn.execute(
                    """
                    INSERT INTO practice_attempt_items (
                        attempt_id, display_order, question_id, question_text, question_type,
                        options_json, domain, difficulty, correct_answer, user_answer,
                        is_correct, is_answered, explanation, coaching_note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt_id,
                        int(item.get("display_order") or index),
                        str(item.get("question_id") or f"q{index}"),
                        str(item.get("question_text") or item.get("question") or ""),
                        str(item.get("question_type") or ""),
                        _json_dumps(item.get("options") if isinstance(item.get("options"), dict) else {}),
                        normalized_domain,
                        str(item.get("difficulty") or ""),
                        str(item.get("correct_answer") or ""),
                        str(item.get("user_answer") or ""),
                        1 if bool(item.get("is_correct")) else 0,
                        1 if bool(item.get("is_answered")) else 0,
                        str(item.get("explanation") or ""),
                        str(item.get("coaching_note") or ""),
                    ),
                )

            normalized_structured_result = dict(structured_result)
            normalized_structured_result["question_results"] = [
                {
                    **item,
                    "domain": normalize_practice_domain(str(item.get("domain") or "")),
                }
                for item in question_results
                if isinstance(item, dict)
            ]
            domain_rollup: dict[str, dict[str, Any]] = {}
            for item in normalized_structured_result["question_results"]:
                domain = str(item.get("domain") or "").strip()
                if not domain:
                    continue
                bucket = domain_rollup.setdefault(
                    domain,
                    {"domain": domain, "correct": 0, "total": 0, "question_numbers": []},
                )
                bucket["total"] += 1
                bucket["correct"] += 1 if bool(item.get("is_correct")) else 0
                question_number = int(item.get("display_order") or 0)
                if question_number > 0:
                    bucket["question_numbers"].append(question_number)
            normalized_structured_result["domain_breakdown"] = [
                {
                    **bucket,
                    "percent": round((bucket["correct"] / bucket["total"]) * 100.0, 2)
                    if bucket["total"]
                    else 0.0,
                }
                for bucket in sorted(domain_rollup.values(), key=lambda item: item["domain"].lower())
            ]

            submitted_at = payload.get("submitted_at") or time.time()
            timed_out = bool(payload.get("timed_out"))
            conn.execute(
                """
                UPDATE practice_attempts
                SET status = ?,
                    submitted_at = ?,
                    duration_seconds = ?,
                    timed_out = ?,
                    result_summary_json = ?,
                    score_correct = ?,
                    score_total = ?,
                    score_percent = ?
                WHERE id = ?
                """,
                (
                    "timed_out" if timed_out else "submitted",
                    submitted_at,
                    payload.get("duration_seconds"),
                    1 if timed_out else 0,
                    _json_dumps(normalized_structured_result),
                    score.get("correct"),
                    score.get("total"),
                    score.get("percent"),
                    attempt_id,
                ),
            )
            conn.commit()
            refreshed = conn.execute("SELECT * FROM practice_attempts WHERE id = ?", (attempt_id,)).fetchone()
        if refreshed is None:
            raise ValueError(f"Practice attempt not found: {attempt_id}")
        result = self._serialize_practice_attempt(refreshed)
        result["items"] = self._get_quiz_attempt_items_sync(attempt_id, tester_id=tester_id)
        return result

    async def save_quiz_attempt_results(self, attempt_id: str, payload: dict[str, Any], tester_id: str | None = None) -> dict[str, Any]:
        return await self._run(self._save_quiz_attempt_results_sync, attempt_id, payload, tester_id)

    def _list_quiz_attempts_sync(
        self,
        limit: int = 20,
        offset: int = 0,
        session_id: str | None = None,
        source_session_id: str | None = None,
        tester_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if source_session_id:
            clauses.append("source_session_id = ?")
            params.append(source_session_id)
        if tester_id:
            clauses.append("tester_id = ?")
            params.append(tester_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([int(limit), int(offset)])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM practice_attempts
                {where_sql}
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._serialize_practice_attempt(row) for row in rows]

    async def list_quiz_attempts(
        self,
        limit: int = 20,
        offset: int = 0,
        session_id: str | None = None,
        source_session_id: str | None = None,
        tester_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self._run(
            self._list_quiz_attempts_sync,
            limit,
            offset,
            session_id,
            source_session_id,
            tester_id,
        )

    def _get_domain_progress_summary_sync(self, recent_attempt_window: int = 10, tester_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            recent_rows = conn.execute(
                """
                SELECT id
                FROM practice_attempts
                WHERE status IN ('submitted', 'timed_out') AND submitted_at IS NOT NULL
                  AND (? IS NULL OR tester_id = ?)
                ORDER BY submitted_at DESC
                LIMIT ?
                """,
                (tester_id, tester_id, int(recent_attempt_window)),
            ).fetchall()
            recent_attempt_ids = {row["id"] for row in recent_rows}

            item_rows = conn.execute(
                """
                SELECT
                    i.domain AS domain,
                    a.id AS attempt_id,
                    a.submitted_at AS submitted_at,
                    i.is_correct AS is_correct
                FROM practice_attempt_items i
                INNER JOIN practice_attempts a ON a.id = i.attempt_id
                WHERE a.status IN ('submitted', 'timed_out')
                  AND COALESCE(i.domain, '') <> ''
                  AND (? IS NULL OR a.tester_id = ?)
                """,
                (tester_id, tester_id),
            ).fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for row in item_rows:
            domain = normalize_practice_domain(row["domain"] or "")
            if not domain:
                continue
            bucket = grouped.setdefault(
                domain,
                {
                    "domain": domain,
                    "lifetime_total": 0,
                    "lifetime_correct": 0,
                    "lifetime_attempt_ids": set(),
                    "recent_total": 0,
                    "recent_correct": 0,
                    "recent_attempt_ids": set(),
                    "last_submitted_at": None,
                },
            )
            bucket["lifetime_total"] += 1
            bucket["lifetime_correct"] += 1 if bool(row["is_correct"]) else 0
            bucket["lifetime_attempt_ids"].add(row["attempt_id"])
            submitted_at = row["submitted_at"]
            if submitted_at and (
                bucket["last_submitted_at"] is None or submitted_at > bucket["last_submitted_at"]
            ):
                bucket["last_submitted_at"] = submitted_at
            if row["attempt_id"] in recent_attempt_ids:
                bucket["recent_total"] += 1
                bucket["recent_correct"] += 1 if bool(row["is_correct"]) else 0
                bucket["recent_attempt_ids"].add(row["attempt_id"])

        result: list[dict[str, Any]] = []
        for bucket in grouped.values():
            lifetime_total = int(bucket["lifetime_total"] or 0)
            recent_total = int(bucket["recent_total"] or 0)
            lifetime_correct = int(bucket["lifetime_correct"] or 0)
            recent_correct = int(bucket["recent_correct"] or 0)
            result.append(
                {
                    "domain": bucket["domain"],
                    "lifetime": {
                        "attempt_count": len(bucket["lifetime_attempt_ids"]),
                        "correct": lifetime_correct,
                        "total": lifetime_total,
                        "percent": (lifetime_correct / lifetime_total * 100.0) if lifetime_total else 0.0,
                    },
                    "recent": {
                        "attempt_count": len(bucket["recent_attempt_ids"]),
                        "correct": recent_correct,
                        "total": recent_total,
                        "percent": (recent_correct / recent_total * 100.0) if recent_total else 0.0,
                    },
                    "last_submitted_at": bucket["last_submitted_at"],
                }
            )
        result.sort(
            key=lambda item: (
                -(float(item["last_submitted_at"] or 0.0)),
                str(item["domain"]).lower(),
            )
        )
        return result

    async def get_domain_progress_summary(self, recent_attempt_window: int = 10, tester_id: str | None = None) -> list[dict[str, Any]]:
        return await self._run(self._get_domain_progress_summary_sync, recent_attempt_window, tester_id)

    @staticmethod
    def _serialize_flashcard_card(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "deck_id": row["deck_id"],
            "display_order": int(row["display_order"] or 0),
            "front": row["front"] or "",
            "back": row["back"] or "",
            "hint": row["hint"] or "",
            "tag": row["tag"] or "",
            "source_ref": row["source_ref"] or "",
        }

    def _get_flashcard_rating_map_sync(self, conn: sqlite3.Connection, deck_id: str) -> dict[str, dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT r.card_id, r.rating, r.reviewed_at
            FROM flashcard_reviews r
            INNER JOIN (
                SELECT card_id, MAX(reviewed_at) AS max_reviewed_at, MAX(id) AS max_id
                FROM flashcard_reviews
                WHERE deck_id = ?
                GROUP BY card_id
            ) latest
              ON latest.card_id = r.card_id
             AND latest.max_reviewed_at = r.reviewed_at
             AND latest.max_id = r.id
            WHERE r.deck_id = ?
            """,
            (deck_id, deck_id),
        ).fetchall()
        return {
            row["card_id"]: {
                "rating": row["rating"] or "new",
                "reviewed_at": row["reviewed_at"],
            }
            for row in rows
        }

    def _build_flashcard_summary_sync(
        self, conn: sqlite3.Connection, deck_id: str, card_ids: list[str]
    ) -> dict[str, Any]:
        rating_map = self._get_flashcard_rating_map_sync(conn, deck_id)
        counts = {"new": 0, "got_it": 0, "missed": 0, "skipped": 0}
        for card_id in card_ids:
            rating = str(rating_map.get(card_id, {}).get("rating") or "new")
            if rating not in counts:
                rating = "new"
            counts[rating] += 1
        return {
            "ratings": rating_map,
            "counts": counts,
            "remaining": counts["new"],
        }

    @staticmethod
    def _serialize_flashcard_session_review(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "deck_id": row["deck_id"],
            "review_mode": row["review_mode"] or "full_deck",
            "card_ids": _json_loads(row["card_ids_json"], []),
            "cards_reviewed": int(row["cards_reviewed"] or 0),
            "got_it_count": int(row["got_it_count"] or 0),
            "missed_count": int(row["missed_count"] or 0),
            "skipped_count": int(row["skipped_count"] or 0),
            "analysis_summary": row["analysis_summary"] or "",
            "analysis_strengths": _json_loads(row["analysis_strengths_json"], []),
            "analysis_weak_spots": _json_loads(row["analysis_weak_spots_json"], []),
            "analysis_recommended_next_step": row["analysis_recommended_next_step"] or "",
            "analysis_focus_topics": _json_loads(row["analysis_focus_topics_json"], []),
            "created_at": row["created_at"],
        }

    def _get_latest_flashcard_session_review_sync(
        self, conn: sqlite3.Connection, deck_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT *
            FROM flashcard_session_reviews
            WHERE deck_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (deck_id,),
        ).fetchone()
        if row is None:
            return None
        return self._serialize_flashcard_session_review(row)

    def _serialize_flashcard_deck(
        self,
        row: sqlite3.Row,
        cards: list[dict[str, Any]] | None = None,
        summary: dict[str, Any] | None = None,
        latest_session_review: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "id": row["id"],
            "deck_id": row["id"],
            "tester_id": row["tester_id"] if "tester_id" in row.keys() else DEFAULT_TESTER_ID,
            "source_type": row["source_type"] or "topic",
            "title": row["title"] or "",
            "topic": row["topic"] or "",
            "source_summary": row["source_summary"] or "",
            "source_kb_names": _json_loads(row["source_kb_names_json"], []),
            "style": row["style"] or "mixed",
            "card_count": int(row["card_count"] or 0),
            "generation_fingerprint": row["generation_fingerprint"] or "",
            "generation_settings": _json_loads(row["generation_settings_json"], {}),
            "source_context": _json_loads(row["source_context_json"], []),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_reviewed_at": row["last_reviewed_at"],
        }
        if cards is not None:
            payload["cards"] = cards
        if summary is not None:
            payload["summary"] = summary
        if latest_session_review is not None:
            payload["latest_session_review"] = latest_session_review
        return payload

    def _save_flashcard_deck_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        cards = payload.get("cards")
        if not isinstance(cards, list) or not cards:
            raise ValueError("cards are required")

        deck_id = str(payload.get("id") or f"deck_{int(now * 1000)}_{uuid.uuid4().hex[:8]}")
        source_kb_names = payload.get("source_kb_names")
        source_context = payload.get("source_context")
        generation_settings = payload.get("generation_settings")
        if not isinstance(source_kb_names, list):
            source_kb_names = []
        if not isinstance(source_context, list):
            source_context = []
        if not isinstance(generation_settings, dict):
            generation_settings = {}

        serialized_cards: list[dict[str, Any]] = []
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO flashcard_decks (
                    id, tester_id, source_type, title, topic, source_summary, source_kb_names_json,
                    style, card_count, generation_fingerprint, generation_settings_json,
                    source_context_json, created_at, updated_at, last_reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    deck_id,
                    str(payload.get("tester_id") or DEFAULT_TESTER_ID),
                    str(payload.get("source_type") or "topic"),
                    str(payload.get("title") or "")[:200],
                    str(payload.get("topic") or ""),
                    str(payload.get("source_summary") or ""),
                    _json_dumps(source_kb_names),
                    str(payload.get("style") or "mixed"),
                    len(cards),
                    str(payload.get("generation_fingerprint") or ""),
                    _json_dumps(generation_settings),
                    _json_dumps(source_context),
                    now,
                    now,
                ),
            )

            for index, card in enumerate(cards, start=1):
                if not isinstance(card, dict):
                    continue
                card_id = str(card.get("id") or f"{deck_id}_card_{index}")
                conn.execute(
                    """
                    INSERT INTO flashcard_cards (
                        id, deck_id, display_order, front, back, hint, tag, source_ref
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        card_id,
                        deck_id,
                        index,
                        str(card.get("front") or ""),
                        str(card.get("back") or ""),
                        str(card.get("hint") or ""),
                        str(card.get("tag") or ""),
                        str(card.get("source_ref") or ""),
                    ),
                )
                serialized_cards.append(
                    {
                        "id": card_id,
                        "deck_id": deck_id,
                        "display_order": index,
                        "front": str(card.get("front") or ""),
                        "back": str(card.get("back") or ""),
                        "hint": str(card.get("hint") or ""),
                        "tag": str(card.get("tag") or ""),
                        "source_ref": str(card.get("source_ref") or ""),
                    }
                )

            conn.commit()
            row = conn.execute(
                "SELECT * FROM flashcard_decks WHERE id = ?",
                (deck_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Failed to save flashcard deck")
        summary = {
            "ratings": {},
            "counts": {"new": len(serialized_cards), "got_it": 0, "missed": 0, "skipped": 0},
            "remaining": len(serialized_cards),
        }
        return self._serialize_flashcard_deck(
            row,
            cards=serialized_cards,
            summary=summary,
            latest_session_review=None,
        )

    async def save_flashcard_deck(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._run(self._save_flashcard_deck_sync, payload)

    def _append_flashcard_cards_sync(
        self,
        deck_id: str,
        cards: list[dict[str, Any]],
        generation_settings: dict[str, Any] | None = None,
        tester_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(cards, list) or not cards:
            raise ValueError("cards are required")
        now = time.time()
        if not isinstance(generation_settings, dict):
            generation_settings = {}
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM flashcard_decks WHERE id = ? AND (? IS NULL OR tester_id = ?)",
                (deck_id, tester_id, tester_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"Flashcard deck not found: {deck_id}")
            current_count = int(row["card_count"] or 0)
            for offset, card in enumerate(cards, start=1):
                if not isinstance(card, dict):
                    continue
                display_order = current_count + offset
                card_id = str(card.get("id") or f"{deck_id}_card_{display_order}")
                conn.execute(
                    """
                    INSERT OR IGNORE INTO flashcard_cards (
                        id, deck_id, display_order, front, back, hint, tag, source_ref
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        card_id,
                        deck_id,
                        display_order,
                        str(card.get("front") or ""),
                        str(card.get("back") or ""),
                        str(card.get("hint") or ""),
                        str(card.get("tag") or ""),
                        str(card.get("source_ref") or ""),
                    ),
                )
            card_rows = conn.execute(
                "SELECT * FROM flashcard_cards WHERE deck_id = ? ORDER BY display_order ASC, id ASC",
                (deck_id,),
            ).fetchall()
            cards_out = [self._serialize_flashcard_card(card_row) for card_row in card_rows]
            conn.execute(
                """
                UPDATE flashcard_decks
                SET card_count = ?, generation_settings_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (len(cards_out), _json_dumps(generation_settings), now, deck_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM flashcard_decks WHERE id = ?", (deck_id,)).fetchone()
            summary = self._build_flashcard_summary_sync(
                conn, deck_id, [card["id"] for card in cards_out]
            )
            latest_session_review = self._get_latest_flashcard_session_review_sync(conn, deck_id)
        if row is None:
            raise ValueError(f"Flashcard deck not found: {deck_id}")
        return self._serialize_flashcard_deck(
            row,
            cards=cards_out,
            summary=summary,
            latest_session_review=latest_session_review,
        )

    async def append_flashcard_cards(
        self,
        deck_id: str,
        cards: list[dict[str, Any]],
        generation_settings: dict[str, Any] | None = None,
        tester_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run(
            self._append_flashcard_cards_sync,
            deck_id,
            cards,
            generation_settings,
            tester_id,
        )

    def _find_flashcard_deck_by_fingerprint_sync(self, generation_fingerprint: str, tester_id: str | None = None) -> dict[str, Any] | None:
        if not generation_fingerprint:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM flashcard_decks
                WHERE generation_fingerprint = ?
                  AND (? IS NULL OR tester_id = ?)
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (generation_fingerprint, tester_id, tester_id),
            ).fetchone()
            if row is None:
                return None
            cards = [
                self._serialize_flashcard_card(card_row)
                for card_row in conn.execute(
                    "SELECT * FROM flashcard_cards WHERE deck_id = ? ORDER BY display_order ASC, id ASC",
                    (row["id"],),
                ).fetchall()
            ]
            summary = self._build_flashcard_summary_sync(
                conn, row["id"], [card["id"] for card in cards]
            )
            latest_session_review = self._get_latest_flashcard_session_review_sync(conn, row["id"])
        return self._serialize_flashcard_deck(
            row,
            cards=cards,
            summary=summary,
            latest_session_review=latest_session_review,
        )

    async def find_flashcard_deck_by_fingerprint(self, generation_fingerprint: str, tester_id: str | None = None) -> dict[str, Any] | None:
        return await self._run(self._find_flashcard_deck_by_fingerprint_sync, generation_fingerprint, tester_id)

    def _get_flashcard_deck_sync(self, deck_id: str, tester_id: str | None = None) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM flashcard_decks WHERE id = ? AND (? IS NULL OR tester_id = ?)",
                (deck_id, tester_id, tester_id),
            ).fetchone()
            if row is None:
                return None
            cards = [
                self._serialize_flashcard_card(card_row)
                for card_row in conn.execute(
                    "SELECT * FROM flashcard_cards WHERE deck_id = ? ORDER BY display_order ASC, id ASC",
                    (deck_id,),
                ).fetchall()
            ]
            summary = self._build_flashcard_summary_sync(
                conn, deck_id, [card["id"] for card in cards]
            )
            latest_session_review = self._get_latest_flashcard_session_review_sync(conn, deck_id)
        return self._serialize_flashcard_deck(
            row,
            cards=cards,
            summary=summary,
            latest_session_review=latest_session_review,
        )

    async def get_flashcard_deck(self, deck_id: str, tester_id: str | None = None) -> dict[str, Any] | None:
        return await self._run(self._get_flashcard_deck_sync, deck_id, tester_id)

    def _list_flashcard_decks_sync(self, limit: int = 20, offset: int = 0, tester_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM flashcard_decks
                WHERE (? IS NULL OR tester_id = ?)
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (tester_id, tester_id, int(limit), int(offset)),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                card_rows = conn.execute(
                    "SELECT id FROM flashcard_cards WHERE deck_id = ? ORDER BY display_order ASC, id ASC",
                    (row["id"],),
                ).fetchall()
                card_ids = [card_row["id"] for card_row in card_rows]
                summary = self._build_flashcard_summary_sync(conn, row["id"], card_ids)
                latest_session_review = self._get_latest_flashcard_session_review_sync(conn, row["id"])
                result.append(
                    self._serialize_flashcard_deck(
                        row,
                        summary=summary,
                        latest_session_review=latest_session_review,
                    )
                )
        return result

    async def list_flashcard_decks(self, limit: int = 20, offset: int = 0, tester_id: str | None = None) -> list[dict[str, Any]]:
        return await self._run(self._list_flashcard_decks_sync, limit, offset, tester_id)

    def _record_flashcard_review_sync(self, deck_id: str, card_id: str, rating: str, tester_id: str | None = None) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            deck = conn.execute(
                "SELECT id FROM flashcard_decks WHERE id = ? AND (? IS NULL OR tester_id = ?)",
                (deck_id, tester_id, tester_id),
            ).fetchone()
            if deck is None:
                raise ValueError(f"Flashcard deck not found: {deck_id}")
            card = conn.execute(
                "SELECT id FROM flashcard_cards WHERE deck_id = ? AND id = ?",
                (deck_id, card_id),
            ).fetchone()
            if card is None:
                raise ValueError(f"Flashcard card not found: {card_id}")
            conn.execute(
                """
                INSERT INTO flashcard_reviews (deck_id, card_id, rating, reviewed_at)
                VALUES (?, ?, ?, ?)
                """,
                (deck_id, card_id, rating, now),
            )
            conn.execute(
                "UPDATE flashcard_decks SET updated_at = ?, last_reviewed_at = ? WHERE id = ?",
                (now, now, deck_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM flashcard_decks WHERE id = ?", (deck_id,)).fetchone()
            cards = [
                self._serialize_flashcard_card(card_row)
                for card_row in conn.execute(
                    "SELECT * FROM flashcard_cards WHERE deck_id = ? ORDER BY display_order ASC, id ASC",
                    (deck_id,),
                ).fetchall()
            ]
            summary = self._build_flashcard_summary_sync(
                conn, deck_id, [item["id"] for item in cards]
            )
            latest_session_review = self._get_latest_flashcard_session_review_sync(conn, deck_id)
        if row is None:
            raise ValueError(f"Flashcard deck not found: {deck_id}")
        return self._serialize_flashcard_deck(
            row,
            cards=cards,
            summary=summary,
            latest_session_review=latest_session_review,
        )

    async def record_flashcard_review(self, deck_id: str, card_id: str, rating: str, tester_id: str | None = None) -> dict[str, Any]:
        return await self._run(self._record_flashcard_review_sync, deck_id, card_id, rating, tester_id)

    def _reset_flashcard_reviews_sync(self, deck_id: str, tester_id: str | None = None) -> dict[str, Any]:
        with self._connect() as conn:
            deck = conn.execute(
                "SELECT id FROM flashcard_decks WHERE id = ? AND (? IS NULL OR tester_id = ?)",
                (deck_id, tester_id, tester_id),
            ).fetchone()
            if deck is None:
                raise ValueError(f"Flashcard deck not found: {deck_id}")
            conn.execute("DELETE FROM flashcard_reviews WHERE deck_id = ?", (deck_id,))
            conn.execute(
                "UPDATE flashcard_decks SET updated_at = ?, last_reviewed_at = NULL WHERE id = ?",
                (time.time(), deck_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM flashcard_decks WHERE id = ?", (deck_id,)).fetchone()
            cards = [
                self._serialize_flashcard_card(card_row)
                for card_row in conn.execute(
                    "SELECT * FROM flashcard_cards WHERE deck_id = ? ORDER BY display_order ASC, id ASC",
                    (deck_id,),
                ).fetchall()
            ]
            summary = self._build_flashcard_summary_sync(
                conn, deck_id, [item["id"] for item in cards]
            )
            latest_session_review = self._get_latest_flashcard_session_review_sync(conn, deck_id)
        if row is None:
            raise ValueError(f"Flashcard deck not found: {deck_id}")
        return self._serialize_flashcard_deck(
            row,
            cards=cards,
            summary=summary,
            latest_session_review=latest_session_review,
        )

    async def reset_flashcard_reviews(self, deck_id: str, tester_id: str | None = None) -> dict[str, Any]:
        return await self._run(self._reset_flashcard_reviews_sync, deck_id, tester_id)

    def _save_flashcard_session_review_sync(self, payload: dict[str, Any], tester_id: str | None = None) -> dict[str, Any]:
        now = time.time()
        deck_id = str(payload.get("deck_id") or "").strip()
        if not deck_id:
            raise ValueError("deck_id is required")
        review_id = str(payload.get("id") or f"flashcard_review_{int(now * 1000)}_{uuid.uuid4().hex[:8]}")
        review_mode = str(payload.get("review_mode") or "full_deck").strip() or "full_deck"
        card_ids = payload.get("card_ids")
        strengths = payload.get("analysis_strengths")
        weak_spots = payload.get("analysis_weak_spots")
        focus_topics = payload.get("analysis_focus_topics")
        if not isinstance(card_ids, list):
            card_ids = []
        if not isinstance(strengths, list):
            strengths = []
        if not isinstance(weak_spots, list):
            weak_spots = []
        if not isinstance(focus_topics, list):
            focus_topics = []

        with self._connect() as conn:
            deck = conn.execute(
                "SELECT id FROM flashcard_decks WHERE id = ? AND (? IS NULL OR tester_id = ?)",
                (deck_id, tester_id, tester_id),
            ).fetchone()
            if deck is None:
                raise ValueError(f"Flashcard deck not found: {deck_id}")
            conn.execute(
                """
                INSERT INTO flashcard_session_reviews (
                    id, deck_id, review_mode, card_ids_json, cards_reviewed,
                    got_it_count, missed_count, skipped_count, analysis_summary,
                    analysis_strengths_json, analysis_weak_spots_json,
                    analysis_recommended_next_step, analysis_focus_topics_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    deck_id,
                    review_mode,
                    _json_dumps(card_ids),
                    int(payload.get("cards_reviewed") or 0),
                    int(payload.get("got_it_count") or 0),
                    int(payload.get("missed_count") or 0),
                    int(payload.get("skipped_count") or 0),
                    str(payload.get("analysis_summary") or ""),
                    _json_dumps(strengths),
                    _json_dumps(weak_spots),
                    str(payload.get("analysis_recommended_next_step") or ""),
                    _json_dumps(focus_topics),
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM flashcard_session_reviews WHERE id = ?",
                (review_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Failed to save flashcard session review")
        return self._serialize_flashcard_session_review(row)

    async def save_flashcard_session_review(self, payload: dict[str, Any], tester_id: str | None = None) -> dict[str, Any]:
        return await self._run(self._save_flashcard_session_review_sync, payload, tester_id)

    def _update_session_title_sync(self, session_id: str, title: str, tester_id: str | None = None) -> bool:
        clauses = ["id = ?"]
        params: list[Any] = [(title.strip() or "New conversation")[:100], time.time(), session_id]
        if tester_id:
            clauses.append("tester_id = ?")
            params.append(tester_id)
        with self._connect() as conn:
            cur = conn.execute(
                f"""
                UPDATE sessions
                SET title = ?, updated_at = ?
                WHERE {" AND ".join(clauses)}
                """,
                params,
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_session_title(self, session_id: str, title: str, tester_id: str | None = None) -> bool:
        return await self._run(self._update_session_title_sync, session_id, title, tester_id)

    def _delete_session_sync(self, session_id: str, tester_id: str | None = None) -> bool:
        clauses = ["id = ?"]
        params: list[Any] = [session_id]
        if tester_id:
            clauses.append("tester_id = ?")
            params.append(tester_id)
        with self._connect() as conn:
            cur = conn.execute(f"DELETE FROM sessions WHERE {' AND '.join(clauses)}", params)
            conn.commit()
        return cur.rowcount > 0

    async def delete_session(self, session_id: str, tester_id: str | None = None) -> bool:
        return await self._run(self._delete_session_sync, session_id, tester_id)

    def _add_message_sync(
        self,
        session_id: str,
        role: str,
        content: str,
        capability: str = "",
        events: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> int:
        now = time.time()
        with self._connect() as conn:
            session = conn.execute("SELECT id, title FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise ValueError(f"Session not found: {session_id}")

            cur = conn.execute(
                """
                INSERT INTO messages (
                    session_id, role, content, capability, events_json, attachments_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    content or "",
                    capability or "",
                    _json_dumps(events or []),
                    _json_dumps(attachments or []),
                    now,
                ),
            )

            title = None
            if session["title"] == "New conversation" and role == "user":
                trimmed = (content or "").strip()
                if trimmed:
                    title = trimmed[:50] + ("..." if len(trimmed) > 50 else "")

            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            if title:
                conn.execute(
                    "UPDATE sessions SET title = ? WHERE id = ?",
                    (title, session_id),
                )
            conn.commit()
            return int(cur.lastrowid)

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        capability: str = "",
        events: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> int:
        return await self._run(
            self._add_message_sync,
            session_id,
            role,
            content,
            capability,
            events,
            attachments,
        )

    def _serialize_message(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "capability": row["capability"] or "",
            "events": _json_loads(row["events_json"], []),
            "attachments": _json_loads(row["attachments_json"], []),
            "created_at": row["created_at"],
        }

    def _get_messages_sync(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, role, content, capability, events_json, attachments_json, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        return [self._serialize_message(row) for row in rows]

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        return await self._run(self._get_messages_sync, session_id)

    def _get_messages_for_context_sync(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, role, content
                FROM messages
                WHERE session_id = ?
                  AND role IN ('user', 'assistant', 'system')
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            {"id": row["id"], "role": row["role"], "content": row["content"] or ""}
            for row in rows
        ]

    async def get_messages_for_context(self, session_id: str) -> list[dict[str, Any]]:
        return await self._run(self._get_messages_for_context_sync, session_id)

    def _list_sessions_sync(
        self,
        limit: int = 50,
        offset: int = 0,
        tester_id: str | None = None,
    ) -> list[dict[str, Any]]:
        where_sql = "WHERE s.tester_id = ?" if tester_id else ""
        params: list[Any] = []
        if tester_id:
            params.append(tester_id)
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    s.id,
                    s.tester_id,
                    s.title,
                    s.created_at,
                    s.updated_at,
                    s.compressed_summary,
                    s.summary_up_to_msg_id,
                    s.preferences_json,
                    COUNT(m.id) AS message_count,
                    COALESCE(
                        (
                            SELECT t.status
                            FROM turns t
                            WHERE t.session_id = s.id
                            ORDER BY t.updated_at DESC
                            LIMIT 1
                        ),
                        'idle'
                    ) AS status,
                    COALESCE(
                        (
                            SELECT t.id
                            FROM turns t
                            WHERE t.session_id = s.id AND t.status = 'running'
                            ORDER BY t.updated_at DESC
                            LIMIT 1
                        ),
                        ''
                    ) AS active_turn_id,
                    COALESCE(
                        (
                            SELECT t.capability
                            FROM turns t
                            WHERE t.session_id = s.id
                            ORDER BY t.updated_at DESC
                            LIMIT 1
                        ),
                        ''
                    ) AS capability,
                    COALESCE(
                        (
                            SELECT m2.content
                            FROM messages m2
                            WHERE m2.session_id = s.id
                              AND TRIM(COALESCE(m2.content, '')) != ''
                            ORDER BY m2.id DESC
                            LIMIT 1
                        ),
                        ''
                    ) AS last_message
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.id
                {where_sql}
                GROUP BY s.id
                ORDER BY s.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        sessions = []
        for row in rows:
            payload = dict(row)
            payload["session_id"] = payload["id"]
            payload["preferences"] = _json_loads(payload.pop("preferences_json", ""), {})
            sessions.append(payload)
        return sessions

    async def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
        tester_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self._run(self._list_sessions_sync, limit, offset, tester_id)

    def _update_summary_sync(self, session_id: str, summary: str, up_to_msg_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE sessions
                SET compressed_summary = ?, summary_up_to_msg_id = ?, updated_at = updated_at
                WHERE id = ?
                """,
                (summary, max(0, int(up_to_msg_id)), session_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_summary(self, session_id: str, summary: str, up_to_msg_id: int) -> bool:
        return await self._run(self._update_summary_sync, session_id, summary, up_to_msg_id)

    def _update_session_preferences_sync(self, session_id: str, preferences: dict[str, Any]) -> bool:
        with self._connect() as conn:
            current = conn.execute(
                "SELECT preferences_json FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if current is None:
                return False
            merged = {
                **_json_loads(current["preferences_json"], {}),
                **(preferences or {}),
            }
            cur = conn.execute(
                """
                UPDATE sessions
                SET preferences_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (_json_dumps(merged), time.time(), session_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_session_preferences(self, session_id: str, preferences: dict[str, Any]) -> bool:
        return await self._run(self._update_session_preferences_sync, session_id, preferences)

    async def get_session_with_messages(
        self,
        session_id: str,
        tester_id: str | None = None,
    ) -> dict[str, Any] | None:
        session = await self.get_session(session_id, tester_id=tester_id)
        if session is None:
            return None
        session["messages"] = await self.get_messages(session_id)
        session["active_turns"] = await self.list_active_turns(session_id)
        return session

    # ── Notebook entries ──────────────────────────────────────────────

    def _upsert_notebook_entries_sync(
        self, session_id: str, items: list[dict[str, Any]]
    ) -> int:
        if not items:
            return 0
        now = time.time()
        with self._connect() as conn:
            session = conn.execute("SELECT id, tester_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise ValueError(f"Session not found: {session_id}")
            tester_id = session["tester_id"] or DEFAULT_TESTER_ID
            upserted = 0
            for item in items:
                question = (item.get("question") or "").strip()
                question_id = (item.get("question_id") or "").strip()
                if not question or not question_id:
                    continue
                conn.execute(
                    """
                    INSERT INTO notebook_entries (
                        tester_id, session_id, question_id, question, question_type,
                        options_json, correct_answer, explanation, difficulty,
                        user_answer, is_correct, bookmarked, followup_session_id,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?)
                    ON CONFLICT(session_id, question_id) DO UPDATE SET
                        user_answer = excluded.user_answer,
                        is_correct = excluded.is_correct,
                        updated_at = excluded.updated_at
                    """,
                    (
                        tester_id,
                        session_id,
                        question_id,
                        question,
                        item.get("question_type") or "",
                        _json_dumps(item.get("options") or {}),
                        item.get("correct_answer") or "",
                        item.get("explanation") or "",
                        item.get("difficulty") or "",
                        item.get("user_answer") or "",
                        1 if item.get("is_correct") else 0,
                        now,
                        now,
                    ),
                )
                upserted += 1
            conn.commit()
        return upserted

    async def upsert_notebook_entries(
        self, session_id: str, items: list[dict[str, Any]]
    ) -> int:
        return await self._run(self._upsert_notebook_entries_sync, session_id, items)

    @staticmethod
    def _serialize_notebook_entry(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "tester_id": row["tester_id"] if "tester_id" in row.keys() else DEFAULT_TESTER_ID,
            "session_id": row["session_id"],
            "session_title": row["session_title"] or "" if "session_title" in row.keys() else "",
            "question_id": row["question_id"] or "",
            "question": row["question"],
            "question_type": row["question_type"] or "",
            "options": _json_loads(row["options_json"], {}),
            "correct_answer": row["correct_answer"] or "",
            "explanation": row["explanation"] or "",
            "difficulty": row["difficulty"] or "",
            "user_answer": row["user_answer"] or "",
            "is_correct": bool(row["is_correct"]),
            "bookmarked": bool(row["bookmarked"]),
            "followup_session_id": row["followup_session_id"] or "",
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def _list_notebook_entries_sync(
        self,
        category_id: int | None,
        bookmarked: bool | None,
        is_correct: bool | None,
        limit: int,
        offset: int,
        tester_id: str | None = None,
    ) -> dict[str, Any]:
        base = """
            SELECT
                n.id, n.tester_id, n.session_id, COALESCE(s.title, '') AS session_title,
                n.question_id, n.question, n.question_type, n.options_json,
                n.correct_answer, n.explanation, n.difficulty,
                n.user_answer, n.is_correct, n.bookmarked,
                n.followup_session_id, n.created_at, n.updated_at
            FROM notebook_entries n
            LEFT JOIN sessions s ON s.id = n.session_id
        """
        count_base = "SELECT COUNT(*) AS cnt FROM notebook_entries n"
        conditions: list[str] = []
        params: list[Any] = []
        if category_id is not None:
            join = " INNER JOIN notebook_entry_categories ec ON ec.entry_id = n.id"
            base += join
            count_base += join
            conditions.append("ec.category_id = ?")
            params.append(category_id)
        if bookmarked is not None:
            conditions.append("n.bookmarked = ?")
            params.append(1 if bookmarked else 0)
        if is_correct is not None:
            conditions.append("n.is_correct = ?")
            params.append(1 if is_correct else 0)
        if tester_id:
            conditions.append("n.tester_id = ?")
            params.append(tester_id)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        with self._connect() as conn:
            total_row = conn.execute(count_base + where, tuple(params)).fetchone()
            total = int(total_row["cnt"]) if total_row else 0
            rows = conn.execute(
                base + where + " ORDER BY n.created_at DESC LIMIT ? OFFSET ?",
                tuple(params) + (limit, offset),
            ).fetchall()
        items = [self._serialize_notebook_entry(r) for r in rows]
        return {"items": items, "total": total}

    async def list_notebook_entries(
        self,
        category_id: int | None = None,
        bookmarked: bool | None = None,
        is_correct: bool | None = None,
        limit: int = 50,
        offset: int = 0,
        tester_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run(
            self._list_notebook_entries_sync,
            category_id, bookmarked, is_correct, limit, offset, tester_id,
        )

    def _get_notebook_entry_sync(self, entry_id: int, tester_id: str | None = None) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    n.*, COALESCE(s.title, '') AS session_title
                FROM notebook_entries n
                LEFT JOIN sessions s ON s.id = n.session_id
                WHERE n.id = ? AND (? IS NULL OR n.tester_id = ?)
                """,
                (entry_id, tester_id, tester_id),
            ).fetchone()
            if row is None:
                return None
            entry = self._serialize_notebook_entry(row)
            cats = conn.execute(
                """
                SELECT c.id, c.name
                FROM notebook_categories c
                INNER JOIN notebook_entry_categories ec ON ec.category_id = c.id
                WHERE ec.entry_id = ?
                ORDER BY c.name
                """,
                (entry_id,),
            ).fetchall()
            entry["categories"] = [{"id": c["id"], "name": c["name"]} for c in cats]
        return entry

    async def get_notebook_entry(self, entry_id: int, tester_id: str | None = None) -> dict[str, Any] | None:
        return await self._run(self._get_notebook_entry_sync, entry_id, tester_id)

    def _find_notebook_entry_sync(self, session_id: str, question_id: str, tester_id: str | None = None) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT n.*, COALESCE(s.title, '') AS session_title
                FROM notebook_entries n
                LEFT JOIN sessions s ON s.id = n.session_id
                WHERE n.session_id = ? AND n.question_id = ? AND (? IS NULL OR n.tester_id = ?)
                """,
                (session_id, question_id, tester_id, tester_id),
            ).fetchone()
        if row is None:
            return None
        return self._serialize_notebook_entry(row)

    async def find_notebook_entry(self, session_id: str, question_id: str, tester_id: str | None = None) -> dict[str, Any] | None:
        return await self._run(self._find_notebook_entry_sync, session_id, question_id, tester_id)

    def _update_notebook_entry_sync(
        self, entry_id: int, updates: dict[str, Any], tester_id: str | None = None
    ) -> bool:
        allowed = {"bookmarked", "followup_session_id", "user_answer", "is_correct"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return False
        fields["updated_at"] = time.time()
        if "bookmarked" in fields:
            fields["bookmarked"] = 1 if fields["bookmarked"] else 0
        if "is_correct" in fields:
            fields["is_correct"] = 1 if fields["is_correct"] else 0
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [entry_id]
        where = "id = ?"
        if tester_id:
            where += " AND tester_id = ?"
            values.append(tester_id)
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE notebook_entries SET {set_clause} WHERE {where}",
                tuple(values),
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_notebook_entry(self, entry_id: int, updates: dict[str, Any], tester_id: str | None = None) -> bool:
        return await self._run(self._update_notebook_entry_sync, entry_id, updates, tester_id)

    def _delete_notebook_entry_sync(self, entry_id: int, tester_id: str | None = None) -> bool:
        with self._connect() as conn:
            if tester_id:
                cur = conn.execute("DELETE FROM notebook_entries WHERE id = ? AND tester_id = ?", (entry_id, tester_id))
            else:
                cur = conn.execute("DELETE FROM notebook_entries WHERE id = ?", (entry_id,))
            conn.commit()
        return cur.rowcount > 0

    async def delete_notebook_entry(self, entry_id: int, tester_id: str | None = None) -> bool:
        return await self._run(self._delete_notebook_entry_sync, entry_id, tester_id)

    # ── Notebook categories ────────────────────────────────────────

    def _create_category_sync(self, name: str) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO notebook_categories (name, created_at) VALUES (?, ?)",
                (name.strip(), now),
            )
            conn.commit()
        return {"id": int(cur.lastrowid), "name": name.strip(), "created_at": now}

    async def create_category(self, name: str) -> dict[str, Any]:
        return await self._run(self._create_category_sync, name)

    def _list_categories_sync(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.name, c.created_at,
                       COUNT(ec.entry_id) AS entry_count
                FROM notebook_categories c
                LEFT JOIN notebook_entry_categories ec ON ec.category_id = c.id
                GROUP BY c.id
                ORDER BY c.name
                """,
            ).fetchall()
        return [
            {"id": r["id"], "name": r["name"], "created_at": float(r["created_at"]),
             "entry_count": int(r["entry_count"])}
            for r in rows
        ]

    async def list_categories(self) -> list[dict[str, Any]]:
        return await self._run(self._list_categories_sync)

    def _rename_category_sync(self, category_id: int, name: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE notebook_categories SET name = ? WHERE id = ?",
                (name.strip(), category_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def rename_category(self, category_id: int, name: str) -> bool:
        return await self._run(self._rename_category_sync, category_id, name)

    def _delete_category_sync(self, category_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM notebook_categories WHERE id = ?", (category_id,))
            conn.commit()
        return cur.rowcount > 0

    async def delete_category(self, category_id: int) -> bool:
        return await self._run(self._delete_category_sync, category_id)

    def _add_entry_to_category_sync(self, entry_id: int, category_id: int) -> bool:
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO notebook_entry_categories (entry_id, category_id) VALUES (?, ?)",
                    (entry_id, category_id),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return False
        return True

    async def add_entry_to_category(self, entry_id: int, category_id: int) -> bool:
        return await self._run(self._add_entry_to_category_sync, entry_id, category_id)

    def _remove_entry_from_category_sync(self, entry_id: int, category_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM notebook_entry_categories WHERE entry_id = ? AND category_id = ?",
                (entry_id, category_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def remove_entry_from_category(self, entry_id: int, category_id: int) -> bool:
        return await self._run(self._remove_entry_from_category_sync, entry_id, category_id)

    def _get_entry_categories_sync(self, entry_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.name FROM notebook_categories c
                INNER JOIN notebook_entry_categories ec ON ec.category_id = c.id
                WHERE ec.entry_id = ?
                ORDER BY c.name
                """,
                (entry_id,),
            ).fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]

    async def get_entry_categories(self, entry_id: int) -> list[dict[str, Any]]:
        return await self._run(self._get_entry_categories_sync, entry_id)


_instance: SQLiteSessionStore | None = None


def get_sqlite_session_store() -> SQLiteSessionStore:
    global _instance
    if _instance is None:
        _instance = SQLiteSessionStore()
    return _instance


__all__ = ["SQLiteSessionStore", "get_sqlite_session_store"]
