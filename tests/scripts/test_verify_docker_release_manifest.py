"""Tests for attested Docker release manifest validation."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "verify-docker-release-manifest.py"
AMD64_PAYLOAD = f"sha256:{'a' * 64}"
ARM64_PAYLOAD = f"sha256:{'b' * 64}"
AMD64_ATTESTATION = f"sha256:{'c' * 64}"
ARM64_ATTESTATION = f"sha256:{'d' * 64}"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("docker_release_verifier", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = _load_script()


def _payload(digest: str, architecture: str) -> dict[str, object]:
    return {
        "digest": digest,
        "platform": {"os": "linux", "architecture": architecture},
    }


def _attestation(digest: str, payload: str) -> dict[str, object]:
    return {
        "digest": digest,
        "platform": {"os": "unknown", "architecture": "unknown"},
        "annotations": {
            "vnd.docker.reference.type": "attestation-manifest",
            "vnd.docker.reference.digest": payload,
        },
    }


def _release_index() -> dict[str, object]:
    return {
        "manifests": [
            _payload(AMD64_PAYLOAD, "amd64"),
            _attestation(AMD64_ATTESTATION, AMD64_PAYLOAD),
            _payload(ARM64_PAYLOAD, "arm64"),
            _attestation(ARM64_ATTESTATION, ARM64_PAYLOAD),
        ]
    }


def test_release_index_accepts_exact_payloads_and_attestation_references() -> None:
    result = VERIFIER.validate_release_index(
        _release_index(),
        amd64_payload=AMD64_PAYLOAD,
        arm64_payload=ARM64_PAYLOAD,
    )

    assert result == {
        "amd64": [AMD64_ATTESTATION],
        "arm64": [ARM64_ATTESTATION],
    }


def test_release_index_rejects_an_unverified_payload() -> None:
    with pytest.raises(ValueError, match="Unexpected amd64 payload"):
        VERIFIER.validate_release_index(
            _release_index(),
            amd64_payload=f"sha256:{'e' * 64}",
            arm64_payload=ARM64_PAYLOAD,
        )


def test_release_index_rejects_extra_runnable_payload() -> None:
    index = _release_index()
    index["manifests"].append(_payload(f"sha256:{'e' * 64}", "ppc64le"))

    with pytest.raises(ValueError, match="exactly two runnable payloads"):
        VERIFIER.validate_release_index(
            index,
            amd64_payload=AMD64_PAYLOAD,
            arm64_payload=ARM64_PAYLOAD,
        )


def test_platform_index_rejects_attestation_for_another_payload() -> None:
    index = {
        "manifests": [
            _payload(AMD64_PAYLOAD, "amd64"),
            _attestation(AMD64_ATTESTATION, ARM64_PAYLOAD),
        ]
    }

    with pytest.raises(ValueError, match="attestation for another payload"):
        VERIFIER.validate_platform_index(index, os_name="linux", architecture="amd64")


def test_release_index_rejects_attestation_for_unexpected_payload() -> None:
    index = _release_index()
    index["manifests"].append(_attestation(f"sha256:{'e' * 64}", f"sha256:{'f' * 64}"))

    with pytest.raises(ValueError, match="attestation for an unexpected payload"):
        VERIFIER.validate_release_index(
            index,
            amd64_payload=AMD64_PAYLOAD,
            arm64_payload=ARM64_PAYLOAD,
        )


def test_attestations_require_both_sbom_and_provenance() -> None:
    complete = {
        "layers": [
            {"annotations": {"in-toto.io/predicate-type": "https://spdx.dev/Document"}},
            {"annotations": {"in-toto.io/predicate-type": "https://slsa.dev/provenance/v1"}},
        ]
    }
    VERIFIER.validate_attestations([complete])

    with pytest.raises(ValueError, match="SLSA provenance"):
        VERIFIER.validate_attestations([{"layers": complete["layers"][:1]}])
