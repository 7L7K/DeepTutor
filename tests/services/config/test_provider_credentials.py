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
    envelope = root / f"{reference}.enc"

    assert authority.read(reference) == "sk-private"
    assert root.stat().st_mode & 0o777 == 0o700
    assert envelope.stat().st_mode & 0o777 == 0o600
    assert authority.key_path.stat().st_mode & 0o777 == 0o600
    assert b"sk-private" not in envelope.read_bytes()


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
    path = authority.root / f"{reference}.enc"
    path.chmod(0o644)

    with pytest.raises(ProviderCredentialError):
        authority.read(reference)


def test_provider_credential_wraps_malformed_envelope_as_a_safe_error(
    tmp_path: Path,
) -> None:
    authority = ProviderCredentialAuthority(tmp_path / "provider_credentials")
    reference = authority.write("secret")
    path = authority.root / f"{reference}.enc"
    path.write_bytes(b"not-an-envelope")
    path.chmod(0o600)

    with pytest.raises(ProviderCredentialError, match="malformed"):
        authority.read(reference)
    assert authority.exists(reference) is False


def test_provider_credential_rejects_hard_linked_secret_file(
    tmp_path: Path,
) -> None:
    authority = ProviderCredentialAuthority(tmp_path / "provider_credentials")
    reference = authority.write("secret")
    original = authority.root / f"{reference}.enc"
    os.link(original, tmp_path / "copied-link.enc")

    with pytest.raises(ProviderCredentialError, match="private-file"):
        authority.read(reference)


def test_provider_credential_rejects_wrong_master_key(tmp_path: Path) -> None:
    root = tmp_path / "provider_credentials"
    authority = ProviderCredentialAuthority(root)
    reference = authority.write("secret")
    authority.key_path.write_bytes(b"x" * 32)
    authority.key_path.chmod(0o600)

    with pytest.raises(ProviderCredentialError, match="cannot be decrypted"):
        authority.read(reference)


def test_provider_credential_migrates_private_legacy_json(
    tmp_path: Path,
) -> None:
    root = tmp_path / "provider_credentials"
    root.mkdir(mode=0o700)
    reference = "pcr_" + ("a" * 32)
    legacy = root / f"{reference}.json"
    legacy.write_text(
        '{"credential_ref":"'
        + reference
        + '","schema_version":1,"secret":"legacy-secret"}',
        encoding="utf-8",
    )
    legacy.chmod(0o600)
    authority = ProviderCredentialAuthority(root)

    assert authority.read(reference) == "legacy-secret"
    assert not legacy.exists()
    assert (root / f"{reference}.enc").exists()
    assert b"legacy-secret" not in (root / f"{reference}.enc").read_bytes()


def test_provider_credential_finishes_interrupted_legacy_cleanup(
    tmp_path: Path,
) -> None:
    root = tmp_path / "provider_credentials"
    authority = ProviderCredentialAuthority(root)
    reference = authority.write("same-secret")
    legacy = root / f"{reference}.json"
    legacy.write_text(
        '{"credential_ref":"'
        + reference
        + '","schema_version":1,"secret":"same-secret"}',
        encoding="utf-8",
    )
    legacy.chmod(0o600)

    assert authority.read(reference) == "same-secret"
    assert not legacy.exists()


def test_provider_credential_rejects_inconsistent_interrupted_migration(
    tmp_path: Path,
) -> None:
    root = tmp_path / "provider_credentials"
    authority = ProviderCredentialAuthority(root)
    reference = authority.write("encrypted-secret")
    legacy = root / f"{reference}.json"
    legacy.write_text(
        '{"credential_ref":"'
        + reference
        + '","schema_version":1,"secret":"different-secret"}',
        encoding="utf-8",
    )
    legacy.chmod(0o600)

    with pytest.raises(ProviderCredentialError, match="inconsistent"):
        authority.read(reference)
    assert legacy.exists()
