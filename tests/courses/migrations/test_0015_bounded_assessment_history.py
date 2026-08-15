"""Populated-history and rollback proof for Course migration 0015."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from deeptutor.courses.attempt_repository import CourseAssessmentRepository
from deeptutor.courses.attempt_service import CourseAssessmentService
from deeptutor.courses.content_quality_repository import CourseContentQualityRepository
from deeptutor.courses.content_quality_service import CourseContentQualityService
from deeptutor.courses.grading_repository import CourseGradingRepository
from deeptutor.courses.migrations import runner
from deeptutor.courses.migrations.runner import (
    CourseMigrationError,
    MigrationArtifact,
    ensure_course_schema,
    open_course_connection,
)
from deeptutor.courses.repository import CourseRepository


OWNER = "u_history_owner"
COURSE_ID = "crs_populated_history"
PRACTICE_SET_ID = "pst_populated_history"
REVISION_ID = "psr_populated_history"
ATTEMPT_ID = "att_populated_history"

EVIDENCE_TABLE = "quiz_item_grading_evidence"
INVALIDATION_TABLE = "practice_question_invalidations"
REBUILT_TABLES = (EVIDENCE_TABLE, INVALIDATION_TABLE)

QUESTIONS = (
    {
        "id": "qst_pending_retry",
        "item_id": "qai_pending_retry",
        "evidence_id": "grd_pending_retry",
        "objective_id": "OBJ-PENDING-RETRY",
        "module_id": "mod_cellular_respiration",
        "knowledge_type": "memory",
        "answer": "mitochondrión",
        "response": "mitochondrión",
        "is_correct": True,
        "error_type": None,
        "state": "pending",
    },
    {
        "id": "qst_pending_invalidated_evidence",
        "item_id": "qai_pending_invalidated_evidence",
        "evidence_id": "grd_pending_invalidated_evidence",
        "objective_id": "OBJ-PENDING-INVALIDATED",
        "module_id": "mod_cellular_respiration",
        "knowledge_type": "concept",
        "answer": "oxygen",
        "response": "oxygen",
        "is_correct": True,
        "error_type": None,
        "state": "pending",
    },
    {
        "id": "qst_applied_global_invalidation",
        "item_id": "qai_applied_global_invalidation",
        "evidence_id": "grd_applied_global_invalidation",
        "objective_id": "OBJ-APPLIED-GLOBAL",
        "module_id": "mod_energy_transfer",
        "knowledge_type": "procedure",
        "answer": "ATP",
        "response": "ATP",
        "is_correct": True,
        "error_type": None,
        "state": "applied",
    },
    {
        "id": "qst_unmapped_retained",
        "item_id": "qai_unmapped_retained",
        "evidence_id": "grd_unmapped_retained",
        "objective_id": "OBJ-UNMAPPED",
        "module_id": None,
        "knowledge_type": None,
        "answer": "matrix",
        "response": "cytosol",
        "is_correct": False,
        "error_type": "application",
        "state": "unmapped",
    },
)


def _json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _migrations_through(
    artifacts: tuple[MigrationArtifact, ...], version: int
) -> tuple[MigrationArtifact, ...]:
    """Select a bounded prefix without assuming the discovered tail ends at 0015."""

    selected = tuple(artifact for artifact in artifacts if artifact.version <= version)
    assert tuple(artifact.version for artifact in selected) == tuple(range(version + 1))
    return selected


def _populate_exact_history(conn: sqlite3.Connection) -> None:
    conn.execute(
        """INSERT INTO courses
           (id, owner_user_id, title, state, revision, write_epoch,
            managed_kb_ref, created_at, updated_at, archived_at, workspace_kind)
           VALUES (?, ?, ?, 'active', 1, 1, NULL, 1000.125, 1000.125,
                   NULL, 'academic_course')""",
        (COURSE_ID, OWNER, "Biología: Cellular Respiration"),
    )
    conn.execute(
        """INSERT INTO practice_sets
           (id, owner_user_id, course_id, title, mode, state,
            current_revision_id, revision, write_epoch, created_at, updated_at,
            archived_at)
           VALUES (?, ?, ?, ?, 'manual', 'draft', NULL, 1, 1,
                   1001.25, 1001.25, NULL)""",
        (PRACTICE_SET_ID, OWNER, COURSE_ID, "Exact evidence history"),
    )
    conn.execute(
        """INSERT INTO practice_set_revisions
           (id, practice_set_id, revision_number, state, source_snapshot_json,
            objective_ids_json, generation_receipt_json, created_at, ready_at)
           VALUES (?, ?, 1, 'draft', ?, ?, NULL, 1002.5, NULL)""",
        (
            REVISION_ID,
            PRACTICE_SET_ID,
            '[ {"source_id":"src_cell_biology","revision":7} ]',
            _json([question["objective_id"] for question in QUESTIONS]),
        ),
    )

    for ordinal, question in enumerate(QUESTIONS, start=1):
        # Deliberate whitespace and non-ASCII content make byte preservation
        # stronger than a semantically equivalent JSON round-trip assertion.
        contract_json = json.dumps(
            {
                "kind": "exact",
                "answer": question["answer"],
                "accepted_answers": [str(question["answer"]).upper()],
            },
            ensure_ascii=False,
            separators=(", ", ": "),
        )
        conn.execute(
            """INSERT INTO practice_questions
               (id, practice_set_revision_id, question_type, prompt,
                answer_contract_json, explanation, objective_ids_json,
                citation_json, ordinal, created_at)
               VALUES (?, ?, 'short_answer', ?, ?, ?, ?, ?, ?, ?)""",
            (
                question["id"],
                REVISION_ID,
                f"Historical exact question {ordinal}: {question['objective_id']}?",
                contract_json,
                f"Retained explanation {ordinal} — source-grounded.",
                _json([question["objective_id"]]),
                f'[ {{"source_id":"src_cell_biology","page":{ordinal}}} ]',
                ordinal,
                1003.0 + ordinal / 10,
            ),
        )

    conn.execute(
        """UPDATE practice_set_revisions
           SET state = 'ready', ready_at = 1004.75 WHERE id = ?""",
        (REVISION_ID,),
    )
    conn.execute(
        """UPDATE practice_sets
           SET current_revision_id = ?, updated_at = 1004.75 WHERE id = ?""",
        (REVISION_ID, PRACTICE_SET_ID),
    )
    conn.execute(
        """INSERT INTO quiz_attempts
           (id, owner_user_id, course_id, practice_set_id,
            practice_set_revision_id, state, score_json, revision,
            course_write_epoch, practice_set_write_epoch, started_at,
            submitted_at, graded_at, archived_at, updated_at, timing_mode)
           VALUES (?, ?, ?, ?, ?, 'in_progress', NULL, 1, 1, 1,
                   1010.125, NULL, NULL, NULL, 1010.125, 'untimed')""",
        (ATTEMPT_ID, OWNER, COURSE_ID, PRACTICE_SET_ID, REVISION_ID),
    )

    for ordinal, question in enumerate(QUESTIONS, start=1):
        conn.execute(
            """INSERT INTO quiz_attempt_items
               (id, attempt_id, question_id, display_ordinal,
                option_order_json, randomized_values_json, grading_json,
                error_type, graded_at)
               VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)""",
            (question["item_id"], ATTEMPT_ID, question["id"], ordinal),
        )
        conn.execute(
            """INSERT INTO quiz_attempt_answers
               (attempt_item_id, response_json, revision, answered_at)
               VALUES (?, NULL, 1, NULL)""",
            (question["item_id"],),
        )
        response_json = json.dumps(
            {"answer": question["response"]},
            ensure_ascii=False,
            separators=(", ", ": "),
        )
        conn.execute(
            """UPDATE quiz_attempt_answers
               SET response_json = ?, revision = 2, answered_at = ?
               WHERE attempt_item_id = ?""",
            (response_json, 1011.0 + ordinal / 10, question["item_id"]),
        )

    conn.execute(
        """UPDATE quiz_attempts
           SET state = 'submitted', submitted_at = 1012.5, revision = 2,
               updated_at = 1012.5 WHERE id = ?""",
        (ATTEMPT_ID,),
    )

    for ordinal, question in enumerate(QUESTIONS, start=1):
        contract = json.loads(
            conn.execute(
                "SELECT answer_contract_json FROM practice_questions WHERE id = ?",
                (question["id"],),
            ).fetchone()[0]
        )
        response = json.loads(
            conn.execute(
                """SELECT response_json FROM quiz_attempt_answers
                   WHERE attempt_item_id = ?""",
                (question["item_id"],),
            ).fetchone()[0]
        )
        payload = {
            "algorithm": "exact-v1",
            "attempt_id": ATTEMPT_ID,
            "attempt_item_id": question["item_id"],
            "question_id": question["id"],
            "objective_id": question["objective_id"],
            "module_id": question["module_id"],
            "knowledge_type": question["knowledge_type"],
            "contract_sha256": _digest(contract),
            "response_sha256": _digest(response),
            "is_correct": question["is_correct"],
            "error_type": question["error_type"],
        }
        grading_json = _json(payload)
        initial_state = "unmapped" if question["state"] == "unmapped" else "pending"
        created_at = 1013.0 + ordinal / 10
        conn.execute(
            """INSERT INTO quiz_item_grading_evidence
               (id, owner_user_id, course_id, practice_set_id, attempt_id,
                attempt_item_id, question_id, objective_id, module_id,
                knowledge_type, algorithm, payload_sha256, is_correct,
                grading_json, error_type, state, created_at, applied_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'exact-v1', ?, ?, ?, ?,
                       ?, ?, ?)""",
            (
                question["evidence_id"],
                OWNER,
                COURSE_ID,
                PRACTICE_SET_ID,
                ATTEMPT_ID,
                question["item_id"],
                question["id"],
                question["objective_id"],
                question["module_id"],
                question["knowledge_type"],
                _digest(payload),
                int(bool(question["is_correct"])),
                grading_json,
                question["error_type"],
                initial_state,
                created_at,
                created_at if initial_state == "unmapped" else None,
            ),
        )
        if question["state"] == "applied":
            conn.execute(
                """UPDATE quiz_item_grading_evidence
                   SET state = 'applied', applied_at = ? WHERE id = ?""",
                (created_at + 0.05, question["evidence_id"]),
            )
        conn.execute(
            """UPDATE quiz_attempt_items
               SET grading_json = ?, error_type = ?, graded_at = ? WHERE id = ?""",
            (
                _json(
                    {
                        "algorithm": "exact-v1",
                        "is_correct": question["is_correct"],
                        "evidence_ids": [question["evidence_id"]],
                    }
                ),
                question["error_type"],
                1014.0 + ordinal / 10,
                question["item_id"],
            ),
        )

    conn.execute(
        """UPDATE quiz_attempts
           SET state = 'graded', score_json = ?, graded_at = 1015.75,
               revision = 3, updated_at = 1015.75 WHERE id = ?""",
        (_json({"correct": 3, "total": 4, "fraction": 0.75}), ATTEMPT_ID),
    )

    invalidations = (
        (
            "cqr_global_question",
            "cqi_global_question",
            QUESTIONS[2],
            None,
            "The entire historical question is unsafe to count.",
        ),
        (
            "cqr_specific_evidence",
            "cqi_specific_evidence",
            QUESTIONS[1],
            QUESTIONS[1]["evidence_id"],
            "Only this retained grading receipt is invalidated.",
        ),
    )
    for offset, (report_id, invalidation_id, question, evidence_id, reason) in enumerate(
        invalidations, start=1
    ):
        created_at = 1020.0 + offset / 10
        conn.execute(
            """INSERT INTO practice_question_quality_reports
               (id, owner_user_id, course_id, practice_set_id,
                practice_set_revision_id, question_id, reporter_user_id,
                reason, state, reviewer_user_id, review_note, created_at,
                reviewed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reported', NULL, NULL, ?, NULL)""",
            (
                report_id,
                OWNER,
                COURSE_ID,
                PRACTICE_SET_ID,
                REVISION_ID,
                question["id"],
                OWNER,
                reason,
                created_at,
            ),
        )
        conn.execute(
            """UPDATE practice_question_quality_reports
               SET state = 'reviewed', reviewer_user_id = ?, review_note = ?,
                   reviewed_at = ? WHERE id = ?""",
            (OWNER, "Reviewed against source packet.", created_at + 0.01, report_id),
        )
        conn.execute(
            """UPDATE practice_question_quality_reports
               SET state = 'invalidated' WHERE id = ?""",
            (report_id,),
        )
        conn.execute(
            """INSERT INTO practice_question_invalidations
               (id, owner_user_id, course_id, practice_set_id,
                practice_set_revision_id, question_id, report_id, evidence_id,
                reason, invalidated_by, invalidated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                invalidation_id,
                OWNER,
                COURSE_ID,
                PRACTICE_SET_ID,
                REVISION_ID,
                question["id"],
                report_id,
                evidence_id,
                reason,
                OWNER,
                created_at + 0.02,
            ),
        )


def _domain_snapshot(conn: sqlite3.Connection) -> dict[str, tuple[tuple[object, ...], ...]]:
    """Capture every pre-existing domain value using the pre-migration columns."""

    tables = tuple(
        str(row[0])
        for row in conn.execute(
            """SELECT name FROM sqlite_master
               WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                 AND name != 'schema_migrations'
               ORDER BY name"""
        )
    )
    snapshot: dict[str, tuple[tuple[object, ...], ...]] = {}
    for table in tables:
        columns = tuple(
            str(row["name"])
            for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            if not (table == "practice_questions" and str(row["name"]) == "options_json")
        )
        projection = ", ".join(f'"{column}"' for column in columns)
        rows = conn.execute(
            f'SELECT {projection} FROM "{table}" ORDER BY rowid'
        ).fetchall()
        snapshot[table] = tuple(tuple(row) for row in rows)
    return snapshot


def _rebuilt_text_bytes(
    conn: sqlite3.Connection,
) -> dict[str, tuple[tuple[object, ...], ...]]:
    """Capture TEXT storage bytes for both tables rebuilt by 0015."""

    result: dict[str, tuple[tuple[object, ...], ...]] = {}
    for table in REBUILT_TABLES:
        text_columns = tuple(
            str(row["name"])
            for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            if str(row["type"]).upper() == "TEXT"
        )
        projection = ", ".join(
            f'typeof("{column}"), hex(CAST("{column}" AS BLOB))'
            for column in text_columns
        )
        rows = conn.execute(
            f'SELECT {projection} FROM "{table}" ORDER BY id'
        ).fetchall()
        result[table] = tuple(tuple(row) for row in rows)
    return result


def _semantics(repository: CourseRepository) -> dict[str, object]:
    attempts = CourseAssessmentService(CourseAssessmentRepository(repository))
    attempt_view = attempts.get_attempt(COURSE_ID, PRACTICE_SET_ID, ATTEMPT_ID)
    quality_repository = CourseContentQualityRepository(repository)
    return {
        "pending_retry_ids": [
            item.id
            for item in CourseGradingRepository(repository).pending(
                COURSE_ID, PRACTICE_SET_ID, ATTEMPT_ID
            )
        ],
        "effective_result": CourseContentQualityService(
            quality_repository
        ).effective_result(COURSE_ID, PRACTICE_SET_ID, attempt_view),
        "stored_score": attempt_view.attempt.score,
    }


def _create_populated_0014_database(
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifacts: tuple[MigrationArtifact, ...],
) -> CourseRepository:
    through_0014 = _migrations_through(artifacts, 14)
    monkeypatch.setattr(runner, "discover_migrations", lambda: through_0014)
    assert ensure_course_schema(path) == tuple(range(15))
    with open_course_connection(path) as conn:
        _populate_exact_history(conn)
        conn.commit()
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    return CourseRepository(path, OWNER)


def _assert_no_pre_0015_tables(conn: sqlite3.Connection) -> None:
    assert conn.execute(
        """SELECT name FROM sqlite_master
           WHERE type = 'table' AND name IN (
               'practice_question_invalidations_pre_0015',
               'quiz_item_grading_evidence_pre_0015'
           )"""
    ).fetchall() == []


def test_0015_preserves_populated_exact_history_and_effective_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = runner.discover_migrations()
    through_0015 = _migrations_through(artifacts, 15)
    assert sum(artifact.version == 15 for artifact in artifacts) == 1
    path = tmp_path / "populated-success.db"
    repository = _create_populated_0014_database(path, monkeypatch, artifacts)

    with open_course_connection(path) as conn:
        before_rows = _domain_snapshot(conn)
        before_counts = {table: len(rows) for table, rows in before_rows.items()}
        before_bytes = _rebuilt_text_bytes(conn)
    before_semantics = _semantics(repository)
    assert before_semantics == {
        "pending_retry_ids": ["grd_pending_retry"],
        "effective_result": {
            "score": {"correct": 1, "total": 2, "fraction": 0.5},
            "invalidated_question_ids": [
                "qst_applied_global_invalidation",
                "qst_pending_invalidated_evidence",
            ],
            "invalidated_evidence_ids": ["grd_pending_invalidated_evidence"],
            "evidence_status": "adjusted_for_invalidated_question",
        },
        "stored_score": {"correct": 3, "total": 4, "fraction": 0.75},
    }

    monkeypatch.setattr(runner, "discover_migrations", lambda: through_0015)
    assert ensure_course_schema(path) == (15,)
    assert ensure_course_schema(path) == ()

    required_indexes = {
        "idx_quiz_grading_evidence_attempt",
        "practice_question_invalidations_attempt_lookup",
    }
    required_triggers = {
        "practice_questions_contract_shape_insert",
        "practice_questions_contract_shape_update",
        "quiz_attempts_submit_requires_complete_answers",
        "quiz_grading_evidence_requires_submitted_attempt",
        "quiz_grading_evidence_immutable",
        "quiz_grading_evidence_state_transition",
        "quiz_grading_evidence_no_delete",
        "quiz_grading_evidence_item_results_agree",
        "quiz_attempt_items_grading_requires_evidence",
        "quiz_attempts_grading_requires_complete_evidence",
        "quiz_grading_evidence_retention_limit",
        "practice_question_invalidation_owned_insert",
        "practice_question_invalidation_no_update",
        "practice_question_invalidation_no_delete",
    }
    with open_course_connection(path) as conn:
        after_rows = _domain_snapshot(conn)
        assert {table: len(rows) for table, rows in after_rows.items()} == before_counts
        assert after_rows == before_rows
        assert _rebuilt_text_bytes(conn) == before_bytes
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        _assert_no_pre_0015_tables(conn)
        assert required_indexes <= {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        assert required_triggers <= {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            )
        }
        expected_versions = tuple(
            artifact.version for artifact in runner.discover_migrations()
        )
        assert tuple(
            int(row[0])
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ) == expected_versions
        assert conn.execute(
            "SELECT COUNT(*) FROM practice_questions WHERE options_json = '[]'"
        ).fetchone()[0] == len(QUESTIONS)

    assert _semantics(repository) == before_semantics


def test_0015_mid_rebuild_failure_rolls_back_populated_database_to_0014(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = runner.discover_migrations()
    through_0014 = _migrations_through(artifacts, 14)
    through_0015 = _migrations_through(artifacts, 15)
    target = next(artifact for artifact in artifacts if artifact.version == 15)
    path = tmp_path / "populated-rollback.db"
    repository = _create_populated_0014_database(path, monkeypatch, artifacts)

    with open_course_connection(path) as conn:
        before_signature = runner._schema_signature(conn, include_ledger=True)
        before_rows = _domain_snapshot(conn)
        before_bytes = _rebuilt_text_bytes(conn)
        before_receipts = tuple(
            tuple(row)
            for row in conn.execute(
                """SELECT version, name, checksum_sha256, applied_at_utc
                   FROM schema_migrations ORDER BY version"""
            )
        )
    before_semantics = _semantics(repository)

    marker = b"DROP TABLE practice_question_invalidations_pre_0015;"
    assert target.content.count(marker) == 1
    broken_content = target.content.replace(
        marker,
        b"SELECT teeechr_test_forced_0015_failure();\n" + marker,
        1,
    )
    broken_target = MigrationArtifact.from_resource(target.filename, broken_content)
    broken_through_0015 = tuple(
        broken_target if artifact.version == 15 else artifact
        for artifact in through_0015
    )
    monkeypatch.setattr(
        runner, "discover_migrations", lambda: broken_through_0015
    )

    with pytest.raises(
        CourseMigrationError,
        match=r"0015_bounded_assessment_runtime\.sql failed:.*forced_0015_failure",
    ):
        ensure_course_schema(path)

    monkeypatch.setattr(runner, "discover_migrations", lambda: through_0014)
    with open_course_connection(path) as conn:
        assert runner._schema_signature(conn, include_ledger=True) == before_signature
        assert _domain_snapshot(conn) == before_rows
        assert _rebuilt_text_bytes(conn) == before_bytes
        assert tuple(
            tuple(row)
            for row in conn.execute(
                """SELECT version, name, checksum_sha256, applied_at_utc
                   FROM schema_migrations ORDER BY version"""
            )
        ) == before_receipts
        assert tuple(
            int(row[0])
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ) == tuple(range(15))
        assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 14
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        _assert_no_pre_0015_tables(conn)

    assert ensure_course_schema(path) == ()
    assert _semantics(repository) == before_semantics
