from __future__ import annotations

import json
import re

import pytest


def _eligible_catalog(*, count: int = 1, owner_bound: bool = False) -> dict:
    from deeptutor.services.config.text_generation_registry import (
        default_text_generation_catalog,
    )

    profiles = []
    for index in range(count):
        profiles.append(
            {
                "id": "llm-openai-global" if index == 0 else f"llm-openai-global-{index}",
                "active": True,
                "owner_bound": owner_bound,
                "ordinary_user_assignable": True,
                "api_key": "resolved-secret",
                "models": [
                    {
                        "id": "llm-gpt-5-6-luna" if index == 0 else f"luna-{index}",
                        "active": True,
                        "model": "gpt-5.6-luna",
                    }
                ],
            }
        )
    return {
        "text_generation": default_text_generation_catalog(),
        "services": {"llm": {"profiles": profiles}},
    }


def test_shared_code_is_exactly_80_bits_and_round_trips() -> None:
    from deeptutor.multi_user.enrollment import canonicalize_invite_code, generate_invite_code

    code = generate_invite_code()
    assert re.fullmatch(r"TEEECHR-[0-9A-HJKMNP-TV-Z]{4}(?:-[0-9A-HJKMNP-TV-Z]{4}){3}", code)
    assert canonicalize_invite_code(f"  {code.lower().replace('-', ' ')}\t") == code


@pytest.mark.parametrize(
    "value",
    [
        "TEEECHR-OOOO-OOOO-OOOO-OOOO",
        "TEEECHR-LLLL-LLLL-LLLL-LLLL",
        "TEEECHR-AAAA-AAAA-AAAA-AAA",
        "TEEECHR-AAAA-AAAA-AAAA-AAAA\u00a0",
    ],
)
def test_shared_code_rejects_confusables_and_non_ascii_whitespace(value: str) -> None:
    from deeptutor.multi_user.enrollment import InviteCodeError, canonicalize_invite_code

    with pytest.raises(InviteCodeError):
        canonicalize_invite_code(value)


def test_exactly_one_eligible_luna_target_is_required() -> None:
    from deeptutor.multi_user.enrollment import resolve_luna_target

    assert resolve_luna_target(_eligible_catalog(count=0), usage_policy_enabled=True) is None
    target = resolve_luna_target(_eligible_catalog(count=1), usage_policy_enabled=True)
    assert target is not None
    assert target.profile_id == "llm-openai-global"
    assert target.model_id == "llm-gpt-5-6-luna"
    assert resolve_luna_target(_eligible_catalog(count=2), usage_policy_enabled=True) is None
    assert resolve_luna_target(_eligible_catalog(owner_bound=True), usage_policy_enabled=True) is None
    assert resolve_luna_target(_eligible_catalog(), usage_policy_enabled=False) is None
    assert (
        resolve_luna_target(
            _eligible_catalog(),
            usage_policy_enabled=True,
            usage_pricing_version="stale-pricing",
        )
        is None
    )


@pytest.mark.parametrize(
    ("profile_patch", "model_patch"),
    [
        ({"active": False}, {}),
        ({"ordinary_user_assignable": False}, {}),
        ({"api_key": ""}, {}),
        ({}, {"active": False}),
        ({}, {"model": "gpt-5-mini"}),
    ],
)
def test_inactive_unassignable_uncredentialed_or_wrong_model_targets_are_rejected(
    profile_patch: dict, model_patch: dict
) -> None:
    from deeptutor.multi_user.enrollment import resolve_luna_target

    catalog = _eligible_catalog()
    profile = catalog["services"]["llm"]["profiles"][0]
    profile.update(profile_patch)
    profile["models"][0].update(model_patch)
    assert resolve_luna_target(catalog, usage_policy_enabled=True) is None


def test_catalog_active_profile_and_model_are_the_only_eligible_target() -> None:
    from copy import deepcopy

    from deeptutor.multi_user.enrollment import resolve_luna_target

    catalog = _eligible_catalog(count=1)
    inactive_profile = deepcopy(catalog["services"]["llm"]["profiles"][0])
    inactive_profile["id"] = "llm-other-global"
    inactive_profile["models"][0]["id"] = "llm-other-luna"
    catalog["services"]["llm"]["profiles"].append(inactive_profile)
    catalog["services"]["llm"]["active_profile_id"] = "llm-openai-global"
    catalog["services"]["llm"]["active_model_id"] = "llm-gpt-5-6-luna"

    target = resolve_luna_target(catalog, usage_policy_enabled=True)
    assert target is not None
    assert target.profile_id == "llm-openai-global"
    assert target.model_id == "llm-gpt-5-6-luna"


def test_create_only_identity_never_overwrites_password(mu_isolated_root) -> None:
    from deeptutor.multi_user.identity import create_user_only, get_user

    created = create_user_only("student", "$2b$12$first", user_id="u_reserved", role="user")
    assert created["id"] == "u_reserved"
    with pytest.raises(FileExistsError):
        create_user_only("student", "$2b$12$second", user_id="u_other", role="user")
    assert get_user("student")["hash"] == "$2b$12$first"


