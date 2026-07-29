"""P4-03 adversarial contracts for deterministic, replay-safe Course grading."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

from pydantic import ValidationError
import pytest

from deeptutor.courses.attempt_repository import CourseAssessmentRepository
from deeptutor.courses.attempt_service import CourseAssessmentService
from deeptutor.courses.grading_repository import CourseGradingRepository
from deeptutor.courses.grading_service import CourseGradingService
from deeptutor.courses.mastery_adapter import CourseMasteryAdapter
from deeptutor.courses.migrations import runner
from deeptutor.courses.migrations.runner import CourseMigrationError, ensure_course_schema
from deeptutor.courses.practice_repository import CoursePracticeRepository
from deeptutor.courses.practice_service import CoursePracticeService
from deeptutor.courses.repository import CourseConflictError, CourseNotFoundError, CourseRepository
from deeptutor.learning.models import KnowledgePoint, KnowledgeType, LearningModule
from deeptutor.learning.storage import LearningConflictError, LearningStore


def _services(tmp_path: Path, owner: str = "u_alice"):
    courses = CourseRepository(tmp_path / "courses.db", owner)
    practice = CoursePracticeService(CoursePracticeRepository(courses))
    attempts = CourseAssessmentService(CourseAssessmentRepository(courses))
    adapter = CourseMasteryAdapter(LearningStore(root=tmp_path / "learning"))
    grading = CourseGradingService(CourseGradingRepository(courses), adapter)
    return courses, practice, attempts, adapter, grading


def _epoch(courses: CourseRepository, course_id: str) -> int:
    return courses.get_course(course_id).write_epoch


def _practice(courses, practice, course_id: str, *, objectives=("kp_one",), answer="yes", raw_contract: str | None = None):
    epoch = _epoch(courses, course_id)
    practice_set = practice.create_practice_set(course_id, title="Quiz", expected_course_write_epoch=epoch)
    revision = practice.create_draft_revision(course_id, practice_set.id, expected_course_write_epoch=epoch)
    question = practice.add_question(
        course_id, practice_set.id, revision.id,
        question_type="short_answer", prompt="Answer?",
        answer_contract={"kind": "exact", "answer": answer}, objective_ids=objectives,
        expected_course_write_epoch=epoch,
    )
    if raw_contract is not None:
        with courses._connect() as conn:
            conn.execute(
                "UPDATE practice_questions SET answer_contract_json = ? WHERE id = ?",
                (raw_contract, question.id),
            )
    practice.ready_revision(course_id, practice_set.id, revision.id, expected_course_write_epoch=epoch)
    return practice_set, revision, question


def _init_objectives(adapter: CourseMasteryAdapter, course_id: str, *objective_ids: str) -> None:
    progress = adapter.service.get_or_create(f"lp_{course_id}")
    adapter.service.init_modules(
        progress,
        [LearningModule(
            id="mod_one", name="Module", order=1,
            knowledge_points=[
                KnowledgePoint(id=item, name=item, type=KnowledgeType.MEMORY, module_id="mod_one")
                for item in objective_ids
            ],
        )],
    )
    adapter.service.save(progress)


def _submitted(courses, attempts, course_id: str, practice_set, revision, response):
    view = attempts.start_or_resume_attempt(
        course_id, practice_set.id, revision.id,
        expected_course_write_epoch=_epoch(courses, course_id), expected_practice_set_write_epoch=2,
    )
    item = view.items[0]
    attempts.autosave_answer(
        course_id, practice_set.id, view.attempt.id, item.id,
        response=response, expected_answer_revision=1, idempotency_token="answer-token",
        expected_course_write_epoch=_epoch(courses, course_id), expected_practice_set_write_epoch=2,
    )
    attempts.submit_attempt(
        course_id, practice_set.id, view.attempt.id,
        expected_course_write_epoch=_epoch(courses, course_id), expected_practice_set_write_epoch=2,
    )
    return view.attempt.id, item.id


def _grade(grading, courses, course_id: str, practice_set_id: str, attempt_id: str):
    return grading.grade_attempt(
        course_id, practice_set_id, attempt_id,
        expected_course_write_epoch=_epoch(courses, course_id), expected_practice_set_write_epoch=2,
    )


@pytest.mark.parametrize("response, correct", [({"answer": "YES"}, True), ({"answer": "no"}, False), ({"answer": ""}, False)])
def test_exact_grading_is_server_contract_driven_for_correct_wrong_and_blank(tmp_path: Path, response, correct: bool) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Biology")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, response)

    result = _grade(grading, courses, course.id, practice_set.id, attempt_id)
    assert result.state == "graded"
    assert result.score == {"correct": int(correct), "total": 1, "fraction": float(correct)}
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    assert len(progress.quiz_attempts) == 1
    assert progress.quiz_attempts[0].is_correct is correct
    if correct:
        assert progress.mastery_levels["kp_one"] > 0
        assert progress.error_records == []
    else:
        assert progress.error_records[0].knowledge_point_id == "kp_one"
        assert progress.review_queue[0].knowledge_point_id == "kp_one"


def test_unsupported_contract_fails_closed_before_any_evidence(tmp_path: Path) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Chemistry")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(
        courses, practice, course.id, raw_contract='{"kind":"unsupported"}'
    )
    with pytest.raises(ValidationError):
        attempts.start_or_resume_attempt(
            course.id, practice_set.id, revision.id,
            expected_course_write_epoch=_epoch(courses, course.id), expected_practice_set_write_epoch=2,
        )
    with courses._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM quiz_item_grading_evidence").fetchone()[0] == 0


def test_response_must_be_the_exact_answer_object_before_any_grading_receipt(tmp_path: Path) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Linguistics")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, "yes")
    with pytest.raises(ValueError, match="response"):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    with courses._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM quiz_item_grading_evidence WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()[0] == 0


def test_grading_is_submitted_owned_and_foreign_or_missing_ids_are_uniform(tmp_path: Path) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    first = courses.create_course("Physics")
    second = courses.create_course("Physics")
    _init_objectives(adapter, first.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, first.id)
    view = attempts.start_or_resume_attempt(first.id, practice_set.id, revision.id, expected_course_write_epoch=_epoch(courses, first.id), expected_practice_set_write_epoch=2)
    for call in (
        lambda: _grade(grading, courses, first.id, practice_set.id, view.attempt.id),
        lambda: _grade(grading, courses, second.id, practice_set.id, view.attempt.id),
        lambda: _grade(grading, courses, first.id, practice_set.id, "att_missing"),
    ):
        with pytest.raises((CourseConflictError, CourseNotFoundError)) as raised:
            call()
        if isinstance(raised.value, CourseNotFoundError):
            assert str(raised.value) == "Assessment resource not found"


def test_multiple_objectives_are_server_resolved_once_each_and_double_grade_is_idempotent(tmp_path: Path) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Math")
    _init_objectives(adapter, course.id, "kp_one", "kp_two")
    practice_set, revision, _ = _practice(courses, practice, course.id, objectives=("kp_one", "kp_two"))
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})
    first = _grade(grading, courses, course.id, practice_set.id, attempt_id)
    second = _grade(grading, courses, course.id, practice_set.id, attempt_id)
    assert first.id == second.id and second.state == "graded"
    with courses._connect() as conn:
        rows = conn.execute("SELECT objective_id, state FROM quiz_item_grading_evidence WHERE attempt_id = ? ORDER BY objective_id", (attempt_id,)).fetchall()
    assert [(row["objective_id"], row["state"]) for row in rows] == [("kp_one", "applied"), ("kp_two", "applied")]
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    assert len(progress.quiz_attempts) == 2
    assert set(progress.mastery_levels) >= {"kp_one", "kp_two"}


def test_unresolved_objective_is_immutable_unmapped_evidence_with_no_learning_effect(tmp_path: Path) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Law")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id, objectives=("kp_one", "kp_missing"))
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})
    assert _grade(grading, courses, course.id, practice_set.id, attempt_id).state == "graded"
    with courses._connect() as conn:
        rows = conn.execute(
            "SELECT objective_id, state FROM quiz_item_grading_evidence WHERE attempt_id = ? ORDER BY objective_id",
            (attempt_id,),
        ).fetchall()
    assert [(row["objective_id"], row["state"]) for row in rows] == [
        ("kp_missing", "unmapped"), ("kp_one", "applied")
    ]
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    assert [item.knowledge_point_id for item in progress.quiz_attempts] == ["kp_one"]


def test_crash_after_learning_save_before_sql_ack_recovers_without_double_effect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("History")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})

    def crash(*_args, **_kwargs):
        raise RuntimeError("after learning save")

    monkeypatch.setattr(grading, "_mark_effect_applied", crash)
    with pytest.raises(RuntimeError, match="after learning save"):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    assert len(progress.quiz_attempts) == 1
    monkeypatch.undo()
    result = _grade(grading, courses, course.id, practice_set.id, attempt_id)
    assert result.state == "graded"
    assert len(adapter.service.get_or_create(f"lp_{course.id}").quiz_attempts) == 1


@pytest.mark.parametrize("seam", ["_apply_effect_to_learning", "_finalize_attempt"])
def test_crash_before_learning_effect_or_before_finalization_recovers_from_pending_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seam: str
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Sociology")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})

    def crash(*_args, **_kwargs):
        raise RuntimeError(seam)

    monkeypatch.setattr(grading, seam, crash)
    with pytest.raises(RuntimeError, match=seam):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    monkeypatch.undo()
    assert _grade(grading, courses, course.id, practice_set.id, attempt_id).state == "graded"
    assert len(adapter.service.get_or_create(f"lp_{course.id}").quiz_attempts) == 1


def test_direct_sql_evidence_is_immutable_and_attempt_cannot_grade_without_all_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Ecology")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, item_id = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})
    def crash(_evidence):
        raise RuntimeError("after sqlite grade")

    monkeypatch.setattr(grading, "_apply_effect_to_learning", crash)
    with pytest.raises(RuntimeError, match="after sqlite grade"):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    with courses._connect() as conn:
        evidence_id = conn.execute("SELECT id FROM quiz_item_grading_evidence WHERE attempt_id = ?", (attempt_id,)).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE quiz_item_grading_evidence SET is_correct = 0 WHERE id = ?", (evidence_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM quiz_item_grading_evidence WHERE id = ?", (evidence_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE quiz_attempts SET state = 'graded', score_json = '{}', graded_at = 1 WHERE id = ?", (attempt_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE quiz_attempt_items SET grading_json = '{}', graded_at = 1 WHERE id = ?", (item_id,))


def test_crash_before_sqlite_commit_rolls_back_evidence_and_leaves_attempt_submitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Geography")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})

    def crash(*_args, **_kwargs):
        raise RuntimeError("before sqlite commit")

    monkeypatch.setattr(grading.repository, "_records", crash)
    with pytest.raises(RuntimeError, match="before sqlite commit"):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    assert attempts.get_attempt(course.id, practice_set.id, attempt_id).attempt.state == "submitted"
    with courses._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM quiz_item_grading_evidence WHERE attempt_id = ?", (attempt_id,)).fetchone()[0] == 0


def test_sqlite_grade_commits_before_json_projection_and_delivery_order_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Economics")
    _init_objectives(adapter, course.id, "kp_one", "kp_two")
    practice_set, revision, _ = _practice(courses, practice, course.id, objectives=("kp_two", "kp_one"))
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})

    monkeypatch.setattr(grading, "_apply_effect_to_learning", lambda _evidence: (_ for _ in ()).throw(RuntimeError("after sqlite commit")))
    with pytest.raises(RuntimeError, match="after sqlite commit"):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    assert attempts.get_attempt(course.id, practice_set.id, attempt_id).attempt.state == "graded"
    pending = grading.repository.pending(course.id, practice_set.id, attempt_id)
    assert [(item.objective_id, item.state) for item in pending] == [("kp_one", "pending"), ("kp_two", "pending")]

    monkeypatch.undo()
    assert _grade(grading, courses, course.id, practice_set.id, attempt_id).state == "graded"
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    assert [item.knowledge_point_id for item in progress.quiz_attempts] == ["kp_one", "kp_two"]


def test_blank_answer_is_mapped_to_metacognitive_error_and_zero_objectives_still_grade_item(
    tmp_path: Path,
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Psychology")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id, objectives=())
    attempt_id, item_id = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": ""})
    assert _grade(grading, courses, course.id, practice_set.id, attempt_id).state == "graded"
    with courses._connect() as conn:
        row = conn.execute(
            "SELECT objective_id, state, error_type FROM quiz_item_grading_evidence WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        item = conn.execute("SELECT grading_json, error_type, graded_at FROM quiz_attempt_items WHERE id = ?", (item_id,)).fetchone()
    assert tuple(row) == ("", "unmapped", "metacognitive")
    assert item["grading_json"] is not None and item["error_type"] == "metacognitive" and item["graded_at"] is not None
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    assert progress.quiz_attempts == [] and progress.error_records == [] and progress.review_queue == []


def test_evidence_payload_digest_conflict_is_rejected_by_learning_projection(tmp_path: Path) -> None:
    _courses, _practice_service, _attempts, adapter, _grading = _services(tmp_path)
    progress = adapter.service.get_or_create("lp_crs_digest")
    adapter.service.init_modules(
        progress,
        [LearningModule(id="mod", name="Module", order=1, knowledge_points=[
            KnowledgePoint(id="kp", name="KP", type=KnowledgeType.MEMORY, module_id="mod")
        ])],
    )
    adapter.service.save(progress)
    adapter.service.record_course_grading_evidence(
        progress, evidence_id="grd_same", payload_sha256="a" * 64, question_id="qst", knowledge_point_id="kp",
        module_id="mod", is_correct=True, user_answer="yes", knowledge_type=KnowledgeType.MEMORY,
    )
    with pytest.raises(LearningConflictError, match="payload conflicts"):
        adapter.service.record_course_grading_evidence(
            progress, evidence_id="grd_same", payload_sha256="b" * 64, question_id="qst", knowledge_point_id="kp",
            module_id="mod", is_correct=True, user_answer="yes", knowledge_type=KnowledgeType.MEMORY,
        )


def test_captured_mapping_survives_later_plan_replacement_and_unmapped_never_revives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Art")
    _init_objectives(adapter, course.id, "kp_old")
    practice_set, revision, _ = _practice(courses, practice, course.id, objectives=("kp_old", "kp_never"))
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})
    monkeypatch.setattr(grading, "_apply_effect_to_learning", lambda _evidence: (_ for _ in ()).throw(RuntimeError("after sqlite")))
    with pytest.raises(RuntimeError, match="after sqlite"):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    progress = adapter.service.get_or_create(f"lp_{course.id}")
    adapter.service.replace_modules(
        progress,
        [LearningModule(id="mod_new", name="New", order=1, knowledge_points=[
            KnowledgePoint(id="kp_never", name="Later", type=KnowledgeType.PROCEDURE, module_id="mod_new")
        ])],
    )
    adapter.service.save(progress)
    monkeypatch.undo()
    assert _grade(grading, courses, course.id, practice_set.id, attempt_id).state == "graded"
    replayed = adapter.service.get_or_create(f"lp_{course.id}")
    assert [(item.knowledge_point_id, item.module_id) for item in replayed.quiz_attempts] == [("kp_old", "mod_one")]
    with courses._connect() as conn:
        rows = conn.execute(
            "SELECT objective_id, module_id, knowledge_type, state FROM quiz_item_grading_evidence WHERE attempt_id = ? ORDER BY objective_id",
            (attempt_id,),
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("kp_never", None, None, "unmapped"), ("kp_old", "mod_one", "memory", "applied")
    ]


def test_archive_after_sqlite_grade_preserves_pending_ack_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Music")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(courses, attempts, course.id, practice_set, revision, {"answer": "yes"})
    monkeypatch.setattr(grading, "_apply_effect_to_learning", lambda _evidence: (_ for _ in ()).throw(RuntimeError("after sqlite")))
    with pytest.raises(RuntimeError):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)
    courses.archive_course(course.id, expected_revision=courses.get_course(course.id).revision)
    monkeypatch.undo()
    assert _grade(grading, courses, course.id, practice_set.id, attempt_id).state == "graded"
    assert len(adapter.service.get_or_create(f"lp_{course.id}").quiz_attempts) == 1


def test_sqlite_evidence_blocks_reset_even_before_learning_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses, practice, attempts, adapter, grading = _services(tmp_path)
    course = courses.create_course("Ethics")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(
        courses, attempts, course.id, practice_set, revision, {"answer": "yes"}
    )
    monkeypatch.setattr(
        grading,
        "_apply_effect_to_learning",
        lambda _evidence: (_ for _ in ()).throw(RuntimeError("after sqlite")),
    )
    with pytest.raises(RuntimeError, match="after sqlite"):
        _grade(grading, courses, course.id, practice_set.id, attempt_id)

    assert grading.repository.has_course_evidence(course.id) is True
    assert (
        adapter.service.get_or_create(f"lp_{course.id}").grading_evidence_receipts
        == {}
    )


def test_0002_upgrade_applies_grading_and_generation_migrations_preserves_rows_and_tamper_or_rollback_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "p4_03"
    path = root / "courses.db"
    artifacts = runner.discover_migrations()
    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts[:3])
    assert ensure_course_schema(path) == (0, 1, 2)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO courses (id, owner_user_id, title, state, revision, write_epoch, managed_kb_ref, created_at, updated_at, archived_at) VALUES ('crs_keep', 'u_alice', 'Keep', 'active', 1, 1, NULL, 1, 1, NULL)")
    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts)
    assert ensure_course_schema(path) == (3, 4, 5)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT title FROM courses WHERE id = 'crs_keep'").fetchone()[0] == "Keep"

    tampered = runner.MigrationArtifact.from_resource(
        artifacts[3].filename, artifacts[3].content + b"\n-- changed bytes\n"
    )
    monkeypatch.setattr(runner, "discover_migrations", lambda: (*artifacts[:3], tampered, *artifacts[4:]))
    with pytest.raises(CourseMigrationError, match="receipt mismatch"):
        ensure_course_schema(path)

    broken = runner.MigrationArtifact.from_resource(
        "0003_grading_evidence.sql", b"CREATE TABLE should_rollback (id INTEGER);\nNOT VALID SQL;"
    )
    monkeypatch.setattr(runner, "discover_migrations", lambda: (*artifacts[:3], broken))
    fresh = tmp_path / "broken.db"
    with pytest.raises(CourseMigrationError, match="0003_grading_evidence.sql failed"):
        ensure_course_schema(fresh)
    with sqlite3.connect(fresh) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'should_rollback'").fetchone()[0] == 0


def test_exact_p4_03_upgrade_applies_generation_and_flashcard_migrations_and_preserves_learning_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P4-05/06 must be no-rewrite upgrades from the accepted P4-03 ledger."""
    root = tmp_path / "p4_03_upgrade"
    path = root / "courses.db"
    artifacts = runner.discover_migrations()
    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts[:4])
    courses, practice, attempts, adapter, grading = _services(root, "u_alice")
    course = courses.create_course("Biology")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _questions = _practice(courses, practice, course.id)
    attempt_id, _item_id = _submitted(
        courses, attempts, course.id, practice_set, revision, {"answer": "yes"}
    )
    _grade(grading, courses, course.id, practice_set.id, attempt_id)
    with courses._connect() as conn:
        before = {
            table: conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            for table in (
                "courses",
                "practice_sets",
                "practice_set_revisions",
                "practice_questions",
                "quiz_attempts",
                "quiz_attempt_items",
                "quiz_attempt_answers",
                "quiz_item_grading_evidence",
            )
        }

    monkeypatch.setattr(runner, "discover_migrations", lambda: artifacts)
    assert ensure_course_schema(path) == (4, 5)
    assert ensure_course_schema(path) == ()
    with courses._connect() as conn:
        after = {
            table: conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            for table in before
        }
        assert conn.execute("SELECT COUNT(*) FROM practice_generation_operations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM flashcard_reviews").fetchone()[0] == 0
        effective_triggers = {
            str(row[0])
            for row in conn.execute(
                """SELECT name FROM sqlite_master
                   WHERE type = 'trigger' AND name LIKE 'practice_generation_%'"""
            )
        }
        assert {
            "practice_generation_operations_terminal_immutable",
            "practice_generation_generated_revision_question_fence",
            "practice_generation_generated_revision_ready_fence",
            "practice_generation_practice_set_mode_immutable",
        } <= effective_triggers
        assert tuple(
            row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        ) == (0, 1, 2, 3, 4, 5)
    assert after == before


