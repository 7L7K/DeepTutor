from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

import pytest

from deeptutor.historical_migration.models import DryRunDestinations
from deeptutor.historical_migration.scanner import (
    HistoricalMigrationError,
    HistoricalMigrationScanner,
    SOURCE_ENV,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_legacy_database(path: Path) -> Path:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys=OFF;
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                tester_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL
            );
            CREATE TABLE practice_attempts (
                id TEXT PRIMARY KEY,
                tester_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE practice_attempt_items (
                id INTEGER PRIMARY KEY,
                attempt_id TEXT NOT NULL
            );
            CREATE TABLE flashcard_decks (
                id TEXT PRIMARY KEY,
                tester_id TEXT NOT NULL,
                title TEXT NOT NULL
            );
            CREATE TABLE flashcard_cards (
                id TEXT PRIMARY KEY,
                deck_id TEXT NOT NULL,
                front TEXT NOT NULL,
                back TEXT NOT NULL
            );
            CREATE TABLE flashcard_reviews (
                id INTEGER PRIMARY KEY,
                deck_id TEXT NOT NULL,
                card_id TEXT NOT NULL,
                rating TEXT NOT NULL
            );
            CREATE TABLE flashcard_session_reviews (
                id TEXT PRIMARY KEY,
                deck_id TEXT NOT NULL
            );

            INSERT INTO sessions VALUES ('alice-session','alice','Private title',1,2);
            INSERT INTO sessions VALUES ('bob-session','bob','Other private title',1,2);
            INSERT INTO messages VALUES (1,'alice-session','user','Private learner text');
            INSERT INTO messages VALUES (2,'missing-session','user','Orphan private text');
            INSERT INTO practice_attempts VALUES ('alice-attempt','alice','alice-session','completed');
            INSERT INTO practice_attempts VALUES ('bad-attempt','alice','alice-session','unknown');
            INSERT INTO practice_attempt_items VALUES (1,'alice-attempt');
            INSERT INTO practice_attempt_items VALUES (2,'missing-attempt');
            INSERT INTO practice_attempt_items VALUES (3,'bad-attempt');
            INSERT INTO flashcard_decks VALUES ('alice-deck','alice','Private deck title');
            INSERT INTO flashcard_cards VALUES ('alice-card','alice-deck','Private front','Private back');
            INSERT INTO flashcard_cards VALUES ('orphan-card','missing-deck','Orphan front','Orphan back');
            INSERT INTO flashcard_reviews VALUES (1,'alice-deck','alice-card','good');
            INSERT INTO flashcard_reviews VALUES (2,'alice-deck','missing-card','good');
            INSERT INTO flashcard_session_reviews VALUES ('review-session','alice-deck');
            """
        )
    return path


@pytest.fixture
def legacy_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = build_legacy_database(tmp_path / "legacy.db")
    monkeypatch.setenv(SOURCE_ENV, str(path))
    return path


def test_source_discovery_is_opaque_and_read_only(legacy_db: Path) -> None:
    before = _sha(legacy_db)
    sources = HistoricalMigrationScanner().list_sources()

    assert len(sources) == 1
    source = sources[0]
    assert source.compatible is True
    assert len(source.owners) == 2
    serialized = source.model_dump_json()
    assert "alice" not in serialized
    assert "bob" not in serialized
    assert "Private" not in serialized
    assert str(legacy_db) not in serialized
    assert _sha(legacy_db) == before


def test_dry_run_requires_destinations_and_classifies_orphans(legacy_db: Path) -> None:
    scanner = HistoricalMigrationScanner()
    source = scanner.list_sources()[0]
    alice = next(owner for owner in source.owners if owner.session_count == 1 and owner.practice_attempt_count == 2)

    report = scanner.dry_run(
        source_id=source.id,
        legacy_owner_designation=alice.designation,
        target_owner_id="target-alice",
        destinations=DryRunDestinations(),
    )
    by_table = {item.table: item for item in report.classifications}

    assert report.zero_write is True
    assert by_table["sessions"].counts.importable == 1
    assert by_table["messages"].counts.importable == 1
    assert by_table["messages"].counts.orphaned == 1
    assert by_table["practice_attempts"].counts.ambiguous == 1
    assert by_table["practice_attempts"].counts.rejected == 1
    assert by_table["practice_attempt_items"].counts.ambiguous == 1
    assert by_table["practice_attempt_items"].counts.orphaned == 1
    assert by_table["practice_attempt_items"].counts.rejected == 1
    assert by_table["flashcard_decks"].counts.ambiguous == 1
    assert by_table["flashcard_cards"].counts.ambiguous == 1
    assert by_table["flashcard_cards"].counts.orphaned == 1
    assert by_table["flashcard_reviews"].counts.ambiguous == 1
    assert by_table["flashcard_reviews"].counts.orphaned == 1
    assert report.required_decisions == [
        "Choose an active academic Course for historical Practice.",
        "Choose General Study or an active Course for historical Flashcards.",
        "Review orphaned child records; they will not be imported.",
        "Review rejected record codes; rejected records remain untouched.",
    ]


def test_destinations_make_only_eligible_records_importable(legacy_db: Path) -> None:
    scanner = HistoricalMigrationScanner()
    source = scanner.list_sources()[0]
    alice = next(owner for owner in source.owners if owner.practice_attempt_count == 2)

    first = scanner.dry_run(
        source_id=source.id,
        legacy_owner_designation=alice.designation,
        target_owner_id="target-alice",
        destinations=DryRunDestinations(
            practice_course_id="crs_science",
            flashcard_workspace_id="crs_general",
        ),
    )
    second = scanner.dry_run(
        source_id=source.id,
        legacy_owner_designation=alice.designation,
        target_owner_id="target-alice",
        destinations=DryRunDestinations(
            practice_course_id="crs_science",
            flashcard_workspace_id="crs_general",
        ),
    )
    by_table = {item.table: item for item in first.classifications}

    assert by_table["practice_attempts"].counts.importable == 1
    assert by_table["practice_attempt_items"].counts.importable == 1
    assert by_table["flashcard_decks"].counts.importable == 1
    assert by_table["flashcard_cards"].counts.importable == 1
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.campaign_id == second.campaign_id


def test_unknown_owner_and_client_path_fail_closed(legacy_db: Path) -> None:
    scanner = HistoricalMigrationScanner()
    source = scanner.list_sources()[0]
    with pytest.raises(HistoricalMigrationError, match="owner selection"):
        scanner.dry_run(
            source_id=source.id,
            legacy_owner_designation="legacy_owner_unknown",
            target_owner_id="target",
            destinations=DryRunDestinations(),
        )


def test_symbolic_link_source_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = build_legacy_database(tmp_path / "source.db")
    link = tmp_path / "linked.db"
    link.symlink_to(source)
    monkeypatch.setenv(SOURCE_ENV, str(link))
    with pytest.raises(HistoricalMigrationError, match="symbolic link"):
        HistoricalMigrationScanner().list_sources()


def test_incomplete_known_schema_is_marked_incompatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "incomplete.db"
    with sqlite3.connect(source) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (id TEXT PRIMARY KEY, tester_id TEXT NOT NULL);
            CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT NOT NULL);
            INSERT INTO sessions VALUES ('session-1', 'owner-1');
            """
        )
    monkeypatch.setenv(SOURCE_ENV, str(source))

    summary = HistoricalMigrationScanner().list_sources()[0]
    assert summary.compatible is False
    assert summary.issue_code == "unsupported_or_empty_legacy_schema"
