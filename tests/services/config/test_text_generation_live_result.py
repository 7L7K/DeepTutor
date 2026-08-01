from __future__ import annotations

import json
from pathlib import Path

from deeptutor.services.config.text_generation_qualification import FrozenQualificationPack

_RUN_DIR = Path("qualification/runs/qrun_20260801_core_01")
_PACK_PATH = Path("qualification/text_generation_core_v1.json")


def _load(name: str) -> dict:
    return json.loads((_RUN_DIR / name).read_text(encoding="utf-8"))


def test_live_result_accounts_for_every_authorized_pair_and_matches_policy() -> None:
    pack = FrozenQualificationPack.load(_PACK_PATH)
    state = _load("run_state.json")
    review = _load("human_review.json")
    result = _load("qualification_result.json")

    expected_pairs = {
        (case.case_id, model) for case in pack.cases for model in pack.models
    }
    calls = {(row["case_id"], row["requested_model"]): row for row in state["calls"]}
    reviews = {
        (row["case_id"], row["requested_model"]): row
        for row in review["observations"]
    }
    assert set(calls) == expected_pairs
    assert set(reviews) == expected_pairs
    assert result["calls_authorized"] == result["calls_attempted"] == len(expected_pairs)
    assert result["retries"] == state["max_retries"] == 0
    assert result["completed_calls"] == state["completed_calls"] == 15
    assert result["failed_calls"] == state["failed_calls"] == 1
    assert result["uncertain_calls"] == state["uncertain_calls"] == 0
    assert result["settled_cost_microusd"] == state["settled_cost_microusd"]
    assert result["settled_cost_microusd"] <= result["approved_spend_cap_microusd"]
    assert result["additional_paid_calls_authorized"] is False

    for case in pack.cases:
        for model in pack.models:
            pair = (case.case_id, model)
            call = calls[pair]
            observation = reviews[pair]
            assert observation["state"] == call["state"]
            assert set(observation["grader_results"]) == set(case.required_graders)
            assert observation["security_result"] in {"pass", "fail"}
            assert observation["validation_result"] in {"pass", "fail"}
            if observation["state"] == "completed":
                assert "artifact_sha256" in call
                assert all(
                    grade in {"pass", "fail"}
                    for grade in observation["grader_results"].values()
                )
            else:
                assert observation["validation_result"] == "fail"
                assert all(
                    grade == "not_applicable"
                    for grade in observation["grader_results"].values()
                )

    decisions = result["feature_decisions"]
    for feature, decision in decisions.items():
        feature_reviews = [
            reviews[(case.case_id, model)]
            for case in pack.cases
            if case.feature == feature
            for model in pack.models
        ]
        all_pass = all(
            row["state"] == "completed"
            and row["security_result"] == "pass"
            and row["validation_result"] == "pass"
            and all(grade == "pass" for grade in row["grader_results"].values())
            for row in feature_reviews
        )
        assert (decision["result"] == "pass") is all_pass


def test_luna_medium_generation_result_is_complete_and_matches_active_policy() -> None:
    run_dir = Path("qualification/runs/qrun_20260801_luna_generation_medium_01")
    pack = FrozenQualificationPack.load(_PACK_PATH)
    state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
    review = json.loads((run_dir / "human_review.json").read_text(encoding="utf-8"))
    result = json.loads(
        (run_dir / "qualification_result.json").read_text(encoding="utf-8")
    )
    selected_cases = {
        case.case_id: case
        for case in pack.cases
        if case.feature in {"flashcard_generation", "practice_generation"}
    }
    expected_pairs = {(case_id, "gpt-5.6-luna") for case_id in selected_cases}
    calls = {(row["case_id"], row["requested_model"]): row for row in state["calls"]}
    reviews = {
        (row["case_id"], row["requested_model"]): row
        for row in review["observations"]
    }

    assert set(calls) == set(reviews) == expected_pairs
    assert result["calls_authorized"] == result["calls_attempted"] == 4
    assert result["mini_calls"] == result["retries"] == 0
    assert state["reasoning_effort"] == result["reasoning_effort"] == "medium"
    assert state["completed_calls"] == result["completed_calls"] == 4
    assert state["failed_calls"] == result["failed_calls"] == 0
    assert state["uncertain_calls"] == result["uncertain_calls"] == 0
    assert state["settled_cost_microusd"] == result["settled_cost_microusd"]
    assert result["settled_cost_microusd"] <= result["approved_spend_cap_microusd"]
    assert result["additional_paid_calls_authorized"] is False
    assert all(row["requested_model"] == "gpt-5.6-luna" for row in state["calls"])

    for pair, observation in reviews.items():
        case = selected_cases[pair[0]]
        assert observation["state"] == calls[pair]["state"] == "completed"
        assert set(observation["grader_results"]) == set(case.required_graders)
        assert set(observation["grader_results"].values()) == {"pass"}
        assert observation["security_result"] == "pass"
        assert observation["validation_result"] == "pass"

    from deeptutor.services.config.text_generation_registry import (
        TextGenerationRegistry,
        default_text_generation_catalog,
    )

    registry = TextGenerationRegistry.from_catalog(
        {"text_generation": default_text_generation_catalog()}
    )
    for feature, decision in result["feature_decisions"].items():
        resolved = registry.resolve(feature)
        assert resolved.model.model_id == decision["model"] == "gpt-5.6-luna"
        assert resolved.mode == decision["mode"] == "qualified"
        assert resolved.reasoning_effort == decision["reasoning_effort"] == "medium"
