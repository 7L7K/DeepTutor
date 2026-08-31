"""Release container provenance checks that fail before runtime work begins."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "verify-teeechr-release-container.py"
    )
    spec = importlib.util.spec_from_file_location("verify_teeechr_release_container", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(spec.name, None)


def test_release_container_requires_full_expected_source_revision(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("EXPECTED_RELEASE_VERSION", "1.2.3")
    monkeypatch.setenv("EXPECTED_RELEASE_REVISION", "short-sha")

    with pytest.raises(RuntimeError, match="full Git SHA"):
        module.main()


def test_release_container_rejects_runtime_source_revision_mismatch(monkeypatch) -> None:
    module = _load_module()
    expected = "a" * 40
    monkeypatch.setenv("EXPECTED_RELEASE_VERSION", "1.2.3")
    monkeypatch.setenv("EXPECTED_RELEASE_REVISION", expected)
    monkeypatch.setenv("TEEECHR_ENVIRONMENT", "production")
    monkeypatch.setenv("TEEECHR_APP_VERSION", "1.2.3")
    monkeypatch.setenv("TEEECHR_SOURCE_REVISION", "b" * 40)

    with pytest.raises(RuntimeError, match="revision does not match"):
        module.main()


def test_release_container_accepts_legacy_controller_sha_as_expected_revision(monkeypatch) -> None:
    module = _load_module()
    expected = "a" * 40
    monkeypatch.setenv("EXPECTED_RELEASE_VERSION", expected)
    monkeypatch.delenv("EXPECTED_RELEASE_REVISION", raising=False)
    monkeypatch.setenv("TEEECHR_ENVIRONMENT", "production")
    monkeypatch.setenv("TEEECHR_APP_VERSION", expected)
    monkeypatch.setenv("TEEECHR_SOURCE_REVISION", expected)

    monkeypatch.setattr(module, "discover_migrations", lambda: [])
    with pytest.raises(RuntimeError, match="latest Course migration"):
        module.main()
