"""Durable controlled-beta admission for Course-source provider work.

The RAG adapters do not expose one qualified, provider-independent token or
price receipt.  Bound their total beta exposure with a persistent operation
ceiling instead: every admitted provider-backed source counts for life,
including work that later fails, is archived, or is superseded.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import threading
import time

from deeptutor.multi_user.paths import get_admin_path_service

COURSE_SOURCE_MAX_LIFETIME_PER_USER = 20
COURSE_SOURCE_MAX_LIFETIME_GLOBAL = 200


class CourseSourceAdmissionError(RuntimeError):
    """A durable Course-source operation could not be admitted."""


class CourseSourceAdmissionLimitError(CourseSourceAdmissionError):
    """The persistent controlled-beta operation ceiling was reached."""


@dataclass(frozen=True)
class CourseSourceAdmission:
    operation_id: str
    owner_user_id: str
    provider: str
    admitted_input_bytes: int
    created_at: float


class CourseSourceAdmissionLedger:
    """Atomic lifetime-operation gate for the single-host controlled beta."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.path.parent.chmod(0o700)
        except OSError as exc:
            raise CourseSourceAdmissionError("Course-source admission directory is unsafe") from exc
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS course_source_admissions (
                    operation_id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    admitted_input_bytes INTEGER NOT NULL
                        CHECK (admitted_input_bytes>=0),
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_course_source_admission_owner
                    ON course_source_admissions(owner_user_id);
                """
            )
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{self.path}{suffix}")
            if candidate.exists():
                candidate.chmod(0o600)

    @staticmethod
    def _admission(row: sqlite3.Row) -> CourseSourceAdmission:
        return CourseSourceAdmission(
            operation_id=str(row["operation_id"]),
            owner_user_id=str(row["owner_user_id"]),
            provider=str(row["provider"]),
            admitted_input_bytes=int(row["admitted_input_bytes"]),
            created_at=float(row["created_at"]),
        )

    def admit(
        self,
        *,
        operation_id: str,
        owner_user_id: str,
        provider: str,
        admitted_input_bytes: int,
    ) -> CourseSourceAdmission:
        if (
            not operation_id.startswith("csi_")
            or not owner_user_id
            or not provider
            or isinstance(admitted_input_bytes, bool)
            or not isinstance(admitted_input_bytes, int)
            or admitted_input_bytes < 0
        ):
            raise CourseSourceAdmissionError("Course-source admission is invalid")

        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT * FROM course_source_admissions WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if prior is not None:
                expected = (owner_user_id, provider, admitted_input_bytes)
                actual = (
                    str(prior["owner_user_id"]),
                    str(prior["provider"]),
                    int(prior["admitted_input_bytes"]),
                )
                if actual != expected:
                    raise CourseSourceAdmissionError(
                        "Course-source operation was already admitted differently"
                    )
                return self._admission(prior)

            global_count = int(
                connection.execute("SELECT COUNT(*) FROM course_source_admissions").fetchone()[0]
            )
            owner_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM course_source_admissions WHERE owner_user_id=?",
                    (owner_user_id,),
                ).fetchone()[0]
            )
            if owner_count >= COURSE_SOURCE_MAX_LIFETIME_PER_USER:
                raise CourseSourceAdmissionLimitError(
                    "Course-source lifetime limit reached for this account"
                )
            if global_count >= COURSE_SOURCE_MAX_LIFETIME_GLOBAL:
                raise CourseSourceAdmissionLimitError(
                    "Course-source controlled-beta lifetime limit reached"
                )
            connection.execute(
                """INSERT INTO course_source_admissions
                   (operation_id,owner_user_id,provider,admitted_input_bytes,created_at)
                   VALUES (?,?,?,?,?)""",
                (
                    operation_id,
                    owner_user_id,
                    provider,
                    admitted_input_bytes,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM course_source_admissions WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
        assert row is not None
        return self._admission(row)


def get_course_source_admission_ledger() -> CourseSourceAdmissionLedger:
    return CourseSourceAdmissionLedger(
        get_admin_path_service().get_settings_dir() / "course_source_admission.db"
    )


__all__ = [
    "COURSE_SOURCE_MAX_LIFETIME_GLOBAL",
    "COURSE_SOURCE_MAX_LIFETIME_PER_USER",
    "CourseSourceAdmission",
    "CourseSourceAdmissionError",
    "CourseSourceAdmissionLedger",
    "CourseSourceAdmissionLimitError",
    "get_course_source_admission_ledger",
]
