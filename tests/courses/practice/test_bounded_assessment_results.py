"""Learner-safe Results projections after bounded-assessment invalidation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def bounded_results_client(tmp_path, monkeypatch) -> TestClient:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import courses as course_router
    from deeptutor.courses import service as course_service
    from deeptutor.multi_user import identity, paths
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.auth import TokenPayload

    admin_root = (tmp_path / "data").resolve()
    users_root = admin_root / "users"
    system_root = admin_root / "system"
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "USERS_ROOT", users_root)
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "missing-users.json")
    monkeypatch.setattr(identity, "LEGACY_SECRET_FILE", tmp_path / "missing-secret")

    alice = save_user("alice", "$2b$12$placeholder", role="admin")
    token = TokenPayload("alice", "admin", alice["id"])
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda supplied: token if supplied == "alice" else None,
    )
    monkeypatch.setattr(course_service, "is_pocketbase_enabled", lambda: False)
    course_service._repository_for.cache_clear()

    app = FastAPI()
    app.include_router(
        course_router.router,
        prefix="/api/v1/courses",
        dependencies=[Depends(auth_router.require_auth)],
    )
    app.state.alice_id = alice["id"]
    return TestClient(app)


@dataclass(frozen=True)
class _GradedScenario:
    client: TestClient
    repository: Any
    practice: Any
    assessments: Any
    course_id: str
    practice_set_id: str
    revision_id: str
    attempt_id: str
    results_url: str
    question_ids: tuple[str, str]
    explanations: tuple[str, str]
    citation_quotes: tuple[str, str]


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer alice"}


def _seed_graded_scenario(client: TestClient) -> _GradedScenario:
    from deeptutor.courses.attempt_repository import CourseAssessmentRepository
    from deeptutor.courses.attempt_service import CourseAssessmentService
    from deeptutor.courses.practice_repository import CoursePracticeRepository
    from deeptutor.courses.practice_service import CoursePracticeService
    from deeptutor.courses.repository import CourseRepository
    from deeptutor.multi_user.paths import get_personal_path_service

    created = client.post("/api/v1/courses", headers=_auth(), json={"title": "Bounded Results"})
    assert created.status_code == 200
    course = created.json()
    repository = CourseRepository(
        get_personal_path_service(client.app.state.alice_id).get_courses_db(),
        client.app.state.alice_id,
    )
    source = repository.create_source(
        course["id"],
        kind="notes",
        display_name="respiration-notes.txt",
        manifest=[],
        content_sha256="a" * 64,
    )
    source = repository.transition_source(
        course["id"],
        source.id,
        operation_id=source.operation_id or "",
        expected_source_revision=source.revision,
        expected_course_revision=course["revision"],
        expected_write_epoch=course["write_epoch"],
        state="ready",
    )
    practice = CoursePracticeService(CoursePracticeRepository(repository))
    practice_set = practice.create_practice_set(
        course["id"],
        title="Respiration review",
        expected_course_write_epoch=course["write_epoch"],
    )
    revision = practice.create_draft_revision(
        course["id"],
        practice_set.id,
        source_ids=(source.id,),
        expected_course_write_epoch=course["write_epoch"],
    )
    explanations = (
        "Oxygen is the final electron acceptor.",
        "Oxygen combines with electrons and protons to form water.",
    )
    citation_quotes = (
        "Oxygen accepts electrons at the end of the chain.",
        "The products include water after oxygen accepts electrons and protons.",
    )
    specifications = (
        ("What is the final electron acceptor?", "oxygen", explanations[0], citation_quotes[0]),
        ("What product forms from reduced oxygen?", "water", explanations[1], citation_quotes[1]),
    )
    questions = []
    for index, (prompt, answer, explanation, quote) in enumerate(specifications, start=1):
        questions.append(
            practice.add_question(
                course["id"],
                practice_set.id,
                revision.id,
                question_type="short_answer",
                prompt=prompt,
                answer_contract={
                    "kind": "bounded_short_answer_v1",
                    "canonical_answer": answer,
                    "accepted_normalized_answers": [answer],
                    "normalization_version": "bounded-text-normalization-v1",
                },
                explanation=explanation,
                objective_ids=(f"OBJ-RESP-0{index}",),
                citations=(
                    {
                        "source_id": source.id,
                        "source_revision": source.revision,
                        "content_sha256": source.content_sha256,
                        "locator": {"page": index, "quote": quote},
                    },
                ),
                expected_course_write_epoch=course["write_epoch"],
            )
        )
    practice.ready_revision(
        course["id"],
        practice_set.id,
        revision.id,
        expected_course_write_epoch=course["write_epoch"],
    )
    practice_set = practice.get_practice_set(course["id"], practice_set.id)
    course_write_epoch = repository.get_course(course["id"]).write_epoch
    attempts_url = f"/api/v1/courses/{course['id']}/practice/{practice_set.id}/attempts"
    started = client.post(
        attempts_url,
        headers=_auth(),
        json={
            "practice_set_revision_id": revision.id,
            "expected_course_write_epoch": course_write_epoch,
            "expected_practice_set_write_epoch": practice_set.write_epoch,
        },
    )
    assert started.status_code == 200, started.text
    view = started.json()
    attempt_url = f"{attempts_url}/{view['attempt']['id']}"
    item_by_question = {item["question_id"]: item for item in view["items"]}
    submitted_answers = ("oxygen", "incorrect")
    for index, (question, answer) in enumerate(
        zip(questions, submitted_answers, strict=True), start=1
    ):
        saved = client.patch(
            attempt_url,
            headers={**_auth(), "Idempotency-Key": f"bounded-answer-{index}"},
            json={
                "attempt_item_id": item_by_question[question.id]["id"],
                "response": {"answer": answer},
                "expected_answer_revision": 1,
                "expected_course_write_epoch": view["attempt"]["course_write_epoch"],
                "expected_practice_set_write_epoch": view["attempt"]["practice_set_write_epoch"],
            },
        )
        assert saved.status_code == 200, saved.text
    mutation = {
        "expected_course_write_epoch": view["attempt"]["course_write_epoch"],
        "expected_practice_set_write_epoch": view["attempt"]["practice_set_write_epoch"],
    }
    assert client.post(f"{attempt_url}/submit", headers=_auth(), json=mutation).status_code == 200
    graded = client.post(f"{attempt_url}/grade", headers=_auth(), json=mutation)
    assert graded.status_code == 200, graded.text
    assert graded.json()["score"] == {"correct": 1, "total": 2, "fraction": 0.5}
    return _GradedScenario(
        client=client,
        repository=repository,
        practice=practice,
        assessments=CourseAssessmentService(CourseAssessmentRepository(repository)),
        course_id=course["id"],
        practice_set_id=practice_set.id,
        revision_id=revision.id,
        attempt_id=view["attempt"]["id"],
        results_url=f"{attempt_url}/results",
        question_ids=(questions[0].id, questions[1].id),
        explanations=explanations,
        citation_quotes=citation_quotes,
    )


def _invalidate(scenario: _GradedScenario, question_id: str) -> None:
    report = scenario.client.post(
        f"/api/v1/courses/{scenario.course_id}/practice/{scenario.practice_set_id}/"
        f"revisions/{scenario.revision_id}/questions/{question_id}/quality-report",
        headers=_auth(),
        json={"reason": "The answer authority failed reviewer verification."},
    )
    assert report.status_code == 201, report.text
    resolved = scenario.client.post(
        f"/api/v1/courses/{scenario.course_id}/content-quality/reports/"
        f"{report.json()['id']}/resolve",
        headers=_auth(),
        json={
            "decision": "invalidate",
            "note": "Withdraw this question from learner scoring and review.",
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["report"]["state"] == "invalidated"


def _start_current_revision(scenario: _GradedScenario):
    course = scenario.repository.get_course(scenario.course_id)
    practice_set = scenario.practice.get_practice_set(
        scenario.course_id, scenario.practice_set_id
    )
    return scenario.client.post(
        f"/api/v1/courses/{scenario.course_id}/practice/"
        f"{scenario.practice_set_id}/attempts",
        headers=_auth(),
        json={
            "practice_set_revision_id": scenario.revision_id,
            "expected_course_write_epoch": course.write_epoch,
            "expected_practice_set_write_epoch": practice_set.write_epoch,
        },
    )


def _questions_url(scenario: _GradedScenario) -> str:
    return (
        f"/api/v1/courses/{scenario.course_id}/practice/{scenario.practice_set_id}/"
        f"revisions/{scenario.revision_id}/questions"
    )


def _by_question(payload: dict[str, Any], collection: str) -> dict[str, dict[str, Any]]:
    return {
        item["question_id" if collection == "items" else "id"]: item for item in payload[collection]
    }


def test_partial_invalidation_withdraws_only_the_invalid_result_authority(
    bounded_results_client: TestClient,
) -> None:
    scenario = _seed_graded_scenario(bounded_results_client)
    invalidated_id, valid_id = scenario.question_ids
    _invalidate(scenario, invalidated_id)

    response = scenario.client.get(scenario.results_url, headers=_auth())
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["effective_score"] == {"correct": 0, "total": 1, "fraction": 0.0}
    assert result["attempt"]["score"] is None
    assert result["content_quality"]["invalidated_question_ids"] == [invalidated_id]
    questions = _by_question(result, "questions")
    items = _by_question(result, "items")

    withdrawn = questions[invalidated_id]
    assert withdrawn["content_quality"] == "invalidated"
    assert not {"answer_contract", "explanation", "citations"} & withdrawn.keys()
    assert items[invalidated_id]["content_quality"] == "invalidated"
    assert items[invalidated_id]["grading"] is None
    assert items[invalidated_id]["error_type"] is None

    ordinary = questions[valid_id]
    assert ordinary["content_quality"] == "valid"
    assert ordinary["answer_contract"]["canonical_answer"] == "water"
    assert ordinary["explanation"] == scenario.explanations[1]
    assert ordinary["citations"][0]["locator"]["quote"] == scenario.citation_quotes[1]
    assert items[valid_id]["content_quality"] == "valid"
    assert items[valid_id]["grading"]["is_correct"] is False

    attempt_url = scenario.results_url.removesuffix("/results")
    detail = scenario.client.get(attempt_url, headers=_auth())
    assert detail.status_code == 200, detail.text
    detail_payload = detail.json()
    assert detail_payload["attempt"]["score"] is None
    assert detail_payload["content_quality"]["invalidated_question_ids"] == [
        invalidated_id
    ]
    detail_items = _by_question(detail_payload, "items")
    assert detail_items[invalidated_id]["grading"] is None
    assert detail_items[invalidated_id]["content_quality"] == "invalidated"
    assert detail_items[valid_id]["grading"]["is_correct"] is False

    grade_replay = scenario.client.post(
        f"{attempt_url}/grade",
        headers=_auth(),
        json={
            "expected_course_write_epoch": detail_payload["attempt"][
                "course_write_epoch"
            ],
            "expected_practice_set_write_epoch": detail_payload["attempt"][
                "practice_set_write_epoch"
            ],
        },
    )
    assert grade_replay.status_code == 200, grade_replay.text
    assert grade_replay.json()["score"] is None
    assert (
        grade_replay.json()["content_quality"]
        == "adjusted_for_invalidated_question"
    )

    history = scenario.client.get(
        f"/api/v1/courses/{scenario.course_id}/practice/"
        f"{scenario.practice_set_id}/attempts",
        headers=_auth(),
    )
    assert history.status_code == 200, history.text
    listed_attempt = next(
        item for item in history.json()["attempts"] if item["id"] == scenario.attempt_id
    )
    assert listed_attempt["score"] is None
    assert listed_attempt["content_quality"] == "adjusted_for_invalidated_question"

    # Invalidation changes only the projection: immutable authoring and grading
    # history remain available to trusted internal services.
    stored_questions = {
        question.id: question
        for question in scenario.practice.list_questions(
            scenario.course_id, scenario.practice_set_id, scenario.revision_id
        )
    }
    assert stored_questions[invalidated_id].answer_contract.canonical_answer == "oxygen"
    assert stored_questions[invalidated_id].explanation == scenario.explanations[0]
    stored_view = scenario.assessments.get_attempt(
        scenario.course_id, scenario.practice_set_id, scenario.attempt_id
    )
    stored_item = next(item for item in stored_view.items if item.question_id == invalidated_id)
    assert stored_item.grading is not None
    assert stored_item.grading["is_correct"] is True


def test_full_invalidation_returns_zero_effective_total_and_no_remediation_scope(
    bounded_results_client: TestClient,
) -> None:
    scenario = _seed_graded_scenario(bounded_results_client)
    for question_id in scenario.question_ids:
        _invalidate(scenario, question_id)

    response = scenario.client.get(scenario.results_url, headers=_auth())
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["effective_score"] == {"correct": 0, "total": 0, "fraction": 0.0}
    assert result["attempt"]["score"] is None
    assert result["content_quality"]["invalidated_question_ids"] == sorted(scenario.question_ids)
    assert all(
        question["content_quality"] == "invalidated"
        and not {"answer_contract", "explanation", "citations"} & question.keys()
        for question in result["questions"]
    )
    assert all(
        item["content_quality"] == "invalidated"
        and item["grading"] is None
        and item["error_type"] is None
        for item in result["items"]
    )

    remediation = scenario.client.post(
        scenario.results_url.removesuffix("/results") + "/flashcard-brief",
        headers=_auth(),
        json={},
    )
    assert remediation.status_code == 409
    assert "no missed answers" in remediation.json()["detail"]


def test_partial_invalidation_admits_only_valid_questions_to_a_new_attempt(
    bounded_results_client: TestClient,
) -> None:
    scenario = _seed_graded_scenario(bounded_results_client)
    invalidated_id, valid_id = scenario.question_ids
    _invalidate(scenario, invalidated_id)

    listed = scenario.client.get(_questions_url(scenario), headers=_auth())
    assert listed.status_code == 200, listed.text
    quality_by_id = {
        question["id"]: question["content_quality"]
        for question in listed.json()["questions"]
    }
    assert quality_by_id == {invalidated_id: "invalidated", valid_id: "valid"}

    started = _start_current_revision(scenario)
    assert started.status_code == 200, started.text
    view = started.json()
    assert [item["question_id"] for item in view["items"]] == [valid_id]
    assert len(view["answers"]) == 1

    attempt_url = (
        f"/api/v1/courses/{scenario.course_id}/practice/{scenario.practice_set_id}/"
        f"attempts/{view['attempt']['id']}"
    )
    mutation = {
        "expected_course_write_epoch": view["attempt"]["course_write_epoch"],
        "expected_practice_set_write_epoch": view["attempt"][
            "practice_set_write_epoch"
        ],
    }
    saved = scenario.client.patch(
        attempt_url,
        headers={**_auth(), "Idempotency-Key": "valid-question-after-invalidation"},
        json={
            "attempt_item_id": view["items"][0]["id"],
            "response": {"answer": "water"},
            "expected_answer_revision": 1,
            **mutation,
        },
    )
    assert saved.status_code == 200, saved.text
    assert (
        scenario.client.post(
            f"{attempt_url}/submit", headers=_auth(), json=mutation
        ).status_code
        == 200
    )
    graded = scenario.client.post(
        f"{attempt_url}/grade", headers=_auth(), json=mutation
    )
    assert graded.status_code == 200, graded.text
    assert graded.json()["score"] == {"correct": 1, "total": 1, "fraction": 1.0}

    with scenario.repository._connect() as conn:
        evidence_question_ids = {
            str(row["question_id"])
            for row in conn.execute(
                """SELECT question_id FROM quiz_item_grading_evidence
                   WHERE attempt_id = ?""",
                (view["attempt"]["id"],),
            ).fetchall()
        }
    assert evidence_question_ids == {valid_id}
    assert invalidated_id not in evidence_question_ids


def test_full_invalidation_blocks_new_attempt_and_counts_distinct_questions(
    bounded_results_client: TestClient,
) -> None:
    scenario = _seed_graded_scenario(bounded_results_client)
    for question_id in scenario.question_ids:
        _invalidate(scenario, question_id)

    listed = scenario.client.get(_questions_url(scenario), headers=_auth())
    assert listed.status_code == 200, listed.text
    assert {
        question["id"]: question["content_quality"]
        for question in listed.json()["questions"]
    } == {question_id: "invalidated" for question_id in scenario.question_ids}

    started = _start_current_revision(scenario)
    assert started.status_code == 409, started.text
    assert started.json()["detail"] == "no_valid_questions"

    with scenario.repository._connect() as conn:
        ledger = conn.execute(
            """SELECT COUNT(*) AS row_count,
                      COUNT(DISTINCT question_id) AS question_count
               FROM practice_question_invalidations
               WHERE course_id = ? AND practice_set_revision_id = ?""",
            (scenario.course_id, scenario.revision_id),
        ).fetchone()
        attempt_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM quiz_attempts WHERE practice_set_revision_id = ?",
                (scenario.revision_id,),
            ).fetchone()[0]
        )
    assert ledger is not None
    assert int(ledger["row_count"]) == 4
    assert int(ledger["question_count"]) == 2
    assert attempt_count == 1


def test_withdrawn_in_progress_attempt_is_read_only_until_abandoned(
    bounded_results_client: TestClient,
) -> None:
    scenario = _seed_graded_scenario(bounded_results_client)
    invalidated_id, valid_id = scenario.question_ids
    fresh = _start_current_revision(scenario)
    assert fresh.status_code == 200, fresh.text
    view = fresh.json()
    item_by_question = {
        item["question_id"]: item for item in view["items"]
    }
    _invalidate(scenario, invalidated_id)

    attempt_url = (
        f"/api/v1/courses/{scenario.course_id}/practice/{scenario.practice_set_id}/"
        f"attempts/{view['attempt']['id']}"
    )
    detail = scenario.client.get(attempt_url, headers=_auth())
    assert detail.status_code == 200, detail.text
    assert detail.json()["content_quality"]["invalidated_question_ids"] == [
        invalidated_id
    ]
    assert {
        item["question_id"]: item["content_quality"]
        for item in detail.json()["items"]
    } == {invalidated_id: "invalidated", valid_id: "valid"}

    mutation = {
        "expected_course_write_epoch": view["attempt"]["course_write_epoch"],
        "expected_practice_set_write_epoch": view["attempt"][
            "practice_set_write_epoch"
        ],
    }
    saved = scenario.client.patch(
        attempt_url,
        headers={**_auth(), "Idempotency-Key": "withdrawn-attempt-write"},
        json={
            "attempt_item_id": item_by_question[valid_id]["id"],
            "response": {"answer": "water"},
            "expected_answer_revision": 1,
            **mutation,
        },
    )
    assert saved.status_code == 409, saved.text
    assert saved.json()["detail"] == "Attempt contains withdrawn questions"

    submitted = scenario.client.post(
        f"{attempt_url}/submit", headers=_auth(), json=mutation
    )
    assert submitted.status_code == 409, submitted.text
    assert submitted.json()["detail"] == "Attempt contains withdrawn questions"

    abandoned = scenario.client.post(
        f"{attempt_url}/abandon", headers=_auth(), json=mutation
    )
    assert abandoned.status_code == 200, abandoned.text
    assert abandoned.json()["state"] == "abandoned"

    replacement = _start_current_revision(scenario)
    assert replacement.status_code == 200, replacement.text
    assert [
        item["question_id"] for item in replacement.json()["items"]
    ] == [valid_id]


def test_submitted_attempt_cannot_be_graded_after_question_withdrawal(
    bounded_results_client: TestClient,
) -> None:
    scenario = _seed_graded_scenario(bounded_results_client)
    invalidated_id, _valid_id = scenario.question_ids
    fresh = _start_current_revision(scenario)
    assert fresh.status_code == 200, fresh.text
    view = fresh.json()
    item_by_question = {
        item["question_id"]: item for item in view["items"]
    }
    mutation = {
        "expected_course_write_epoch": view["attempt"]["course_write_epoch"],
        "expected_practice_set_write_epoch": view["attempt"][
            "practice_set_write_epoch"
        ],
    }
    attempt_url = (
        f"/api/v1/courses/{scenario.course_id}/practice/{scenario.practice_set_id}/"
        f"attempts/{view['attempt']['id']}"
    )
    for index, (question_id, answer) in enumerate(
        zip(scenario.question_ids, ("oxygen", "water"), strict=True), start=1
    ):
        saved = scenario.client.patch(
            attempt_url,
            headers={**_auth(), "Idempotency-Key": f"pre-withdrawal-answer-{index}"},
            json={
                "attempt_item_id": item_by_question[question_id]["id"],
                "response": {"answer": answer},
                "expected_answer_revision": 1,
                **mutation,
            },
        )
        assert saved.status_code == 200, saved.text
    submitted = scenario.client.post(
        f"{attempt_url}/submit", headers=_auth(), json=mutation
    )
    assert submitted.status_code == 200, submitted.text

    _invalidate(scenario, invalidated_id)

    graded = scenario.client.post(
        f"{attempt_url}/grade", headers=_auth(), json=mutation
    )
    assert graded.status_code == 409, graded.text
    assert graded.json()["detail"] == "Attempt contains withdrawn questions"
