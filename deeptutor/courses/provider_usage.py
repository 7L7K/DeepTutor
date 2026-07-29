"""Single-host paid-provider admission and accounting authority.

This ledger is administrative metadata.  It deliberately stores no prompt,
source excerpt, transcript, card, learner response, or provider credential.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
import threading
import time

from deeptutor.multi_user.paths import get_admin_path_service


class ProviderUsageError(RuntimeError):
    """Paid-provider admission, accounting, or configuration failed."""


@dataclass(frozen=True)
class ProviderUsagePolicy:
    enabled: bool = False
    max_concurrent_per_user: int = 1
    max_concurrent_global: int = 2
    max_daily_input_tokens_per_user: int = 250_000
    max_daily_output_tokens_per_user: int = 50_000
    max_daily_input_tokens_global: int = 1_000_000
    max_daily_output_tokens_global: int = 200_000
    pricing_version: str = "unqualified"

    def __post_init__(self) -> None:
        numeric = (
            self.max_concurrent_per_user,
            self.max_concurrent_global,
            self.max_daily_input_tokens_per_user,
            self.max_daily_output_tokens_per_user,
            self.max_daily_input_tokens_global,
            self.max_daily_output_tokens_global,
        )
        if any(isinstance(item, bool) or item < 1 for item in numeric):
            raise ProviderUsageError("Provider usage policy limits must be positive")
        if (
            self.max_concurrent_per_user > self.max_concurrent_global
            or self.max_daily_input_tokens_per_user
            > self.max_daily_input_tokens_global
            or self.max_daily_output_tokens_per_user
            > self.max_daily_output_tokens_global
            or not self.pricing_version
            or len(self.pricing_version) > 80
        ):
            raise ProviderUsageError("Provider usage policy is inconsistent")


@dataclass(frozen=True)
class ProviderUsageReservation:
    operation_id: str
    owner_user_id: str
    provider: str
    requested_model: str
    reserved_input_tokens: int
    reserved_output_tokens: int
    state: str
    usage_day: str
    pricing_version: str


class ProviderUsageLedger:
    """Durable global gate for one persistent local beta process."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._initialize()

    @staticmethod
    def _usage_day() -> str:
        return datetime.now(UTC).date().isoformat()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.path.parent.chmod(0o700)
        except OSError as exc:
            raise ProviderUsageError("Provider usage directory is unsafe") from exc
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS provider_usage_policy (
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
                CREATE TABLE IF NOT EXISTS provider_usage_reservations (
                    operation_id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    requested_model TEXT NOT NULL,
                    reserved_input_tokens INTEGER NOT NULL CHECK (reserved_input_tokens>=1),
                    reserved_output_tokens INTEGER NOT NULL CHECK (reserved_output_tokens>=1),
                    settled_input_tokens INTEGER CHECK (settled_input_tokens>=0),
                    settled_output_tokens INTEGER CHECK (settled_output_tokens>=0),
                    estimated_cost_microusd INTEGER CHECK (estimated_cost_microusd>=0),
                    pricing_version TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN ('reserved','settled','released','uncertain')
                    ),
                    usage_day TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    settled_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_provider_usage_owner_day
                    ON provider_usage_reservations(owner_user_id,usage_day,state);
                CREATE INDEX IF NOT EXISTS idx_provider_usage_day
                    ON provider_usage_reservations(usage_day,state);
                """
            )
            default = ProviderUsagePolicy()
            connection.execute(
                """INSERT OR IGNORE INTO provider_usage_policy
                   (singleton,enabled,max_concurrent_per_user,max_concurrent_global,
                    max_daily_input_tokens_per_user,max_daily_output_tokens_per_user,
                    max_daily_input_tokens_global,max_daily_output_tokens_global,
                    pricing_version,updated_at)
                   VALUES (1,?,?,?,?,?,?,?,?,?)""",
                (
                    int(default.enabled),
                    default.max_concurrent_per_user,
                    default.max_concurrent_global,
                    default.max_daily_input_tokens_per_user,
                    default.max_daily_output_tokens_per_user,
                    default.max_daily_input_tokens_global,
                    default.max_daily_output_tokens_global,
                    default.pricing_version,
                    time.time(),
                ),
            )
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{self.path}{suffix}")
            if candidate.exists():
                candidate.chmod(0o600)

    @staticmethod
    def _policy(row: sqlite3.Row) -> ProviderUsagePolicy:
        return ProviderUsagePolicy(
            enabled=bool(row["enabled"]),
            max_concurrent_per_user=int(row["max_concurrent_per_user"]),
            max_concurrent_global=int(row["max_concurrent_global"]),
            max_daily_input_tokens_per_user=int(
                row["max_daily_input_tokens_per_user"]
            ),
            max_daily_output_tokens_per_user=int(
                row["max_daily_output_tokens_per_user"]
            ),
            max_daily_input_tokens_global=int(row["max_daily_input_tokens_global"]),
            max_daily_output_tokens_global=int(row["max_daily_output_tokens_global"]),
            pricing_version=str(row["pricing_version"]),
        )

    def load_policy(self) -> ProviderUsagePolicy:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM provider_usage_policy WHERE singleton=1"
            ).fetchone()
        if row is None:
            raise ProviderUsageError("Provider usage policy is unavailable")
        return self._policy(row)

    def configure(self, policy: ProviderUsagePolicy) -> ProviderUsagePolicy:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE provider_usage_policy SET
                   enabled=?,max_concurrent_per_user=?,max_concurrent_global=?,
                   max_daily_input_tokens_per_user=?,
                   max_daily_output_tokens_per_user=?,
                   max_daily_input_tokens_global=?,
                   max_daily_output_tokens_global=?,pricing_version=?,updated_at=?
                   WHERE singleton=1""",
                (
                    int(policy.enabled),
                    policy.max_concurrent_per_user,
                    policy.max_concurrent_global,
                    policy.max_daily_input_tokens_per_user,
                    policy.max_daily_output_tokens_per_user,
                    policy.max_daily_input_tokens_global,
                    policy.max_daily_output_tokens_global,
                    policy.pricing_version,
                    time.time(),
                ),
            )
        return policy

    @staticmethod
    def _reservation(row: sqlite3.Row) -> ProviderUsageReservation:
        return ProviderUsageReservation(
            operation_id=str(row["operation_id"]),
            owner_user_id=str(row["owner_user_id"]),
            provider=str(row["provider"]),
            requested_model=str(row["requested_model"]),
            reserved_input_tokens=int(row["reserved_input_tokens"]),
            reserved_output_tokens=int(row["reserved_output_tokens"]),
            state=str(row["state"]),
            usage_day=str(row["usage_day"]),
            pricing_version=str(row["pricing_version"]),
        )

    def reserve(
        self,
        *,
        operation_id: str,
        owner_user_id: str,
        provider: str,
        requested_model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> ProviderUsageReservation:
        if (
            not operation_id.startswith("ofg_")
            or not owner_user_id
            or not provider
            or not requested_model
            or isinstance(input_tokens, bool)
            or isinstance(output_tokens, bool)
            or input_tokens < 1
            or output_tokens < 1
        ):
            raise ProviderUsageError("Provider usage reservation is invalid")
        usage_day = self._usage_day()
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # A killed process cannot release its in-flight reservation. The
            # provider runtime is bounded to 120 seconds, so a five-minute
            # reservation is no longer live. Retain it as an uncertain daily
            # charge while releasing the concurrency slot.
            connection.execute(
                """UPDATE provider_usage_reservations
                   SET state='uncertain',updated_at=?
                   WHERE state='reserved' AND updated_at<=?""",
                (now, now - 300),
            )
            prior = connection.execute(
                "SELECT * FROM provider_usage_reservations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if prior is not None:
                expected = (
                    owner_user_id,
                    provider,
                    requested_model,
                    input_tokens,
                    output_tokens,
                )
                actual = (
                    str(prior["owner_user_id"]),
                    str(prior["provider"]),
                    str(prior["requested_model"]),
                    int(prior["reserved_input_tokens"]),
                    int(prior["reserved_output_tokens"]),
                )
                if actual != expected:
                    raise ProviderUsageError(
                        "Provider usage operation was already reserved differently"
                    )
                if str(prior["state"]) != "reserved":
                    raise ProviderUsageError(
                        "Provider usage operation is not available for another call"
                    )
                return self._reservation(prior)
            policy_row = connection.execute(
                "SELECT * FROM provider_usage_policy WHERE singleton=1"
            ).fetchone()
            if policy_row is None:
                raise ProviderUsageError("Provider usage policy is unavailable")
            policy = self._policy(policy_row)
            if not policy.enabled:
                raise ProviderUsageError("Paid provider generation is disabled")
            active_global = int(
                connection.execute(
                    """SELECT COUNT(*) FROM provider_usage_reservations
                       WHERE state='reserved'"""
                ).fetchone()[0]
            )
            active_owner = int(
                connection.execute(
                    """SELECT COUNT(*) FROM provider_usage_reservations
                       WHERE state='reserved' AND owner_user_id=?""",
                    (owner_user_id,),
                ).fetchone()[0]
            )
            if (
                active_owner >= policy.max_concurrent_per_user
                or active_global >= policy.max_concurrent_global
            ):
                raise ProviderUsageError("Paid provider concurrency limit reached")
            counted_states = ("reserved", "settled", "uncertain")
            placeholders = ",".join("?" for _ in counted_states)
            owner_totals = connection.execute(
                f"""SELECT
                    COALESCE(SUM(COALESCE(settled_input_tokens,reserved_input_tokens)),0),
                    COALESCE(SUM(COALESCE(settled_output_tokens,reserved_output_tokens)),0)
                    FROM provider_usage_reservations
                    WHERE usage_day=? AND owner_user_id=?
                      AND state IN ({placeholders})""",
                (usage_day, owner_user_id, *counted_states),
            ).fetchone()
            global_totals = connection.execute(
                f"""SELECT
                    COALESCE(SUM(COALESCE(settled_input_tokens,reserved_input_tokens)),0),
                    COALESCE(SUM(COALESCE(settled_output_tokens,reserved_output_tokens)),0)
                    FROM provider_usage_reservations
                    WHERE usage_day=? AND state IN ({placeholders})""",
                (usage_day, *counted_states),
            ).fetchone()
            if (
                int(owner_totals[0]) + input_tokens
                > policy.max_daily_input_tokens_per_user
                or int(owner_totals[1]) + output_tokens
                > policy.max_daily_output_tokens_per_user
                or int(global_totals[0]) + input_tokens
                > policy.max_daily_input_tokens_global
                or int(global_totals[1]) + output_tokens
                > policy.max_daily_output_tokens_global
            ):
                raise ProviderUsageError("Paid provider daily token limit reached")
            connection.execute(
                """INSERT INTO provider_usage_reservations
                   (operation_id,owner_user_id,provider,requested_model,
                    reserved_input_tokens,reserved_output_tokens,
                    settled_input_tokens,settled_output_tokens,
                    estimated_cost_microusd,pricing_version,state,usage_day,
                    created_at,updated_at,settled_at)
                   VALUES (?,?,?,?,?,?,NULL,NULL,NULL,?,'reserved',?,?,?,NULL)""",
                (
                    operation_id,
                    owner_user_id,
                    provider,
                    requested_model,
                    input_tokens,
                    output_tokens,
                    policy.pricing_version,
                    usage_day,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM provider_usage_reservations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
        assert row is not None
        return self._reservation(row)

    def settle(
        self,
        operation_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_microusd: int,
    ) -> None:
        if min(input_tokens, output_tokens, estimated_cost_microusd) < 0:
            raise ProviderUsageError("Provider settlement is invalid")
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            reservation = connection.execute(
                """SELECT reserved_input_tokens,reserved_output_tokens,state
                   FROM provider_usage_reservations WHERE operation_id=?""",
                (operation_id,),
            ).fetchone()
            if reservation is None or str(reservation["state"]) != "reserved":
                raise ProviderUsageError("Provider reservation cannot be settled")
            if (
                input_tokens > int(reservation["reserved_input_tokens"])
                or output_tokens > int(reservation["reserved_output_tokens"])
            ):
                # The provider call has already happened, so releasing the
                # reservation would fail open. Retain the reported charge as
                # uncertain so it counts against daily budgets and requires
                # operator investigation before any retry.
                connection.execute(
                    """UPDATE provider_usage_reservations
                       SET state='uncertain',settled_input_tokens=?,
                           settled_output_tokens=?,estimated_cost_microusd=?,
                           settled_at=?,updated_at=?
                       WHERE operation_id=? AND state='reserved'""",
                    (
                        input_tokens,
                        output_tokens,
                        estimated_cost_microusd,
                        now,
                        now,
                        operation_id,
                    ),
                )
                connection.commit()
                raise ProviderUsageError(
                    "Provider usage exceeded its conservative reservation"
                )
            result = connection.execute(
                """UPDATE provider_usage_reservations
                   SET state='settled',settled_input_tokens=?,
                       settled_output_tokens=?,estimated_cost_microusd=?,
                       settled_at=?,updated_at=?
                   WHERE operation_id=? AND state='reserved'""",
                (
                    input_tokens,
                    output_tokens,
                    estimated_cost_microusd,
                    now,
                    now,
                    operation_id,
                ),
            )
            if result.rowcount != 1:
                raise ProviderUsageError("Provider reservation cannot be settled")

    def release(self, operation_id: str) -> None:
        with self._lock, self._connect() as connection:
            result = connection.execute(
                """UPDATE provider_usage_reservations
                   SET state='released',updated_at=?
                   WHERE operation_id=? AND state='reserved'""",
                (time.time(), operation_id),
            )
            if result.rowcount != 1:
                raise ProviderUsageError("Provider reservation cannot be released")

    def mark_uncertain(self, operation_id: str) -> None:
        with self._lock, self._connect() as connection:
            result = connection.execute(
                """UPDATE provider_usage_reservations
                   SET state='uncertain',updated_at=?
                   WHERE operation_id=? AND state='reserved'""",
                (time.time(), operation_id),
            )
            if result.rowcount != 1:
                raise ProviderUsageError("Provider reservation cannot be reconciled")


def get_provider_usage_ledger() -> ProviderUsageLedger:
    """Resolve the single-host administrative usage authority."""

    return ProviderUsageLedger(
        get_admin_path_service().get_settings_dir() / "provider_usage.db"
    )


__all__ = [
    "ProviderUsageError",
    "ProviderUsageLedger",
    "ProviderUsagePolicy",
    "ProviderUsageReservation",
    "get_provider_usage_ledger",
]
