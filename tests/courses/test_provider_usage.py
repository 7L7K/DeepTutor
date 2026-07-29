from __future__ import annotations

from pathlib import Path
import time

import pytest

from deeptutor.courses.provider_usage import (
    ProviderUsageError,
    ProviderUsageLedger,
    ProviderUsagePolicy,
)


def _enabled(**overrides: object) -> ProviderUsagePolicy:
    return ProviderUsagePolicy(
        enabled=True,
        pricing_version="test-v1",
        **overrides,
    )


def test_paid_provider_is_disabled_by_default(tmp_path: Path) -> None:
    ledger = ProviderUsageLedger(tmp_path / "usage" / "provider_usage.db")

    with pytest.raises(ProviderUsageError, match="disabled"):
        ledger.reserve(
            operation_id="ofg_disabled",
            owner_user_id="u_alice",
            provider="openai",
            requested_model="gpt-5-mini",
            input_tokens=100,
            output_tokens=50,
        )


def test_reservation_is_idempotent_and_settles_without_content(tmp_path: Path) -> None:
    path = tmp_path / "usage" / "provider_usage.db"
    ledger = ProviderUsageLedger(path)
    ledger.configure(_enabled())

    first = ledger.reserve(
        operation_id="ofg_once",
        owner_user_id="u_alice",
        provider="openai",
        requested_model="gpt-5-mini",
        input_tokens=100,
        output_tokens=50,
    )
    replay = ledger.reserve(
        operation_id="ofg_once",
        owner_user_id="u_alice",
        provider="openai",
        requested_model="gpt-5-mini",
        input_tokens=100,
        output_tokens=50,
    )
    assert replay == first

    ledger.settle(
        "ofg_once",
        input_tokens=75,
        output_tokens=30,
        estimated_cost_microusd=123,
    )
    schema = path.read_bytes()
    assert b"prompt" not in schema
    assert b"transcript" not in schema
    assert b"sk-" not in schema


def test_user_and_global_concurrency_are_independent(tmp_path: Path) -> None:
    ledger = ProviderUsageLedger(tmp_path / "usage" / "provider_usage.db")
    ledger.configure(_enabled())
    ledger.reserve(
        operation_id="ofg_alice",
        owner_user_id="u_alice",
        provider="openai",
        requested_model="gpt-5-mini",
        input_tokens=100,
        output_tokens=50,
    )
    with pytest.raises(ProviderUsageError, match="concurrency"):
        ledger.reserve(
            operation_id="ofg_alice_2",
            owner_user_id="u_alice",
            provider="openai",
            requested_model="gpt-5-mini",
            input_tokens=100,
            output_tokens=50,
        )
    ledger.reserve(
        operation_id="ofg_bob",
        owner_user_id="u_bob",
        provider="openai",
        requested_model="gpt-5-mini",
        input_tokens=100,
        output_tokens=50,
    )
    with pytest.raises(ProviderUsageError, match="concurrency"):
        ledger.reserve(
            operation_id="ofg_carol",
            owner_user_id="u_carol",
            provider="openai",
            requested_model="gpt-5-mini",
            input_tokens=100,
            output_tokens=50,
        )


def test_release_frees_concurrency_but_uncertain_keeps_budget(tmp_path: Path) -> None:
    ledger = ProviderUsageLedger(tmp_path / "usage" / "provider_usage.db")
    ledger.configure(
        _enabled(
            max_daily_input_tokens_per_user=150,
            max_daily_output_tokens_per_user=100,
            max_daily_input_tokens_global=500,
            max_daily_output_tokens_global=500,
        )
    )
    ledger.reserve(
        operation_id="ofg_release",
        owner_user_id="u_alice",
        provider="openai",
        requested_model="gpt-5-mini",
        input_tokens=100,
        output_tokens=50,
    )
    ledger.release("ofg_release")
    ledger.reserve(
        operation_id="ofg_uncertain",
        owner_user_id="u_alice",
        provider="openai",
        requested_model="gpt-5-mini",
        input_tokens=100,
        output_tokens=50,
    )
    ledger.mark_uncertain("ofg_uncertain")
    with pytest.raises(ProviderUsageError, match="daily token"):
        ledger.reserve(
            operation_id="ofg_over_budget",
            owner_user_id="u_alice",
            provider="openai",
            requested_model="gpt-5-mini",
            input_tokens=100,
            output_tokens=50,
        )


def test_settlement_cannot_silently_exceed_reserved_budget(tmp_path: Path) -> None:
    path = tmp_path / "usage" / "provider_usage.db"
    ledger = ProviderUsageLedger(path)
    ledger.configure(
        _enabled(
            max_daily_input_tokens_per_user=100,
            max_daily_output_tokens_per_user=100,
            max_daily_input_tokens_global=100,
            max_daily_output_tokens_global=100,
        )
    )
    ledger.reserve(
        operation_id="ofg_overage",
        owner_user_id="u_alice",
        provider="openai",
        requested_model="gpt-5-mini",
        input_tokens=10,
        output_tokens=10,
    )

    with pytest.raises(ProviderUsageError, match="exceeded"):
        ledger.settle(
            "ofg_overage",
            input_tokens=101,
            output_tokens=101,
            estimated_cost_microusd=0,
        )

    with ledger._connect() as connection:
        row = connection.execute(
            """SELECT state,settled_input_tokens,settled_output_tokens
               FROM provider_usage_reservations WHERE operation_id='ofg_overage'"""
        ).fetchone()
    assert row is not None
    assert tuple(row) == ("uncertain", 101, 101)
    with pytest.raises(ProviderUsageError, match="daily token"):
        ledger.reserve(
            operation_id="ofg_after_overage",
            owner_user_id="u_alice",
            provider="openai",
            requested_model="gpt-5-mini",
            input_tokens=1,
            output_tokens=1,
        )


def test_stale_crash_reservation_releases_concurrency_conservatively(
    tmp_path: Path,
) -> None:
    path = tmp_path / "usage" / "provider_usage.db"
    ledger = ProviderUsageLedger(path)
    ledger.configure(_enabled(max_concurrent_global=1))
    ledger.reserve(
        operation_id="ofg_crashed",
        owner_user_id="u_alice",
        provider="openai",
        requested_model="gpt-5-mini",
        input_tokens=100,
        output_tokens=50,
    )
    with ledger._connect() as connection:
        connection.execute(
            """UPDATE provider_usage_reservations
               SET updated_at=? WHERE operation_id='ofg_crashed'""",
            (time.time() - 301,),
        )

    replacement = ledger.reserve(
        operation_id="ofg_after_restart",
        owner_user_id="u_bob",
        provider="openai",
        requested_model="gpt-5-mini",
        input_tokens=100,
        output_tokens=50,
    )

    assert replacement.state == "reserved"
    with ledger._connect() as connection:
        crashed = connection.execute(
            """SELECT state FROM provider_usage_reservations
               WHERE operation_id='ofg_crashed'"""
        ).fetchone()
    assert crashed is not None and crashed["state"] == "uncertain"
    with pytest.raises(ProviderUsageError, match="another call"):
        ledger.reserve(
            operation_id="ofg_crashed",
            owner_user_id="u_alice",
            provider="openai",
            requested_model="gpt-5-mini",
            input_tokens=100,
            output_tokens=50,
        )
