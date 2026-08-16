"""Static release-contract tests for the Docker publication workflow."""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "docker-release.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_each_platform_is_built_once_and_pushed_only_by_digest() -> None:
    workflow = _workflow_text()

    assert workflow.count("uses: docker/build-push-action@v6") == 2
    assert workflow.count("platforms: linux/amd64") == 1
    assert workflow.count("platforms: linux/arm64") == 1
    assert workflow.count("push-by-digest=true,name-canonical=true,push=true") == 2
    assert "          push: true\n" not in workflow
    assert "platforms: linux/amd64,linux/arm64" not in workflow
    assert "group: docker-release" in workflow
    assert "queue: max" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "type=pep440,pattern={{version}}" in workflow
    assert "type=semver,pattern={{version}}" not in workflow


def test_exact_platform_digests_are_pulled_and_runtime_verified() -> None:
    workflow = _workflow_text()

    verify_start = workflow.index("- name: Pull and verify exact platform digests")
    manifest_start = workflow.index("- name: Verify platform index receipts")
    assert verify_start < manifest_start
    assert 'docker pull --platform "$platform" "$image_ref"' in workflow
    assert "docker run --rm" in workflow
    assert '--platform "$platform"' in workflow
    assert "org.opencontainers.image.revision" in workflow
    assert "org.opencontainers.image.version" in workflow
    assert "/app/scripts/verify-teeechr-release-container.py" in workflow


def test_manifest_is_created_only_from_verified_artifacts_without_rebuild() -> None:
    workflow = _workflow_text()
    verify_start = workflow.index("- name: Pull and verify exact platform digests")
    manifest_start = workflow.index("- name: Verify platform index receipts")

    assert "docker/build-push-action" not in workflow[verify_start:]
    assert "docker/bake-action" not in workflow[verify_start:]
    assert "docker build " not in workflow[verify_start:]
    assert "docker buildx build" not in workflow[verify_start:]
    assert "docker buildx bake" not in workflow[verify_start:]
    assert "docker buildx imagetools create" in workflow[manifest_start:]
    assert '"$IMAGE@$AMD64_DIGEST"' in workflow[manifest_start:]
    assert '"$IMAGE@$ARM64_DIGEST"' in workflow[manifest_start:]
    assert '"$IMAGE@$MANIFEST_DIGEST"' in workflow[manifest_start:]
    assert ".github/scripts/verify-docker-release-manifest.py platform" in workflow[manifest_start:]
    assert ".github/scripts/verify-docker-release-manifest.py release" in workflow[manifest_start:]
    assert "python scripts/verify-docker-release-manifest.py" not in workflow
    assert "--format '{{.Manifest.Digest}}'" in workflow[manifest_start:]
    assert "awk '$1 == \"Digest:\"'" not in workflow[manifest_start:]
    assert "tag_digest" in workflow[manifest_start:]


def test_public_tags_are_untouched_until_candidate_manifest_is_verified() -> None:
    workflow = _workflow_text()

    candidate = workflow.index("- name: Assemble and verify candidate manifest")
    verify_candidate = workflow.index("verify-docker-release-manifest.py release")
    promote = workflow.index("- name: Promote verified manifest to release tags")
    assert candidate < verify_candidate < promote
    assert "candidate-$RELEASE_COMMIT" in workflow[candidate:promote]
    candidate_slice = workflow[candidate:promote]
    assert "docker buildx imagetools create" in candidate_slice
    assert '--tag "$candidate_ref"' in candidate_slice


def test_release_source_identity_is_bound_before_building() -> None:
    workflow = _workflow_text()

    source_check = workflow.index('if [[ "$checkout_commit" != "$tag_commit"')
    first_build = workflow.index("uses: docker/build-push-action@v6")
    assert source_check < first_build
    assert "RELEASE_EVENT_SHA: ${{ github.sha }}" in workflow
    assert "from packaging.version import Version" in workflow
    assert "expected = str(Version(" in workflow
    assert 'echo "commit=$tag_commit" >> "$GITHUB_OUTPUT"' in workflow
