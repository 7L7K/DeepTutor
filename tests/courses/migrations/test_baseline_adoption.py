"""P4-01B baseline adoption and fail-closed legacy-shape checks."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from deeptutor.courses.migrations import runner
from deeptutor.courses.migrations.runner import CourseSchemaMismatchError, ensure_course_schema

from .conftest import build_legacy_database, domain_digest, seed_phase3a_rows


def _receipt(path: Path) -> tuple[int, str, str, str]:
    with sqlite3.connect(path) as conn:
        return tuple(conn.execute(
            "SELECT version, name, checksum_sha256, applied_at_utc FROM schema_migrations"
        ).fetchone())


@pytest.mark.parametrize("include_blueway", [False, True], ids=["course_only", "full"])
def test_exact_legacy_profiles_adopt_without_rewriting_domain_rows(
    tmp_path: Path, include_blueway: bool
) -> None:
    path = tmp_path / "courses.db"
    with build_legacy_database(path, include_blueway=include_blueway) as conn:
        seed_phase3a_rows(conn, include_blueway=include_blueway)
        before = domain_digest(
            conn, ignored_columns={"courses": {"workspace_kind"}}
        )

    assert ensure_course_schema(path) == tuple(range(16))
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        assert domain_digest(
            conn,
            ignored_columns={
                "courses": {"workspace_kind"},
                # Migrations 12 and 13 add nullable identity/authorization
                # columns; the legacy values themselves must remain intact.
                "blueway_course_maps": {"external_term_id"},
                "blueway_records": {"external_term_id"},
            },
        ) == before
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 16
        assert tuple(conn.execute(
            "SELECT id, revision, write_epoch, managed_kb_ref, workspace_kind FROM courses"
        ).fetchone()) == (
            "crs_fixture", 3, 2, "personal:kb:fixture", "academic_course"
        )
        if include_blueway:
            assert tuple(conn.execute(
                "SELECT connection_id, course_id, remote_hash FROM blueway_course_maps"
            ).fetchone()) == ("bwc_fixture", "crs_fixture", "remote_hash")
            assert tuple(conn.execute(
                "SELECT payload_json, current_source_id FROM blueway_records"
            ).fetchone()) == ('{"score":91}', "src_fixture")
        else:
            assert conn.execute("SELECT COUNT(*) FROM blueway_connections").fetchone()[0] == 0


def test_fresh_and_adopted_manifests_converge_and_replay_guard_remains_effective(
    tmp_path: Path,
) -> None:
    fresh = tmp_path / "fresh.db"
    upgraded = tmp_path / "upgraded.db"
    ensure_course_schema(fresh)
    with build_legacy_database(upgraded, include_blueway=False) as conn:
        seed_phase3a_rows(conn, include_blueway=False)
    ensure_course_schema(upgraded)

    with sqlite3.connect(fresh) as fresh_conn, sqlite3.connect(upgraded) as upgraded_conn:
        fresh_conn.row_factory = sqlite3.Row
        upgraded_conn.row_factory = sqlite3.Row
        assert runner._schema_signature(fresh_conn, include_ledger=True) == runner._schema_signature(
            upgraded_conn, include_ledger=True
        )
        upgraded_conn.execute(
            """INSERT INTO blueway_connections
               (id, owner_user_id, external_subject, state, scope_version, revision,
                grant_generation, credential_status, created_at, updated_at)
               VALUES ('bwc_guard', 'owner_guard', 'subject_guard', 'active', 'phase3a',
                       1, 1, 'healthy', 1.0, 1.0)"""
        )
        for run_id in ("run_one", "run_two"):
            if run_id == "run_two":
                with pytest.raises(sqlite3.IntegrityError):
                    upgraded_conn.execute(
                        """INSERT INTO blueway_sync_runs
                           (id, connection_id, expected_generation, snapshot_id,
                            snapshot_sha256, state, attempt_count, counts_json,
                            created_at, updated_at, completed_at)
                           VALUES (?, 'bwc_guard', 1, 'snapshot_guard', 'hash',
                                   'completed', 1, '{}', 1.0, 1.0, 1.0)""",
                        (run_id,),
                    )
                break
            upgraded_conn.execute(
                """INSERT INTO blueway_sync_runs
                   (id, connection_id, expected_generation, snapshot_id, snapshot_sha256,
                    state, attempt_count, counts_json, created_at, updated_at, completed_at)
                   VALUES (?, 'bwc_guard', 1, 'snapshot_guard', 'hash', 'completed',
                           1, '{}', 1.0, 1.0, 1.0)""",
                (run_id,),
            )


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("CREATE TABLE courses (id TEXT PRIMARY KEY)", "missing table blueway_connections"),
        ("CREATE TABLE unexpected_managed_shape (id TEXT)", "unexpected table unexpected_managed_shape"),
        ("CREATE TABLE third_party_cache (id TEXT)", "unexpected table third_party_cache"),
    ],
    ids=["partial_core", "unknown_managed", "unallowlisted_unmanaged"],
)
def test_partial_and_unknown_ledger_free_shapes_fail_closed_without_writes(
    tmp_path: Path, statement: str, expected: str
) -> None:
    path = tmp_path / "courses.db"
    with sqlite3.connect(path) as conn:
        conn.execute(statement)
        before = list(conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ))

    with pytest.raises(CourseSchemaMismatchError, match="no changes were made") as error:
        ensure_course_schema(path)
    assert expected in str(error.value)
    with sqlite3.connect(path) as conn:
        after = list(conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ))
    assert after == before


def test_managed_name_collision_is_a_bounded_fail_closed_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "courses.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE courses (id TEXT PRIMARY KEY, surprise TEXT)")

    with pytest.raises(CourseSchemaMismatchError, match="no changes were made") as error:
        ensure_course_schema(path)
    assert "courses" in str(error.value)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()[0] == 0


def test_generated_hidden_column_drift_fails_before_rewriting_the_receipt(tmp_path: Path) -> None:
    path = tmp_path / "courses.db"
    ensure_course_schema(path)
    receipt = _receipt(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """ALTER TABLE courses ADD COLUMN generated_title TEXT
               GENERATED ALWAYS AS (lower(title)) VIRTUAL"""
        )

    with pytest.raises(CourseSchemaMismatchError, match="unexpected column generated_title"):
        ensure_course_schema(path)
    assert _receipt(path) == receipt


def test_unknown_view_drift_fails_before_rewriting_the_receipt(tmp_path: Path) -> None:
    path = tmp_path / "courses.db"
    ensure_course_schema(path)
    receipt = _receipt(path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE VIEW unreviewed_course_view AS SELECT id FROM courses")

    with pytest.raises(CourseSchemaMismatchError, match="view definitions mismatch"):
        ensure_course_schema(path)
    assert _receipt(path) == receipt


def test_view_only_database_is_not_mistaken_for_an_empty_profile(tmp_path: Path) -> None:
    path = tmp_path / "courses.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE VIEW leftover_view AS SELECT 1 AS value")

    with pytest.raises(CourseSchemaMismatchError, match="Unrecognized Course database schema"):
        ensure_course_schema(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'view' AND name = 'leftover_view'"
        ).fetchone()[0] == 1


def test_expression_index_term_collation_and_order_drift_fails_before_receipt_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "courses.db"
    ensure_course_schema(path)
    receipt = _receipt(path)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP INDEX idx_courses_owner_updated")
        conn.execute(
            """CREATE INDEX idx_courses_owner_updated
               ON courses(lower(owner_user_id) COLLATE NOCASE DESC, updated_at ASC)"""
        )
        conn.row_factory = sqlite3.Row
        signature = runner._schema_signature(conn, include_ledger=True)

    index = next(
        item
        for item in signature["tables"]["courses"]["named_indexes"]
        if item["name"] == "idx_courses_owner_updated"
    )
    assert index["key_terms"] == [
        {"cid": -2, "name": None, "order": "DESC", "collation": "NOCASE"},
        {"cid": 8, "name": "updated_at", "order": "ASC", "collation": "BINARY"},
    ]

    with pytest.raises(CourseSchemaMismatchError, match="named_indexes mismatch"):
        ensure_course_schema(path)
    assert _receipt(path) == receipt


def test_explicit_column_collation_drift_fails_before_rewriting_the_receipt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "courses.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(runner.discover_migrations()[0].content.decode("utf-8"))
        conn.execute("DROP TABLE schema_migrations")
        conn.executescript(
            """PRAGMA foreign_keys = OFF;
               DROP INDEX idx_courses_owner_updated;
               CREATE TABLE courses_rebuilt (
                   id TEXT PRIMARY KEY,
                   owner_user_id TEXT NOT NULL,
                   title TEXT NOT NULL COLLATE "NOCASE",
                   state TEXT NOT NULL CHECK (state IN ('active', 'archived')),
                   revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
                   write_epoch INTEGER NOT NULL DEFAULT 1 CHECK (write_epoch >= 1),
                   managed_kb_ref TEXT,
                   created_at REAL NOT NULL,
                   updated_at REAL NOT NULL,
                   archived_at REAL
               );
               DROP TABLE courses;
               ALTER TABLE courses_rebuilt RENAME TO courses;
               CREATE INDEX idx_courses_owner_updated
                   ON courses(owner_user_id, updated_at DESC);
               PRAGMA foreign_keys = ON;"""
        )

    with pytest.raises(CourseSchemaMismatchError, match="explicit_collations mismatch"):
        ensure_course_schema(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()[0] == 0


def test_checked_in_phase3a_manifest_matches_effective_baseline_authority() -> None:
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads(
        (root / "docs/contracts/teeechr_phase3a_courses_schema_manifest.json").read_text()
    )
    signature = runner._expected_signature(runner.discover_migrations()[:1])
    tables = {
        name: value
        for name, value in signature["tables"].items()
        if name != "schema_migrations"
    }

    assert manifest["canonical_profile"] == "phase3a_course_plus_blueway"
    assert set(tables) == set(manifest["tables"])
    for table, authority in manifest["tables"].items():
        actual_columns = sorted(
            [
                [
                    column["name"],
                    column["type"],
                    column["notnull"],
                    column["default"],
                    column["pk"],
                ]
                for column in tables[table]["columns"]
            ]
        )
        assert actual_columns == sorted(authority["columns"])
        actual_foreign_keys = sorted(
            [
                [
                    foreign_key["from"],
                    foreign_key["table"],
                    foreign_key["to"],
                    foreign_key["on_update"],
                    foreign_key["on_delete"],
                ]
                for foreign_key in tables[table]["foreign_keys"]
            ]
        )
        assert actual_foreign_keys == sorted(authority["foreign_keys"])

    effective_indexes = {
        index["name"]: {
            "table": table,
            "unique": index["unique"],
            "columns": [
                [term["name"], term["order"]]
                for term in index["key_terms"]
            ],
            "where": index["where"],
        }
        for table, details in tables.items()
        for index in details["named_indexes"]
    }
    assert set(effective_indexes) == set(manifest["named_indexes"])
    for name, authority in manifest["named_indexes"].items():
        actual = effective_indexes[name]
        assert actual["table"] == authority["table"]
        assert actual["unique"] == authority["unique"]
        assert actual["columns"] == authority["columns"]
        expected_where = authority["where"]
        assert actual["where"] == (
            runner._normalize_sql(expected_where) if expected_where is not None else None
        )
