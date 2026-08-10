from pathlib import Path

from scripts import run_c3_final_set_plan_v3 as campaign
from scripts.run_c3_final_set_plan_v2 import _instructions, _request, _set_failure_v2, _slot_contracts
from scripts.run_c3_final_quality_campaign import _material, _objective_evidence


REFERENCE_ROOT = Path(__file__).resolve().parents[3] / "evals/reference_course"


def _configure(monkeypatch) -> None:
    for name in (
        "FINAL_SET_PLAN_ID",
        "FINAL_SET_PLAN_FILENAME",
        "FINAL_CAMPAIGN_ID",
        "FINAL_GENERATION_PROMPT_ID",
        "FINAL_CAMPAIGN_SCHEMA_VERSION",
        "FINAL_GENERATION_RECEIPT_SCHEMA_VERSION",
        "FINAL_NORMALIZED_SCHEMA_VERSION",
        "ITEM_LIMIT",
        "ALLOCATION",
    ):
        monkeypatch.setattr(campaign.base, name, getattr(campaign, name))


def test_v3_is_a_frozen_three_objective_successor_plan(monkeypatch) -> None:
    _configure(monkeypatch)
    slots = _slot_contracts(REFERENCE_ROOT)
    assert campaign.FINAL_SET_PLAN_ID == "c3-final-set-plan-v3"
    assert campaign.ITEM_LIMIT == 3
    assert campaign.ALLOCATION == {"OBJ-RESP-01": 1, "OBJ-RESP-02": 1, "OBJ-RESP-03": 1}
    assert len(slots) == 3
    assert {slot.objective_id for slot in slots.values()} == set(campaign.ALLOCATION)


def test_v3_prompt_does_not_require_four_choice_positions_for_two_choice_slots(monkeypatch) -> None:
    _configure(monkeypatch)
    slots = _slot_contracts(REFERENCE_ROOT)
    instructions = _instructions(slots)
    assert "Use distinct correct_option_key values across the single-choice slots." in instructions
    assert "slot_resp02_terminal_mechanism must assess" not in instructions


def test_v3_request_uses_three_items(monkeypatch) -> None:
    _configure(monkeypatch)
    slots = _slot_contracts(REFERENCE_ROOT)
    request = _request(
        campaign_id="test-c3-final-set-plan-v3",
        phase="primary",
        candidate_number=1,
        material=_material(REFERENCE_ROOT),
        evidence=_objective_evidence(REFERENCE_ROOT),
        purpose="practice",
        item_limit=campaign.ITEM_LIMIT,
        focus="test",
        slots=slots,
    )
    assert request.item_limit == 3


def test_v3_rejects_the_old_five_item_shape(monkeypatch) -> None:
    _configure(monkeypatch)
    slots = _slot_contracts(REFERENCE_ROOT)
    request = _request(
        campaign_id="test-c3-final-set-plan-v3-shape",
        phase="primary",
        candidate_number=1,
        material=_material(REFERENCE_ROOT),
        evidence=_objective_evidence(REFERENCE_ROOT),
        purpose="practice",
        item_limit=campaign.ITEM_LIMIT,
        focus="test",
        slots=slots,
    )
    failure, detail, _ = _set_failure_v2([{}] * 5, slots=slots, request=request)
    assert failure == "MODEL_FORMAT_FAILURE"
    assert "exactly 3" in detail
