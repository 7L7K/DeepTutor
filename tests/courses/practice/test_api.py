"""Authenticated API contracts for manual Course Practice workflows."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def practice_client(tmp_path, monkeypatch) -> TestClient:
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
    bob = save_user("bob", "$2b$12$placeholder", role="user")
    tokens = {
        "alice": TokenPayload("alice", "admin", alice["id"]),
        "bob": TokenPayload("bob", "user", bob["id"]),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    monkeypatch.setattr(course_service, "is_pocketbase_enabled", lambda: False)
    course_service._repository_for.cache_clear()

    app = FastAPI()
    app.include_router(
        course_router.router,
        prefix="/api/v1/courses",
        dependencies=[Depends(auth_router.require_auth)],
    )
    return TestClient(app)


def _auth(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {name}"}


def _create_course(client: TestClient, owner: str = "alice") -> dict:
    response = client.post(
        "/api/v1/courses", headers=_auth(owner), json={"title": "Biology"}
    )
    assert response.status_code == 200
    return response.json()


def _create_ready_practice(
    client: TestClient, course: dict, owner: str = "alice"
) -> tuple[dict, dict]:
    course_id = course["id"]
    practice = client.post(
        f"/api/v1/courses/{course_id}/practice",
        headers=_auth(owner),
        json={"title": "Cell quiz", "expected_course_write_epoch": course["write_epoch"]},
    )
    assert practice.status_code == 200
    practice_set = practice.json()
    revision = client.post(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/revisions",
        headers=_auth(owner),
        json={"expected_course_write_epoch": course["write_epoch"]},
    )
    assert revision.status_code == 200
    revision_payload = revision.json()
    question = client.post(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/revisions/{revision_payload['id']}/questions",
        headers=_auth(owner),
        json={
            "question_type": "short_answer",
            "prompt": "Type yes",
            "answer_contract": {"kind": "exact", "answer": "yes"},
            "objective_ids": ["kp_cell"],
            "expected_course_write_epoch": course["write_epoch"],
        },
    )
    assert question.status_code == 200
    ready = client.post(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/revisions/{revision_payload['id']}/ready",
        headers=_auth(owner),
        json={"expected_course_write_epoch": course["write_epoch"]},
    )
    assert ready.status_code == 200
    updated_set = client.get(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}",
        headers=_auth(owner),
    )
    assert updated_set.status_code == 200
    return updated_set.json(), revision_payload


def test_manual_practice_api_lifecycle_autosave_idempotency_and_results(
    practice_client: TestClient,
) -> None:
    course = _create_course(practice_client)
    practice_set, revision = _create_ready_practice(practice_client, course)
    course_id = course["id"]
    start_body = {
        "practice_set_revision_id": revision["id"],
        "expected_course_write_epoch": course["write_epoch"],
        "expected_practice_set_write_epoch": practice_set["write_epoch"],
    }
    started = practice_client.post(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/attempts",
        headers=_auth("alice"),
        json=start_body,
    )
    assert started.status_code == 200
    view = started.json()
    resumed = practice_client.post(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/attempts",
        headers=_auth("alice"),
        json=start_body,
    )
    assert resumed.status_code == 200
    assert resumed.json()["attempt"]["id"] == view["attempt"]["id"]

    endpoint = (
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/attempts/"
        f"{view['attempt']['id']}"
    )
    assert practice_client.get(f"{endpoint}/results", headers=_auth("alice")).status_code == 409

    autosave_body = {
        "attempt_item_id": view["items"][0]["id"],
        "response": {"answer": "wrong"},
        "expected_answer_revision": 1,
        "expected_course_write_epoch": course["write_epoch"],
        "expected_practice_set_write_epoch": practice_set["write_epoch"],
    }
    headers = {**_auth("alice"), "Idempotency-Key": "answer-once"}
    saved = practice_client.patch(endpoint, headers=headers, json=autosave_body)
    assert saved.status_code == 200
    assert saved.json()["revision"] == 2
    assert practice_client.patch(endpoint, headers=headers, json=autosave_body).json() == saved.json()
    conflicting = practice_client.patch(
        endpoint,
        headers=headers,
        json={**autosave_body, "response": {"answer": "different"}},
    )
    assert conflicting.status_code == 409

    mutation = {
        "expected_course_write_epoch": course["write_epoch"],
        "expected_practice_set_write_epoch": practice_set["write_epoch"],
    }
    assert practice_client.post(
        f"{endpoint}/submit",
        headers=_auth("alice"),
        json={**mutation, "score": {"correct": 999}},
    ).status_code == 422
    submitted = practice_client.post(f"{endpoint}/submit", headers=_auth("alice"), json=mutation)
    assert submitted.status_code == 200
    graded = practice_client.post(f"{endpoint}/grade", headers=_auth("alice"), json=mutation)
    assert graded.status_code == 200
    assert graded.json()["state"] == "graded"
    assert graded.json()["score"] == {"correct": 0, "total": 1, "fraction": 0.0}
    assert practice_client.post(
        f"{endpoint}/grade", headers=_auth("alice"), json=mutation
    ).json() == graded.json()
    learner_attempt = practice_client.get(endpoint, headers=_auth("alice"))
    assert learner_attempt.status_code == 200
    assert "answer_contract" not in learner_attempt.text
    assert "yes" not in learner_attempt.text

    successor = practice_client.post(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/revisions/successor",
        headers=_auth("alice"),
        json={"expected_course_write_epoch": course["write_epoch"]},
    )
    assert successor.status_code == 200
    successor_id = successor.json()["id"]
    assert practice_client.post(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/revisions/{successor_id}/questions",
        headers=_auth("alice"),
        json={
            "question_type": "short_answer",
            "prompt": "Type no",
            "answer_contract": {"kind": "exact", "answer": "no"},
            "expected_course_write_epoch": course["write_epoch"],
        },
    ).status_code == 200
    assert practice_client.post(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/revisions/{successor_id}/ready",
        headers=_auth("alice"),
        json={"expected_course_write_epoch": course["write_epoch"]},
    ).status_code == 200
    results = practice_client.get(f"{endpoint}/results", headers=_auth("alice"))
    assert results.status_code == 200
    assert results.json()["attempt"]["score"] == graded.json()["score"]
    assert results.json()["attempt"]["practice_set_revision_id"] == revision["id"]
    assert [item["id"] for item in results.json()["questions"]] == [
        view["items"][0]["question_id"]
    ]
    assert results.json()["questions"][0]["answer_contract"] == {
        "kind": "exact",
        "answer": "yes",
    }


def test_draft_questions_show_author_contract_but_ready_questions_are_learner_safe(
    practice_client: TestClient,
) -> None:
    course = _create_course(practice_client)
    course_id = course["id"]
    practice_set = practice_client.post(
        f"/api/v1/courses/{course_id}/practice",
        headers=_auth("alice"),
        json={"title": "Draft quiz", "expected_course_write_epoch": course["write_epoch"]},
    ).json()
    revision = practice_client.post(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/revisions",
        headers=_auth("alice"),
        json={"expected_course_write_epoch": course["write_epoch"]},
    ).json()
    questions_endpoint = (
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/revisions/"
        f"{revision['id']}/questions"
    )
    added = practice_client.post(
        questions_endpoint,
        headers=_auth("alice"),
        json={
            "question_type": "short_answer",
            "prompt": "Secret answer",
            "answer_contract": {"kind": "exact", "answer": "reveal-me"},
            "expected_course_write_epoch": course["write_epoch"],
        },
    )
    assert added.status_code == 200
    assert added.json()["answer_contract"]["answer"] == "reveal-me"
    draft_questions = practice_client.get(questions_endpoint, headers=_auth("alice"))
    assert draft_questions.status_code == 200
    assert draft_questions.json()["questions"][0]["answer_contract"]["answer"] == "reveal-me"
    assert practice_client.post(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/revisions/{revision['id']}/ready",
        headers=_auth("alice"),
        json={"expected_course_write_epoch": course["write_epoch"]},
    ).status_code == 200
    ready_questions = practice_client.get(questions_endpoint, headers=_auth("alice"))
    assert ready_questions.status_code == 200
    assert "answer_contract" not in ready_questions.text
    assert "explanation" not in ready_questions.text
    assert "reveal-me" not in ready_questions.text


def test_manual_practice_api_is_private_strict_and_archive_terminalizes_attempt(
    practice_client: TestClient,
) -> None:
    course = _create_course(practice_client)
    rejected = practice_client.post(
        f"/api/v1/courses/{course['id']}/practice",
        headers=_auth("alice"),
        json={
            "title": "No forged owner",
            "owner_user_id": "bob",
            "expected_course_write_epoch": course["write_epoch"],
        },
    )
    assert rejected.status_code == 422
    practice_set, revision = _create_ready_practice(practice_client, course)
    course_id = course["id"]
    assert practice_client.get(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}",
        headers=_auth("bob"),
    ).status_code == 404
    rejected_order = practice_client.post(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/revisions/{revision['id']}/questions",
        headers=_auth("alice"),
        json={
            "question_type": "short_answer",
            "prompt": "cannot mutate ready",
            "answer_contract": {"kind": "exact", "answer": "yes"},
            "ordinal": 99,
            "expected_course_write_epoch": course["write_epoch"],
        },
    )
    assert rejected_order.status_code == 422

    started = practice_client.post(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/attempts",
        headers=_auth("alice"),
        json={
            "practice_set_revision_id": revision["id"],
            "expected_course_write_epoch": course["write_epoch"],
            "expected_practice_set_write_epoch": practice_set["write_epoch"],
        },
    )
    assert started.status_code == 200
    attempt_page = practice_client.get(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/attempts?limit=1&offset=0",
        headers=_auth("alice"),
    )
    assert attempt_page.status_code == 200
    assert [item["id"] for item in attempt_page.json()["attempts"]] == [
        started.json()["attempt"]["id"]
    ]
    assert attempt_page.json()["next_offset"] == 1
    assert practice_client.get(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/attempts?limit=101",
        headers=_auth("alice"),
    ).status_code == 422
    archived = practice_client.post(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/archive",
        headers=_auth("alice"),
        json={
            "expected_revision": practice_set["revision"],
            "expected_course_write_epoch": course["write_epoch"],
        },
    )
    assert archived.status_code == 200
    attempt_id = started.json()["attempt"]["id"]
    history = practice_client.get(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/attempts/{attempt_id}",
        headers=_auth("alice"),
    )
    assert history.status_code == 200
    assert history.json()["attempt"]["state"] == "archived"
    stale_submit = practice_client.post(
        f"/api/v1/courses/{course_id}/practice/{practice_set['id']}/attempts/{attempt_id}/submit",
        headers=_auth("alice"),
        json={
            "expected_course_write_epoch": course["write_epoch"],
            "expected_practice_set_write_epoch": practice_set["write_epoch"],
        },
    )
    assert stale_submit.status_code == 409


def test_manual_practice_api_keeps_same_title_users_and_all_foreign_ids_private(
    practice_client: TestClient,
) -> None:
    alice_course = _create_course(practice_client, "alice")
    bob_course = _create_course(practice_client, "bob")
    assert alice_course["title"] == bob_course["title"] == "Biology"
    assert alice_course["id"] != bob_course["id"]
    alice_set, alice_revision = _create_ready_practice(practice_client, alice_course)
    bob_set, _bob_revision = _create_ready_practice(practice_client, bob_course, "bob")
    assert alice_set["title"] == bob_set["title"] == "Cell quiz"
    assert alice_set["id"] != bob_set["id"]

    alice_attempt = practice_client.post(
        f"/api/v1/courses/{alice_course['id']}/practice/{alice_set['id']}/attempts",
        headers=_auth("alice"),
        json={
            "practice_set_revision_id": alice_revision["id"],
            "expected_course_write_epoch": alice_course["write_epoch"],
            "expected_practice_set_write_epoch": alice_set["write_epoch"],
        },
    ).json()
    attempt_id = alice_attempt["attempt"]["id"]
    item_id = alice_attempt["items"][0]["id"]
    prefix = f"/api/v1/courses/{alice_course['id']}/practice/{alice_set['id']}"
    foreign_responses = [
        practice_client.get(f"{prefix}", headers=_auth("bob")),
        practice_client.get(
            f"{prefix}/revisions/{alice_revision['id']}", headers=_auth("bob")
        ),
        practice_client.get(f"{prefix}/attempts/{attempt_id}", headers=_auth("bob")),
        practice_client.patch(
            f"{prefix}/attempts/{attempt_id}",
            headers={**_auth("bob"), "Idempotency-Key": "foreign-item"},
            json={
                "attempt_item_id": item_id,
                "response": {"answer": "yes"},
                "expected_answer_revision": 1,
                "expected_course_write_epoch": alice_course["write_epoch"],
                "expected_practice_set_write_epoch": alice_set["write_epoch"],
            },
        ),
    ]
    assert [response.status_code for response in foreign_responses] == [404, 404, 404, 404]
    assert {response.json()["detail"] for response in foreign_responses} == {
        "Practice resource not found"
    }
    alice_list = practice_client.get(
        f"/api/v1/courses/{alice_course['id']}/practice", headers=_auth("alice")
    )
    bob_list = practice_client.get(
        f"/api/v1/courses/{bob_course['id']}/practice", headers=_auth("bob")
    )
    assert [item["id"] for item in alice_list.json()["practice_sets"]] == [alice_set["id"]]
    assert [item["id"] for item in bob_list.json()["practice_sets"]] == [bob_set["id"]]


def test_manual_flashcard_api_lifecycle_due_queue_idempotency_and_archive(
    practice_client: TestClient,
) -> None:
    course = _create_course(practice_client)
    course_id = course["id"]
    root = f"/api/v1/courses/{course_id}/flashcards"
    deck = practice_client.post(
        root,
        headers=_auth("alice"),
        json={"title": "Biology terms", "expected_course_write_epoch": course["write_epoch"]},
    )
    assert deck.status_code == 200
    deck = deck.json()
    deck_page = practice_client.get(
        f"{root}?include_archived=true&limit=1&offset=0",
        headers=_auth("alice"),
    )
    assert deck_page.status_code == 200
    assert [item["id"] for item in deck_page.json()["flashcard_decks"]] == [
        deck["id"]
    ]
    assert deck_page.json()["next_offset"] == 1
    assert practice_client.get(
        f"{root}?limit=101", headers=_auth("alice")
    ).status_code == 422
    card = practice_client.post(
        f"{root}/{deck['id']}/cards",
        headers=_auth("alice"),
        json={
            "prompt": "ATP?",
            "answer": "Energy currency",
            "objective_ids": ["cell_energy"],
            "expected_deck_revision": deck["revision"],
            "expected_course_write_epoch": course["write_epoch"],
        },
    )
    assert card.status_code == 200
    card = card.json()
    deck = practice_client.get(f"{root}/{deck['id']}", headers=_auth("alice")).json()["deck"]
    ready = practice_client.post(
        f"{root}/{deck['id']}/ready",
        headers=_auth("alice"),
        json={"expected_revision": deck["revision"], "expected_course_write_epoch": course["write_epoch"]},
    )
    assert ready.status_code == 200
    deck = ready.json()
    review_body = {
        "card_id": card["id"],
        "rating": "again",
        "idempotency_key": "review-once",
        "expected_deck_revision": deck["revision"],
        "expected_card_revision": card["revision"],
        "expected_course_write_epoch": course["write_epoch"],
    }
    first = practice_client.post(f"{root}/{deck['id']}/reviews", headers=_auth("alice"), json=review_body)
    assert first.status_code == 200
    assert practice_client.post(
        f"{root}/{deck['id']}/reviews", headers=_auth("alice"), json=review_body
    ).json()["review"] == first.json()["review"]
    due = practice_client.get(f"{root}/{deck['id']}/reviews", headers=_auth("alice"))
    assert due.status_code == 200
    assert due.json()["review_summary"]["review_count"] == 1
    archived = practice_client.post(
        f"{root}/{deck['id']}/archive",
        headers=_auth("alice"),
        json={"expected_revision": deck["revision"], "expected_course_write_epoch": course["write_epoch"]},
    )
    assert archived.status_code == 200
    assert practice_client.post(
        f"{root}/{deck['id']}/reviews",
        headers=_auth("alice"),
        json={**review_body, "idempotency_key": "after-archive", "expected_deck_revision": archived.json()["revision"]},
    ).status_code == 409
    assert practice_client.get(f"{root}/{deck['id']}", headers=_auth("alice")).json()["review_summary"]["review_count"] == 1


def test_manual_flashcard_api_hides_foreign_deck_card_and_review_ids(
    practice_client: TestClient,
) -> None:
    alice_course = _create_course(practice_client, "alice")
    bob_course = _create_course(practice_client, "bob")
    root = f"/api/v1/courses/{alice_course['id']}/flashcards"
    deck = practice_client.post(
        root,
        headers=_auth("alice"),
        json={"title": "Same title", "expected_course_write_epoch": alice_course["write_epoch"]},
    ).json()
    card = practice_client.post(
        f"{root}/{deck['id']}/cards",
        headers=_auth("alice"),
        json={
            "prompt": "one", "answer": "two", "expected_deck_revision": deck["revision"],
            "expected_course_write_epoch": alice_course["write_epoch"],
        },
    ).json()
    bob_root = f"/api/v1/courses/{bob_course['id']}/flashcards/{deck['id']}"
    responses = [
        practice_client.get(f"{root}/{deck['id']}", headers=_auth("bob")),
        practice_client.get(bob_root, headers=_auth("bob")),
        practice_client.post(
            f"{bob_root}/reviews",
            headers=_auth("bob"),
            json={
                "card_id": card["id"], "rating": "good", "idempotency_key": "foreign-review",
                "expected_deck_revision": deck["revision"], "expected_card_revision": card["revision"],
                "expected_course_write_epoch": bob_course["write_epoch"],
            },
        ),
    ]
    assert [response.status_code for response in responses] == [404, 404, 404]
    assert {response.json()["detail"] for response in responses} == {"Practice resource not found"}