def test_enrollment_grant_has_exact_v2_shape_and_no_secret_fields(mu_isolated_root) -> None:
    from deeptutor.multi_user import enrollment
    from deeptutor.multi_user.grants import load_grant, save_grant

    journal = enrollment.create_journal(
        user_id="u_reserved",
        policy_revision=4,
        profile_id="llm-openai-global",
        model_ids=["llm-gpt-5-6-luna"],
    )
    grant = save_grant(
        "u_reserved",
        {
            "version": 2,
            "user_id": "u_reserved",
            "models": {
                "llm": [
                    {
                        "profile_id": "llm-openai-global",
                        "model_ids": ["llm-gpt-5-6-luna"],
                    }
                ]
            },
        },
        enrollment_id=journal["enrollment_id"],
    )
    enrollment.record_grant_fingerprint(journal["enrollment_id"], grant)

    persisted = load_grant("u_reserved")
    assert persisted["version"] == 2
    assert persisted["models"]["llm"] == [
        {
            "profile_id": "llm-openai-global",
            "model_ids": ["llm-gpt-5-6-luna"],
        }
    ]
    encoded = json.dumps(persisted)
    assert "model_id\"" not in encoded
    assert not any(word in encoded for word in ("api_key", "secret", "base_url"))


def test_reconciliation_deletes_only_exact_fingerprint_bound_orphan(mu_isolated_root) -> None:
    from deeptutor.multi_user import enrollment
    from deeptutor.multi_user.grants import grant_path, load_grant, save_grant

    journal = enrollment.create_journal(
        user_id="u_orphan",
        policy_revision=2,
        profile_id="llm-openai-global",
        model_ids=["llm-gpt-5-6-luna"],
    )
    grant = save_grant(
        "u_orphan",
        {"models": {"llm": [{"profile_id": "llm-openai-global", "model_ids": ["llm-gpt-5-6-luna"]}]}},
        enrollment_id=journal["enrollment_id"],
    )
    enrollment.record_grant_fingerprint(journal["enrollment_id"], grant)

    result = enrollment.reconcile_enrollment_journals()
    assert result.recovery_required is False
    assert not grant_path("u_orphan").exists()

    ambiguous = enrollment.create_journal(
        user_id="u_ambiguous",
        policy_revision=3,
        profile_id="llm-openai-global",
        model_ids=["llm-gpt-5-6-luna"],
    )
    save_grant(
        "u_ambiguous",
        {"models": {"llm": [{"profile_id": "llm-openai-global", "model_ids": ["llm-gpt-5-6-luna"]}]}},
        enrollment_id=ambiguous["enrollment_id"],
    )
    result = enrollment.reconcile_enrollment_journals()
    assert result.recovery_required is True
    assert grant_path("u_ambiguous").exists()


def test_reconciliation_keeps_exact_finalized_identity_and_rejects_mismatch(
    mu_isolated_root,
) -> None:
    from deeptutor.multi_user import enrollment
    from deeptutor.multi_user.grants import grant_path, load_grant, save_grant
    from deeptutor.multi_user.identity import create_user_only
    from deeptutor.services.file_io import atomic_write_json

    completed = enrollment.create_journal(
        user_id="u_finalized",
        policy_revision=5,
        profile_id="llm-openai-global",
        model_ids=["llm-gpt-5-6-luna"],
    )
    completed_grant = save_grant(
        "u_finalized",
        {
            "models": {
                "llm": [
                    {
                        "profile_id": "llm-openai-global",
                        "model_ids": ["llm-gpt-5-6-luna"],
                    }
                ]
            }
        },
        enrollment_id=completed["enrollment_id"],
    )
    enrollment.record_grant_fingerprint(completed["enrollment_id"], completed_grant)
    create_user_only(
        "finalized", "$2b$12$finalized", user_id="u_finalized", role="user"
    )

    finalized_result = enrollment.reconcile_enrollment_journals()
    assert finalized_result.recovery_required is False
    assert grant_path("u_finalized").exists()
    assert enrollment.load_journal(completed["enrollment_id"]) is None

    mismatched = enrollment.create_journal(
        user_id="u_mismatch",
        policy_revision=6,
        profile_id="llm-openai-global",
        model_ids=["llm-gpt-5-6-luna"],
    )
    mismatched_grant = save_grant(
        "u_mismatch",
        {
            "models": {
                "llm": [
                    {
                        "profile_id": "llm-openai-global",
                        "model_ids": ["llm-gpt-5-6-luna"],
                    }
                ]
            }
        },
        enrollment_id=mismatched["enrollment_id"],
    )
    enrollment.record_grant_fingerprint(mismatched["enrollment_id"], mismatched_grant)
    changed_grant = load_grant("u_mismatch")
    changed_grant["models"]["llm"] = []
    atomic_write_json(grant_path("u_mismatch"), changed_grant)

    mismatch_result = enrollment.reconcile_enrollment_journals()
    assert mismatch_result.recovery_required is True
    assert grant_path("u_mismatch").exists()
    assert enrollment.load_journal(mismatched["enrollment_id"]) is not None
