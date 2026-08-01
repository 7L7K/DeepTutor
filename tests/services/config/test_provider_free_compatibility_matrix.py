from __future__ import annotations

import json
from pathlib import Path
import re

_MATRIX_PATH = Path("qualification/provider_free_compatibility_v1.json")
_REQUIRED_CASES = {
    "streaming",
    "structured_outputs",
    "function_calling",
    "reasoning_usage",
    "cached_usage",
    "zero_output",
    "refusal",
    "incomplete_status",
    "http_400",
    "http_401",
    "rate_limit",
    "timeout",
    "malformed_json",
    "duplicate_cards",
    "duplicate_questions",
    "unexpected_actual_model",
    "budget_reservation",
    "budget_settlement",
    "failure_release",
    "idempotent_replay",
    "owner_revocation",
    "course_archive_during_work",
    "source_revision_change",
    "restart_recovery",
}


def test_provider_free_matrix_is_complete_and_has_resolvable_test_proof() -> None:
    payload = json.loads(_MATRIX_PATH.read_text(encoding="utf-8"))

    assert set(payload) == {
        "version",
        "matrix_id",
        "provider_calls_allowed",
        "requirements",
    }
    assert payload["version"] == 1
    assert payload["provider_calls_allowed"] is False
    rows = payload["requirements"]
    assert isinstance(rows, list)
    assert {row["id"] for row in rows} == _REQUIRED_CASES
    assert len(rows) == len(_REQUIRED_CASES)

    for row in rows:
        assert set(row) == {"id", "status", "evidence"}
        assert row["status"] == "covered_provider_free"
        assert isinstance(row["evidence"], list) and row["evidence"]
        for reference in row["evidence"]:
            path_text, separator, test_name = reference.partition("::")
            assert separator == "::"
            assert path_text.startswith("tests/")
            assert test_name.startswith("test_")
            source = Path(path_text).read_text(encoding="utf-8")
            assert re.search(
                rf"^(?:async )?def {re.escape(test_name)}\(",
                source,
                flags=re.MULTILINE,
            ), reference
