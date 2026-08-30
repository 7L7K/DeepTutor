from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from deeptutor.courses import source_admission
from deeptutor.courses.source_admission import (
    CourseSourceAdmissionError,
    CourseSourceAdmissionLedger,
    CourseSourceAdmissionLimitError,
)


def _admit(
    ledger: CourseSourceAdmissionLedger,
    operation_id: str,
    owner_user_id: str,
    *,
    provider: str = "llamaindex",
    admitted_input_bytes: int = 1024,
):
    return ledger.admit(
        operation_id=operation_id,
        owner_user_id=owner_user_id,
        provider=provider,
        admitted_input_bytes=admitted_input_bytes,
    )


def test_lifetime_admission_is_idempotent_and_survives_restart(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(source_admission, "COURSE_SOURCE_MAX_LIFETIME_PER_USER", 1)
    monkeypatch.setattr(source_admission, "COURSE_SOURCE_MAX_LIFETIME_GLOBAL", 2)
    path = tmp_path / "settings" / "course_source_admission.db"
    ledger = CourseSourceAdmissionLedger(path)

    first = _admit(ledger, "csi_first", "user-a")
    replay = _admit(ledger, "csi_first", "user-a")
    assert replay == first
    with pytest.raises(CourseSourceAdmissionError, match="admitted differently"):
        _admit(
            ledger,
            "csi_first",
            "user-a",
            admitted_input_bytes=2048,
        )
    with pytest.raises(CourseSourceAdmissionLimitError, match="this account"):
        _admit(ledger, "csi_second", "user-a")

    _admit(ledger, "csi_third", "user-b")
    restarted = CourseSourceAdmissionLedger(path)
    with pytest.raises(CourseSourceAdmissionLimitError, match="controlled-beta"):
        _admit(restarted, "csi_fourth", "user-c")


def test_cross_course_lifetime_race_admits_only_one_owner_operation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(source_admission, "COURSE_SOURCE_MAX_LIFETIME_PER_USER", 1)
    monkeypatch.setattr(source_admission, "COURSE_SOURCE_MAX_LIFETIME_GLOBAL", 10)
    path = tmp_path / "settings" / "course_source_admission.db"
    first = CourseSourceAdmissionLedger(path)
    second = CourseSourceAdmissionLedger(path)

    def attempt(ledger: CourseSourceAdmissionLedger, suffix: str) -> str:
        try:
            _admit(ledger, f"csi_{suffix}", "same-owner")
        except CourseSourceAdmissionLimitError:
            return "denied"
        return "admitted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda item: attempt(*item),
                ((first, "course-a"), (second, "course-b")),
            )
        )

    assert sorted(outcomes) == ["admitted", "denied"]


@pytest.mark.parametrize(
    "operation_id,owner,provider,size",
    [
        ("bad", "user-a", "llamaindex", 1),
        ("csi_ok", "", "llamaindex", 1),
        ("csi_ok", "user-a", "", 1),
        ("csi_ok", "user-a", "llamaindex", -1),
        ("csi_ok", "user-a", "llamaindex", True),
    ],
)
def test_admission_rejects_unbound_or_malformed_identity(
    tmp_path, operation_id, owner, provider, size
) -> None:
    ledger = CourseSourceAdmissionLedger(tmp_path / "settings" / "admission.db")
    with pytest.raises(CourseSourceAdmissionError, match="invalid"):
        _admit(
            ledger,
            operation_id,
            owner,
            provider=provider,
            admitted_input_bytes=size,
        )
