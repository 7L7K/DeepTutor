"""Validate Docker release indexes and their BuildKit attestations."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import re
import subprocess
from typing import Any

ATTESTATION_TYPE = "attestation-manifest"
REFERENCE_DIGEST = "vnd.docker.reference.digest"
REFERENCE_TYPE = "vnd.docker.reference.type"
PREDICATE_TYPE = "in-toto.io/predicate-type"
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _descriptors(index: dict[str, Any]) -> list[dict[str, Any]]:
    descriptors = index.get("manifests")
    if not isinstance(descriptors, list):
        raise ValueError("Image is not an OCI index with a manifests array")
    return descriptors


def _is_attestation(descriptor: dict[str, Any]) -> bool:
    annotations = descriptor.get("annotations", {})
    return annotations.get(REFERENCE_TYPE) == ATTESTATION_TYPE


def _digest(descriptor: dict[str, Any]) -> str:
    digest = descriptor.get("digest")
    if not isinstance(digest, str) or DIGEST_PATTERN.fullmatch(digest) is None:
        raise ValueError(f"Invalid descriptor digest: {digest!r}")
    return digest


def validate_platform_index(
    index: dict[str, Any],
    *,
    os_name: str,
    architecture: str,
    allow_other_payloads: bool = False,
) -> tuple[str, list[str]]:
    """Return the one runnable payload and its attestation manifest digests."""
    descriptors = _descriptors(index)
    payloads = [
        descriptor
        for descriptor in descriptors
        if not _is_attestation(descriptor)
        and descriptor.get("platform", {}).get("os") == os_name
        and descriptor.get("platform", {}).get("architecture") == architecture
    ]
    if len(payloads) != 1:
        raise ValueError(f"Expected one {os_name}/{architecture} payload, found {len(payloads)}")
    payload_digest = _digest(payloads[0])

    runnable = [descriptor for descriptor in descriptors if not _is_attestation(descriptor)]
    if not allow_other_payloads and len(runnable) != 1:
        raise ValueError(f"Expected one runnable payload, found {len(runnable)}")

    attestations = [descriptor for descriptor in descriptors if _is_attestation(descriptor)]
    if not attestations:
        raise ValueError(f"No attestation manifest refers to {payload_digest}")
    if not allow_other_payloads and any(
        descriptor.get("annotations", {}).get(REFERENCE_DIGEST) != payload_digest
        for descriptor in attestations
    ):
        raise ValueError("Platform index contains an attestation for another payload")
    attestations = [
        descriptor
        for descriptor in attestations
        if descriptor.get("annotations", {}).get(REFERENCE_DIGEST) == payload_digest
    ]
    if not attestations:
        raise ValueError(f"No attestation manifest refers to {payload_digest}")
    return payload_digest, [_digest(descriptor) for descriptor in attestations]


def validate_attestations(attestations: Sequence[dict[str, Any]]) -> None:
    """Require SPDX SBOM and SLSA provenance predicates across the manifests."""
    predicate_types = {
        layer.get("annotations", {}).get(PREDICATE_TYPE, "")
        for attestation in attestations
        for layer in attestation.get("layers", [])
    }
    if not any(predicate.startswith("https://spdx.dev/") for predicate in predicate_types):
        raise ValueError("Attestations do not contain an SPDX SBOM predicate")
    if not any(
        predicate.startswith("https://slsa.dev/provenance/") for predicate in predicate_types
    ):
        raise ValueError("Attestations do not contain a SLSA provenance predicate")


def validate_release_index(
    index: dict[str, Any], *, amd64_payload: str, arm64_payload: str
) -> dict[str, list[str]]:
    """Require exactly the expected payloads and attestations in a release index."""
    amd_payload, amd_attestations = validate_platform_index(
        index, os_name="linux", architecture="amd64", allow_other_payloads=True
    )
    arm_payload, arm_attestations = validate_platform_index(
        index, os_name="linux", architecture="arm64", allow_other_payloads=True
    )
    if amd_payload != amd64_payload:
        raise ValueError(f"Unexpected amd64 payload: {amd_payload}")
    if arm_payload != arm64_payload:
        raise ValueError(f"Unexpected arm64 payload: {arm_payload}")

    runnable = [descriptor for descriptor in _descriptors(index) if not _is_attestation(descriptor)]
    if len(runnable) != 2:
        raise ValueError(f"Expected exactly two runnable payloads, found {len(runnable)}")
    expected_payloads = {amd64_payload, arm64_payload}
    attestation_references = {
        descriptor.get("annotations", {}).get(REFERENCE_DIGEST)
        for descriptor in _descriptors(index)
        if _is_attestation(descriptor)
    }
    if not attestation_references.issubset(expected_payloads):
        raise ValueError("Release index contains an attestation for an unexpected payload")
    return {"amd64": amd_attestations, "arm64": arm_attestations}


def inspect_raw(reference: str) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", reference, "--raw"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object for {reference}")
    return value


def _inspect_attestations(image: str, digests: Sequence[str]) -> list[dict[str, Any]]:
    return [inspect_raw(f"{image}@{digest}") for digest in digests]


def _write_outputs(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    platform = subparsers.add_parser("platform")
    platform.add_argument("--image", required=True)
    platform.add_argument("--digest", required=True)
    platform.add_argument("--platform", required=True, choices=("linux/amd64", "linux/arm64"))
    platform.add_argument("--output", type=Path, required=True)

    release = subparsers.add_parser("release")
    release.add_argument("--image", required=True)
    release.add_argument("--digest", required=True)
    release.add_argument("--amd64-payload", required=True)
    release.add_argument("--arm64-payload", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if DIGEST_PATTERN.fullmatch(args.digest) is None:
        raise ValueError(f"Invalid image digest: {args.digest}")

    if args.command == "platform":
        os_name, architecture = args.platform.split("/", maxsplit=1)
        index = inspect_raw(f"{args.image}@{args.digest}")
        payload, attestation_digests = validate_platform_index(
            index, os_name=os_name, architecture=architecture
        )
        validate_attestations(_inspect_attestations(args.image, attestation_digests))
        _write_outputs(args.output, {"payload_digest": payload})
        print(json.dumps({"platform": args.platform, "payload_digest": payload}))
        return 0

    index = inspect_raw(f"{args.image}@{args.digest}")
    attestations = validate_release_index(
        index,
        amd64_payload=args.amd64_payload,
        arm64_payload=args.arm64_payload,
    )
    for digests in attestations.values():
        validate_attestations(_inspect_attestations(args.image, digests))
    print(
        json.dumps(
            {
                "manifest_digest": args.digest,
                "amd64_payload": args.amd64_payload,
                "arm64_payload": args.arm64_payload,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
