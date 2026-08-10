from __future__ import annotations

from pathlib import Path
import sqlite3
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
            pricing_version="test-v1",
            input_tokens=100,
            output_tokens=50,
            estimated_cost_microusd=125,
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
        pricing_version="test-v1",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_microusd=125,
    )
    replay = ledger.reserve(
        operation_id="ofg_once",
        owner_user_id="u_alice",
        provider="openai",
        requested_model="gpt-5-mini",
        pricing_version="test-v1",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_microusd=125,
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
        pricing_version="test-v1",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_microusd=125,
    )
    with pytest.raises(ProviderUsageError, match="concurrency"):
        ledger.reserve(
            operation_id="ofg_alice_2",
            owner_user_id="u_alice",
            provider="openai",
            requested_model="gpt-5-mini",
            pricing_version="test-v1",
            input_tokens=100,
            output_tokens=50,
            estimated_cost_microusd=125,
        )
    ledger.reserve(
        operation_id="ofg_bob",
        owner_user_id="u_bob",
        provider="openai",
        requested_model="gpt-5-mini",
        pricing_version="test-v1",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_microusd=125,
    )
    with pytest.raises(ProviderUsageError, match="concurrency"):
        ledger.reserve(
            operation_id="ofg_carol",
            owner_user_id="u_carol",
            provider="openai",
            requested_model="gpt-5-mini",
            pricing_version="test-v1",
            input_tokens=100,
            output_tokens=50,
            estimated_cost_microusd=125,
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
        pricing_version="test-v1",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_microusd=125,
    )
    ledger.release("ofg_release")
    ledger.reserve(
        operation_id="ofg_uncertain",
        owner_user_id="u_alice",
        provider="openai",
        requested_model="gpt-5-mini",
        pricing_version="test-v1",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_microusd=125,
    )
    ledger.mark_uncertain("ofg_uncertain")
    with pytest.raises(ProviderUsageError, match="daily token"):
        ledger.reserve(
            operation_id="ofg_over_budget",
            owner_user_id="u_alice",
            provider="openai",
            requested_model="gpt-5-mini",
            pricing_version="test-v1",
            input_tokens=100,
            output_tokens=50,
            estimated_cost_microusd=125,
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
        pricing_version="test-v1",
        input_tokens=10,
        output_tokens=10,
        estimated_cost_microusd=25,
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
            pricing_version="test-v1",
            input_tokens=1,
            output_tokens=1,
            estimated_cost_microusd=3,
        )


def test_daily_output_limit_can_be_disabled_for_bounded_campaign_only(
    tmp_path: Path,
) -> None:
    ledger = ProviderUsageLedger(tmp_path / "usage" / "provider_usage.db")
    ledger.configure(
        _enabled(
            max_daily_output_tokens_per_user=50,
            max_daily_output_tokens_global=50,
        )
    )

    reservation = ledger.reserve(
        operation_id="ofg_campaign_override",
        owner_user_id="u_alice",
        provider="openai",
        requested_model="gpt-5.6-luna",
        pricing_version="test-v1",
        input_tokens=1,
        output_tokens=60,
        estimated_cost_microusd=125,
        enforce_daily_output_limits=False,
    )

    assert reservation.state == "reserved"
    assert ledger.load_policy().max_daily_output_tokens_per_user == 50
    assert ledger.load_policy().max_daily_output_tokens_global == 50
    ledger.release("ofg_campaign_override")


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
        pricing_version="test-v1",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_microusd=125,
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
        pricing_version="test-v1",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_microusd=125,
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
            pricing_version="test-v1",
            input_tokens=100,
            output_tokens=50,
            estimated_cost_microusd=125,
        )


def test_lifetime_cost_cap_survives_restart_and_counts_uncertain_work(
    tmp_path: Path,
) -> None:
    path = tmp_path / "usage" / "provider_usage.db"
    ledger = ProviderUsageLedger(path)
    ledger.configure(_enabled(max_lifetime_cost_microusd=200))
    ledger.reserve(
        operation_id="ofg_first_cost",
        owner_user_id="u_alice",
        provider="openai",
        requested_model="gpt-5-mini",
        pricing_version="test-v1",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_microusd=125,
    )
    ledger.mark_uncertain("ofg_first_cost")

    restarted = ProviderUsageLedger(path)
    with pytest.raises(ProviderUsageError, match="lifetime cost"):
        restarted.reserve(
            operation_id="ofg_after_restart_cost",
            owner_user_id="u_bob",
            provider="openai",
            requested_model="gpt-5-mini",
            pricing_version="test-v1",
            input_tokens=100,
            output_tokens=50,
            estimated_cost_microusd=100,
        )

    summary = restarted.usage_summary()
    assert summary == {
        "settled_cost_microusd": 0,
        "reserved_or_uncertain_cost_microusd": 125,
        "admitted_cost_microusd": 125,
        "alert_threshold_microusd": 100,
        "remaining_cost_microusd": 75,
    }


