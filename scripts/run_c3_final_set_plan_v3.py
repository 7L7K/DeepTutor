#!/usr/bin/env python3
"""Run the frozen three-item C3 final set-plan-v3 campaign.

This successor keeps the v2 harness and individual publication rules but uses a
smaller source-supported composition: one complete question per objective.
"""

from scripts import run_c3_final_set_plan_v2 as base


FINAL_SET_PLAN_ID = "c3-final-set-plan-v3"
FINAL_SET_PLAN_FILENAME = "final_set_plan_v3.json"
FINAL_CAMPAIGN_ID = "2026-08-10-teeechr-c3-final-learning-loop-v3"
FINAL_GENERATION_PROMPT_ID = "c3-final-set-generation-prompt-v3"
FINAL_CAMPAIGN_SCHEMA_VERSION = "c3-final-quality-campaign-v3"
FINAL_GENERATION_RECEIPT_SCHEMA_VERSION = "c3-final-generation-receipt-v3"
FINAL_NORMALIZED_SCHEMA_VERSION = "c3-final-normalized-questions-v3"
ITEM_LIMIT = 3
ALLOCATION = {"OBJ-RESP-01": 1, "OBJ-RESP-02": 1, "OBJ-RESP-03": 1}


def configure() -> None:
    """Apply the v3 constants to the shared harness immediately before running."""
    base.FINAL_SET_PLAN_ID = FINAL_SET_PLAN_ID
    base.FINAL_SET_PLAN_FILENAME = FINAL_SET_PLAN_FILENAME
    base.FINAL_CAMPAIGN_ID = FINAL_CAMPAIGN_ID
    base.FINAL_GENERATION_PROMPT_ID = FINAL_GENERATION_PROMPT_ID
    base.FINAL_CAMPAIGN_SCHEMA_VERSION = FINAL_CAMPAIGN_SCHEMA_VERSION
    base.FINAL_GENERATION_RECEIPT_SCHEMA_VERSION = FINAL_GENERATION_RECEIPT_SCHEMA_VERSION
    base.FINAL_NORMALIZED_SCHEMA_VERSION = FINAL_NORMALIZED_SCHEMA_VERSION
    base.ITEM_LIMIT = ITEM_LIMIT
    base.ALLOCATION = ALLOCATION


if __name__ == "__main__":
    configure()
    raise SystemExit(base.main())
