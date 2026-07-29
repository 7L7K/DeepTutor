from __future__ import annotations

import os
from pathlib import Path

import pytest

from deeptutor.services.config.provider_credentials import (
    ProviderCredentialAuthority,
    ProviderCredentialError,
)


def test_provider_credential_round_trip_uses_private_permissions(tmp_path: Path) -> None:
    root = tmp_path / "provider_credentials"
    authority = ProviderCredentialAuthority(root)

    reference = authority.write("sk-private")

    assert authority.read(reference) == "sk-private"
    assert root.stat().st_mode & 0o777 == 0o700
    assert (root / f"{reference}.json").stat().st_mode & 0o777 == 0o600


def test_provider_credential_update_preserves_reference(tmp_path: Path) -> None:
    authority = ProviderCredentialAuthority(tmp_path / "provider_credentials")
    reference = authority.write("first")

    updated = authority.write("second", credential_ref=reference)

    assert updated == reference
    assert authority.read(reference) == "second"


def test_provider_credential_rejects_symlink_target(tmp_path: Path) -> None:
    authority = ProviderCredentialAuthority(tmp_path / "provider_credentials")
    authority.root.mkdir(mode=0o700)
    reference = "pcr_" + ("a" * 32)
    outside = tmp_path / "outside"
    outside.write_text("do-not-touch", encoding="utf-8")
    os.symlink(outside, authority.root / f"{reference}.json")

    with pytest.raises(ProviderCredentialError):
        authority.write("secret", credential_ref=reference)

    assert outside.read_text(encoding="utf-8") == "do-not-touch"


def test_provider_credential_rejects_world_readable_file(tmp_path: Path) -> None:
    authority = ProviderCredentialAuthority(tmp_path / "provider_credentials")
    reference = authority.write("secret")
    path = authority.root / f"{reference}.json"
    path.chmod(0o644)

    with pytest.raises(ProviderCredentialError):
        authority.read(reference)


def test_provider_credential_wraps_malformed_json_as_a_safe_error(
    tmp_path: Path,
) -> None:
    authority = ProviderCredentialAuthority(tmp_path / "provider_credentials")
    reference = authority.write("secret")
    path = authority.root / f"{reference}.json"
    path.write_text("{not-json", encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(ProviderCredentialError, match="malformed"):
        authority.read(reference)
    assert authority.exists(reference) is False


def test_provider_credential_rejects_hard_linked_secret_file(
    tmp_path: Path,
) -> None:
    authority = ProviderCredentialAuthority(tmp_path / "provider_credentials")
    reference = authority.write("secret")
    original = authority.root / f"{reference}.json"
    os.link(original, tmp_path / "copied-link.json")

    with pytest.raises(ProviderCredentialError, match="private-file"):
        authority.read(reference)
