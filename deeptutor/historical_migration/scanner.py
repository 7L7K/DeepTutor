"""Read-only classifier for the pre-v1.5.2 learner SQLite store.

The browser never supplies a filesystem path. Sources are selected from a
server-side allowlist, opened with SQLite ``mode=ro`` and ``query_only``, and
re-hashed after every scan. The returned manifest contains counts and opaque
designations only; learner text, credentials, paths, and legacy IDs never leave
this module.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterator

from deeptutor.runtime.home import get_runtime_home

from .models import (
    ClassificationCount,
    DryRunDestinations,
    HistoricalMigrationDryRun,
    HistoricalSourceSummary,
    LegacyOwnerSummary,
    TableClassification,
)

MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
SOURCE_ENV = "TEEECHR_LEGACY_CHAT_DB"
SOURCE_LABEL = "Historical TEEECHR learner database"
SUPPORTED_TABLES = (
    "sessions",
    "messages",
    "practice_attempts",
    "practice_attempt_items",
    "flashcard_decks",
    "flashcard_cards",
    "flashcard_reviews",
    "flashcard_session_reviews",
)
OWNER_TABLES = ("sessions", "practice_attempts", "flashcard_decks")
REQUIRED_COLUMNS = {
    "sessions": {"id", "tester_id"},
    "messages": {"session_id"},
    "practice_attempts": {"id", "tester_id", "session_id", "status"},
    "practice_attempt_items": {"attempt_id"},
    "flashcard_decks": {"id", "tester_id"},
    "flashcard_cards": {"id", "deck_id"},
    "flashcard_reviews": {"deck_id", "card_id"},
    "flashcard_session_reviews": {"deck_id"},
}


class HistoricalMigrationError(RuntimeError):
    """Safe migration failure; messages are suitable for an authenticated UI."""


class HistoricalSourceNotFoundError(HistoricalMigrationError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _opaque(prefix: str, value: str, *, size: int = 16) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:size]}"


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_paths() -> list[Path]:
    configured = os.getenv(SOURCE_ENV, "").strip()
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute():
            raise HistoricalMigrationError(f"{SOURCE_ENV} must be an absolute path")
        return [candidate]
    # Local migration convenience: the preserved pre-v1.5.2 checkout is the
    # sibling ``DeepTutor`` directory. This is discovery only; the client never
    # receives or controls the resolved path.
    return [get_runtime_home().parent / "DeepTutor" / "data" / "user" / "chat_history.db"]


def _validate_source_path(path: Path) -> Path:
    if path.is_symlink():
        raise HistoricalMigrationError("Historical database cannot be a symbolic link")
    try:
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
    except FileNotFoundError as exc:
        raise HistoricalSourceNotFoundError("Historical database was not found") from exc
    if not resolved.is_file():
        raise HistoricalMigrationError("Historical database is not a regular file")
    if stat.st_size <= 0 or stat.st_size > MAX_SOURCE_BYTES:
        raise HistoricalMigrationError("Historical database size is outside the supported range")
    if hasattr(os, "geteuid") and stat.st_uid != os.geteuid():
        raise HistoricalMigrationError("Historical database is owned by another OS account")
    with resolved.open("rb") as handle:
        if handle.read(16) != b"SQLite format 3\x00":
            raise HistoricalMigrationError("Historical source is not a SQLite database")
    return resolved


@contextmanager
def _read_only_connection(path: Path) -> Iterator[sqlite3.Connection]:
    # Path.as_uri percent-encodes query metacharacters in filenames. The only
    # URI query is the server-owned read-only mode below.
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result is None or str(result[0]).lower() != "ok":
            raise HistoricalMigrationError("Historical database integrity check failed")
        yield connection
    finally:
        connection.close()


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if table not in SUPPORTED_TABLES:
        return set()
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _schema_fingerprint(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        """SELECT type,name,tbl_name,COALESCE(sql,'') AS sql
           FROM sqlite_master
           WHERE type IN ('table','index','trigger')
           ORDER BY type,name,tbl_name"""
    ).fetchall()
    return _canonical_hash([list(row) for row in rows])


def _schema_is_compatible(connection: sqlite3.Connection, available: set[str]) -> bool:
    if not {"sessions", "messages"}.issubset(available):
        return False
    return all(
        REQUIRED_COLUMNS[table].issubset(_columns(connection, table))
        for table in available.intersection(REQUIRED_COLUMNS)
    )


def _owner_designation(database_sha256: str, owner_id: str) -> str:
    return _opaque("legacy_owner", f"{database_sha256}:{owner_id}", size=16)


def _safe_count(connection: sqlite3.Connection, table: str, where: str = "", params: tuple = ()) -> int:
    if table not in SUPPORTED_TABLES:
        return 0
    suffix = f" WHERE {where}" if where else ""
    return int(connection.execute(f'SELECT count(*) FROM "{table}"{suffix}', params).fetchone()[0])


def _owners(
    connection: sqlite3.Connection, database_sha256: str, available: set[str]
) -> tuple[list[LegacyOwnerSummary], dict[str, str]]:
    owner_ids: set[str] = set()
    for table in OWNER_TABLES:
        if table in available and "tester_id" in _columns(connection, table):
            owner_ids.update(
                str(row[0])
                for row in connection.execute(
                    f'SELECT DISTINCT tester_id FROM "{table}" WHERE tester_id IS NOT NULL'
                )
                if str(row[0]).strip()
            )
    by_designation = {
        _owner_designation(database_sha256, owner_id): owner_id for owner_id in sorted(owner_ids)
    }
    summaries = []
    for designation, owner_id in sorted(by_designation.items()):
        summaries.append(
            LegacyOwnerSummary(
                designation=designation,
                session_count=_safe_count(connection, "sessions", "tester_id=?", (owner_id,))
                if "sessions" in available
                else 0,
                practice_attempt_count=_safe_count(
                    connection, "practice_attempts", "tester_id=?", (owner_id,)
                )
                if "practice_attempts" in available
                else 0,
                flashcard_deck_count=_safe_count(
                    connection, "flashcard_decks", "tester_id=?", (owner_id,)
                )
                if "flashcard_decks" in available
                else 0,
            )
        )
    return summaries, by_designation


def _classification(
    table: str,
    *,
    importable: int = 0,
    ambiguous: int = 0,
    orphaned: int = 0,
    duplicate: int = 0,
    rejected: int = 0,
    reasons: Counter[str] | None = None,
) -> TableClassification:
    counts = ClassificationCount(
        importable=importable,
        ambiguous=ambiguous,
        orphaned=orphaned,
        duplicate=duplicate,
        rejected=rejected,
    )
    return TableClassification(
        table=table,
        total=sum(counts.model_dump().values()),
        counts=counts,
        reason_codes=dict(sorted((reasons or Counter()).items())),
    )


class HistoricalMigrationScanner:
    """Discover and classify server-approved historical learner databases."""

    def list_sources(self) -> list[HistoricalSourceSummary]:
        sources: list[HistoricalSourceSummary] = []
        for raw_path in _source_paths():
            try:
                path = _validate_source_path(raw_path)
                database_sha256 = _sha256_file(path)
                with _read_only_connection(path) as connection:
                    available = _tables(connection)
                    schema_fingerprint = _schema_fingerprint(connection)
                    owners, _ = _owners(connection, database_sha256, available)
                    compatible = _schema_is_compatible(connection, available) and bool(owners)
                    issue = None if compatible else "unsupported_or_empty_legacy_schema"
                stat = path.stat()
                sources.append(
                    HistoricalSourceSummary(
                        id=_opaque("hms", f"{path}:{database_sha256}"),
                        label=SOURCE_LABEL,
                        size_bytes=stat.st_size,
                        modified_at=stat.st_mtime,
                        database_sha256=database_sha256,
                        schema_fingerprint=schema_fingerprint,
                        compatible=compatible,
                        issue_code=issue,
                        owners=owners,
                    )
                )
            except HistoricalSourceNotFoundError:
                continue
        return sources

    def _resolve_source(self, source_id: str) -> tuple[Path, HistoricalSourceSummary]:
        for source in self.list_sources():
            if source.id == source_id:
                for raw_path in _source_paths():
                    try:
                        path = _validate_source_path(raw_path)
                    except HistoricalSourceNotFoundError:
                        continue
                    if _opaque("hms", f"{path}:{source.database_sha256}") == source.id:
                        return path, source
        raise HistoricalSourceNotFoundError("Historical migration source was not found")

    def dry_run(
        self,
        *,
        source_id: str,
        legacy_owner_designation: str,
        target_owner_id: str,
        destinations: DryRunDestinations,
    ) -> HistoricalMigrationDryRun:
        path, source = self._resolve_source(source_id)
        if not source.compatible:
            raise HistoricalMigrationError("Historical database is not compatible")
        before_sha = _sha256_file(path)
        if before_sha != source.database_sha256:
            raise HistoricalMigrationError("Historical database changed before the dry run")

        with _read_only_connection(path) as connection:
            available = _tables(connection)
            _, owner_map = _owners(connection, before_sha, available)
            owner_id = owner_map.get(legacy_owner_designation)
            if owner_id is None:
                raise HistoricalMigrationError("Legacy owner selection is unavailable")
            classifications = self._classify(
                connection,
                available=available,
                owner_id=owner_id,
                destinations=destinations,
            )
            schema_fingerprint = _schema_fingerprint(connection)

        after_sha = _sha256_file(path)
        if after_sha != before_sha:
            raise HistoricalMigrationError("Historical database changed during the dry run")

        totals_counter: Counter[str] = Counter()
        for item in classifications:
            totals_counter.update(item.counts.model_dump())
        totals = ClassificationCount(**totals_counter)
        decisions: list[str] = []
        if destinations.practice_course_id is None and any(
            item.table.startswith("practice_") and item.total for item in classifications
        ):
            decisions.append("Choose an active academic Course for historical Practice.")
        if destinations.flashcard_workspace_id is None and any(
            item.table.startswith("flashcard_") and item.total for item in classifications
        ):
            decisions.append("Choose General Study or an active Course for historical Flashcards.")
        if totals.orphaned:
            decisions.append("Review orphaned child records; they will not be imported.")
        if totals.rejected:
            decisions.append("Review rejected record codes; rejected records remain untouched.")

        base_payload = {
            "source_id": source.id,
            "source_database_sha256": before_sha,
            "source_schema_fingerprint": schema_fingerprint,
            "target_owner_designation": _opaque("owner", target_owner_id, size=16),
            "legacy_owner_designation": legacy_owner_designation,
            "destinations": destinations.model_dump(),
            "classifications": [item.model_dump() for item in classifications],
            "totals": totals.model_dump(),
            "required_decisions": decisions,
            "warnings": [
                "This report performed no writes.",
                "Legacy scores and mastery remain archival evidence only.",
            ],
            "zero_write": True,
        }
        manifest_sha256 = _canonical_hash(base_payload)
        return HistoricalMigrationDryRun(
            campaign_id=_opaque("hmc", manifest_sha256, size=24),
            manifest_sha256=manifest_sha256,
            **base_payload,
        )

    def _classify(
        self,
        connection: sqlite3.Connection,
        *,
        available: set[str],
        owner_id: str,
        destinations: DryRunDestinations,
    ) -> list[TableClassification]:
        results: list[TableClassification] = []

        session_ids = {
            str(row[0])
            for row in connection.execute(
                "SELECT id FROM sessions WHERE tester_id=?", (owner_id,)
            )
        }
        results.append(
            _classification(
                "sessions",
                importable=len(session_ids),
                reasons=Counter({"course_less_archive": len(session_ids)}) if session_ids else Counter(),
            )
        )

        if "messages" in available:
            owned_messages = int(
                connection.execute(
                    """SELECT count(*) FROM messages
                       JOIN sessions ON sessions.id=messages.session_id
                       WHERE sessions.tester_id=?""",
                    (owner_id,),
                ).fetchone()[0]
            )
            orphan_messages = int(
                connection.execute(
                    """SELECT count(*) FROM messages
                       LEFT JOIN sessions ON sessions.id=messages.session_id
                       WHERE sessions.id IS NULL"""
                ).fetchone()[0]
            )
        else:
            owned_messages = orphan_messages = 0
        results.append(
            _classification(
                "messages",
                importable=owned_messages,
                orphaned=orphan_messages,
                reasons=Counter({"missing_session": orphan_messages}) if orphan_messages else Counter(),
            )
        )

        eligible_attempt_ids: set[str] = set()
        if "practice_attempts" in available:
            rows = connection.execute(
                "SELECT id,session_id,status FROM practice_attempts WHERE tester_id=?",
                (owner_id,),
            ).fetchall()
            eligible_attempt_ids = {
                str(row[0])
                for row in rows
                if str(row[1]) in session_ids
                and str(row[2]) in {"in_progress", "submitted", "graded", "completed"}
            }
            orphaned = sum(1 for row in rows if str(row[1]) not in session_ids)
            invalid = sum(1 for row in rows if str(row[2]) not in {"in_progress", "submitted", "graded", "completed"})
            eligible = max(0, len(rows) - orphaned - invalid)
            ambiguous = eligible if destinations.practice_course_id is None else 0
            importable = eligible if destinations.practice_course_id is not None else 0
            reasons = Counter()
            if ambiguous:
                reasons["practice_destination_required"] = ambiguous
            if orphaned:
                reasons["missing_owned_session"] = orphaned
            if invalid:
                reasons["unsupported_attempt_state"] = invalid
            results.append(
                _classification(
                    "practice_attempts",
                    importable=importable,
                    ambiguous=ambiguous,
                    orphaned=orphaned,
                    rejected=invalid,
                    reasons=reasons,
                )
            )
        else:
            results.append(_classification("practice_attempts"))

        if "practice_attempt_items" in available:
            owned_item_rows = connection.execute(
                """SELECT i.attempt_id FROM practice_attempt_items i
                   JOIN practice_attempts a ON a.id=i.attempt_id
                   WHERE a.tester_id=?""",
                (owner_id,),
            ).fetchall()
            eligible_items = sum(
                1 for row in owned_item_rows if str(row[0]) in eligible_attempt_ids
            )
            rejected_items = len(owned_item_rows) - eligible_items
            orphan_items = int(
                connection.execute(
                    """SELECT count(*) FROM practice_attempt_items i
                       LEFT JOIN practice_attempts a ON a.id=i.attempt_id
                       WHERE a.id IS NULL"""
                ).fetchone()[0]
            )
            results.append(
                _classification(
                    "practice_attempt_items",
                    importable=eligible_items if destinations.practice_course_id else 0,
                    ambiguous=eligible_items if not destinations.practice_course_id else 0,
                    orphaned=orphan_items,
                    rejected=rejected_items,
                    reasons=Counter(
                        {
                            **({"practice_destination_required": eligible_items} if eligible_items and not destinations.practice_course_id else {}),
                            **({"missing_attempt": orphan_items} if orphan_items else {}),
                            **({"ineligible_parent_attempt": rejected_items} if rejected_items else {}),
                        }
                    ),
                )
            )
        else:
            results.append(_classification("practice_attempt_items"))

        deck_ids: set[str] = set()
        if "flashcard_decks" in available:
            deck_ids = {
                str(row[0])
                for row in connection.execute(
                    "SELECT id FROM flashcard_decks WHERE tester_id=?", (owner_id,)
                )
            }
            results.append(
                _classification(
                    "flashcard_decks",
                    importable=len(deck_ids) if destinations.flashcard_workspace_id else 0,
                    ambiguous=len(deck_ids) if not destinations.flashcard_workspace_id else 0,
                    reasons=Counter({"flashcard_destination_required": len(deck_ids)})
                    if deck_ids and not destinations.flashcard_workspace_id
                    else Counter(),
                )
            )
        else:
            results.append(_classification("flashcard_decks"))

        child_specs = (
            ("flashcard_cards", False),
            ("flashcard_reviews", True),
            ("flashcard_session_reviews", False),
        )
        for table, requires_card in child_specs:
            if table not in available:
                results.append(_classification(table))
                continue
            if requires_card:
                owned = int(
                    connection.execute(
                        '''SELECT count(*) FROM flashcard_reviews child
                           JOIN flashcard_decks deck ON deck.id=child.deck_id
                           JOIN flashcard_cards card
                             ON card.id=child.card_id AND card.deck_id=child.deck_id
                           WHERE deck.tester_id=?''',
                        (owner_id,),
                    ).fetchone()[0]
                )
                orphaned = int(
                    connection.execute(
                        '''SELECT count(*) FROM flashcard_reviews child
                           LEFT JOIN flashcard_decks deck ON deck.id=child.deck_id
                           LEFT JOIN flashcard_cards card
                             ON card.id=child.card_id AND card.deck_id=child.deck_id
                           WHERE deck.id IS NULL OR card.id IS NULL'''
                    ).fetchone()[0]
                )
            else:
                owned = int(
                    connection.execute(
                        f'''SELECT count(*) FROM "{table}" child
                            JOIN flashcard_decks deck ON deck.id=child.deck_id
                            WHERE deck.tester_id=?''',
                        (owner_id,),
                    ).fetchone()[0]
                )
                orphaned = int(
                    connection.execute(
                        f'''SELECT count(*) FROM "{table}" child
                            LEFT JOIN flashcard_decks deck ON deck.id=child.deck_id
                            WHERE deck.id IS NULL'''
                    ).fetchone()[0]
                )
            reasons = Counter()
            if owned and not destinations.flashcard_workspace_id:
                reasons["flashcard_destination_required"] = owned
            if orphaned:
                reasons["missing_deck_or_card" if requires_card else "missing_deck"] = orphaned
            results.append(
                _classification(
                    table,
                    importable=owned if destinations.flashcard_workspace_id else 0,
                    ambiguous=owned if not destinations.flashcard_workspace_id else 0,
                    orphaned=orphaned,
                    reasons=reasons,
                )
            )
        return results


__all__ = [
    "HistoricalMigrationError",
    "HistoricalMigrationScanner",
    "HistoricalSourceNotFoundError",
    "MAX_SOURCE_BYTES",
    "SOURCE_ENV",
]