def test_pre_call_release_restores_lifetime_capacity(tmp_path: Path) -> None:
    ledger = ProviderUsageLedger(tmp_path / "usage" / "provider_usage.db")
    ledger.configure(_enabled(max_lifetime_cost_microusd=125))
    ledger.reserve(
        operation_id="ofg_released_cost",
        owner_user_id="u_alice",
        provider="openai",
        requested_model="gpt-5-mini",
        pricing_version="test-v1",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_microusd=125,
    )
    ledger.release("ofg_released_cost")

    admitted = ledger.reserve(
        operation_id="ofg_replacement_cost",
        owner_user_id="u_alice",
        provider="openai",
        requested_model="gpt-5-mini",
        pricing_version="test-v1",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_microusd=125,
    )
    assert admitted.state == "reserved"
    assert ledger.usage_summary()["remaining_cost_microusd"] == 0


def test_reservation_rechecks_pricing_inside_admission_transaction(
    tmp_path: Path,
) -> None:
    ledger = ProviderUsageLedger(tmp_path / "usage" / "provider_usage.db")
    ledger.configure(_enabled())

    with pytest.raises(ProviderUsageError, match="pricing is not qualified"):
        ledger.reserve(
            operation_id="ofg_stale_pricing",
            owner_user_id="u_alice",
            provider="openai",
            requested_model="gpt-5-mini",
            pricing_version="stale-pricing",
            input_tokens=100,
            output_tokens=50,
            estimated_cost_microusd=125,
        )

    assert ledger.usage_summary()["admitted_cost_microusd"] == 0


def test_default_pilot_reports_quarterly_alert_thresholds(tmp_path: Path) -> None:
    ledger = ProviderUsageLedger(tmp_path / "usage" / "provider_usage.db")
    ledger.configure(_enabled())
    ledger.reserve(
        operation_id="ofg_first_alert",
        owner_user_id="u_alice",
        provider="openai",
        requested_model="gpt-5-mini",
        pricing_version="test-v1",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_microusd=2_500_000,
    )

    assert ledger.usage_summary()["alert_threshold_microusd"] == 2_500_000


def test_existing_provider_ledger_adds_cost_authority_without_reset(
    tmp_path: Path,
) -> None:
    path = tmp_path / "usage" / "provider_usage.db"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE provider_usage_policy (
                singleton INTEGER PRIMARY KEY CHECK (singleton=1),
                enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
                max_concurrent_per_user INTEGER NOT NULL,
                max_concurrent_global INTEGER NOT NULL,
                max_daily_input_tokens_per_user INTEGER NOT NULL,
                max_daily_output_tokens_per_user INTEGER NOT NULL,
                max_daily_input_tokens_global INTEGER NOT NULL,
                max_daily_output_tokens_global INTEGER NOT NULL,
                pricing_version TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE provider_usage_reservations (
                operation_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                requested_model TEXT NOT NULL,
                reserved_input_tokens INTEGER NOT NULL,
                reserved_output_tokens INTEGER NOT NULL,
                settled_input_tokens INTEGER,
                settled_output_tokens INTEGER,
                estimated_cost_microusd INTEGER,
                pricing_version TEXT NOT NULL,
                state TEXT NOT NULL,
                usage_day TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                settled_at REAL
            );
            INSERT INTO provider_usage_policy VALUES
                (1,0,1,2,250000,50000,1000000,200000,'legacy-v1',1.0);
            INSERT INTO provider_usage_reservations VALUES
                ('ofg_legacy','u_alice','openai','gpt-5-mini',
                 100,50,80,40,75,'legacy-v1','settled',
                 '2026-07-29',1.0,2.0,2.0);
            """
        )

    ledger = ProviderUsageLedger(path)

    assert ledger.load_policy().max_lifetime_cost_microusd == 10_000_000
    assert ledger.usage_summary()["settled_cost_microusd"] == 75
    with ledger._connect() as connection:
        row = connection.execute(
            """SELECT reserved_cost_microusd
               FROM provider_usage_reservations
               WHERE operation_id='ofg_legacy'"""
        ).fetchone()
    assert row is not None and row["reserved_cost_microusd"] == 0
