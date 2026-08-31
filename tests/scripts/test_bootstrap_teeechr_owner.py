from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def test_owner_bootstrap_seeds_secure_production_identity(tmp_path: Path) -> None:
    """The documented fresh-volume command must create the production gate inputs."""
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "bootstrap-teeechr-owner.py"),
            "--home",
            str(tmp_path),
        ],
        # Run from outside the checkout to prove the helper makes the copied
        # image root importable when invoked directly by the container entrypoint.
        cwd=tmp_path,
        input="owner\ncorrect horse battery staple\ncorrect horse battery staple\n",
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONWARNINGS": "ignore"},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    users = json.loads(
        (tmp_path / "data" / "system" / "auth" / "users.json").read_text(encoding="utf-8")
    )
    auth = json.loads(
        (tmp_path / "data" / "user" / "settings" / "auth.json").read_text(encoding="utf-8")
    )

    assert users["owner"]["role"] == "admin"
    assert users["owner"]["hash"].startswith("$2")
    assert auth["enabled"] is True
    assert auth["cookie_secure"] is True
    assert auth["password_hash"] == ""