def test_raw_sql_cannot_forge_a_self_consistent_wrong_exact_grade(tmp_path: Path) -> None:
    courses, practice, attempts, adapter, _grading = _services(tmp_path)
    course = courses.create_course("Forensics")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, item_id = _submitted(
        courses, attempts, course.id, practice_set, revision, {"answer": "no"}
    )
    with courses._connect() as conn:
        row = conn.execute(
            """SELECT attempts.*, items.question_id, answers.response_json,
                      questions.answer_contract_json FROM quiz_attempts AS attempts
               JOIN quiz_attempt_items AS items ON items.attempt_id = attempts.id
               JOIN quiz_attempt_answers AS answers ON answers.attempt_item_id = items.id
               JOIN practice_questions AS questions ON questions.id = items.question_id
               WHERE attempts.id = ?""",
            (attempt_id,),
        ).fetchone()
        contract_sha = hashlib.sha256(
            json.dumps(json.loads(row["answer_contract_json"]), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        forged = {
            "algorithm": "exact-v1", "attempt_id": attempt_id,
            "attempt_item_id": item_id, "question_id": row["question_id"],
            "objective_id": "kp_one", "module_id": "mod_one", "knowledge_type": "memory",
            "contract_sha256": contract_sha,
            "response_sha256": hashlib.sha256(
                json.dumps(
                    {"answer": "no"},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            "is_correct": True, "error_type": None,
        }
        forged_json = json.dumps(forged, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO quiz_item_grading_evidence
                   (id, owner_user_id, course_id, practice_set_id, attempt_id,
                    attempt_item_id, question_id, objective_id, module_id, knowledge_type,
                    algorithm, payload_sha256, is_correct, grading_json, error_type,
                    state, created_at, applied_at)
                   VALUES ('grd_forged', ?, ?, ?, ?, ?, ?, 'kp_one', 'mod_one', 'memory',
                           'exact-v1', ?, 1, ?, NULL, 'pending', 1, NULL)""",
                (
                    row["owner_user_id"], course.id, practice_set.id, attempt_id, item_id,
                    row["question_id"], hashlib.sha256(forged_json.encode()).hexdigest(), forged_json,
                ),
            )
        unrelated = {
            **forged,
            "objective_id": "kp_forged",
            "module_id": None,
            "knowledge_type": None,
            "is_correct": False,
            "error_type": "application",
        }
        unrelated_json = json.dumps(unrelated, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO quiz_item_grading_evidence
                   (id, owner_user_id, course_id, practice_set_id, attempt_id,
                    attempt_item_id, question_id, objective_id, module_id, knowledge_type,
                    algorithm, payload_sha256, is_correct, grading_json, error_type,
                    state, created_at, applied_at)
                   VALUES ('grd_unrelated', ?, ?, ?, ?, ?, ?, 'kp_forged', NULL, NULL,
                           'exact-v1', ?, 0, ?, 'application', 'unmapped', 1, 1)""",
                (
                    row["owner_user_id"], course.id, practice_set.id, attempt_id, item_id,
                    row["question_id"], hashlib.sha256(unrelated_json.encode()).hexdigest(), unrelated_json,
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE quiz_attempt_items SET grading_json = ?, error_type = NULL, graded_at = 1 WHERE id = ?",
                (json.dumps({"algorithm": "exact-v1", "is_correct": True, "evidence_ids": ["grd_forged"]}), item_id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE quiz_attempts SET state = 'graded', score_json = ?, graded_at = 1, revision = revision + 1, updated_at = 1 WHERE id = ?",
                (json.dumps({"correct": 1, "total": 1, "fraction": 1.0}), attempt_id),
            )


@pytest.mark.parametrize("terminalize", ["course", "practice", "successor"])
def test_archive_and_successor_terminalize_submitted_ungraded_attempts(
    tmp_path: Path, terminalize: str
) -> None:
    courses, practice, attempts, adapter, _grading = _services(tmp_path)
    course = courses.create_course("Terminal")
    _init_objectives(adapter, course.id, "kp_one")
    practice_set, revision, _ = _practice(courses, practice, course.id)
    attempt_id, _ = _submitted(
        courses, attempts, course.id, practice_set, revision, {"answer": "yes"}
    )
    if terminalize == "course":
        archived = courses.archive_course(course.id, expected_revision=courses.get_course(course.id).revision)
        courses.restore_course(course.id, expected_revision=archived.revision)
    elif terminalize == "practice":
        current = practice.get_practice_set(course.id, practice_set.id)
        practice.archive_practice_set(
            course.id, practice_set.id, expected_revision=current.revision,
            expected_course_write_epoch=_epoch(courses, course.id),
        )
    else:
        epoch = _epoch(courses, course.id)
        successor = practice.create_successor_revision(
            course.id, practice_set.id, expected_course_write_epoch=epoch
        )
        practice.add_question(
            course.id, practice_set.id, successor.id, question_type="short_answer",
            prompt="Again?", answer_contract={"kind": "exact", "answer": "yes"},
            objective_ids=("kp_one",), expected_course_write_epoch=epoch,
        )
        practice.ready_revision(
            course.id, practice_set.id, successor.id, expected_course_write_epoch=epoch
        )
    assert attempts.get_attempt(course.id, practice_set.id, attempt_id).attempt.state == "archived"
    with pytest.raises(CourseConflictError):
        _grade(_grading, courses, course.id, practice_set.id, attempt_id)
