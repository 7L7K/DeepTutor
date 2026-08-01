from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def test_direct_start_skips_unrelated_heavy_cli_modules() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = """
import json
import sys

sys.argv = ["deeptutor", "start"]
import deeptutor_cli.main as cli

print(json.dumps({
    "fast_start": cli._FAST_START,
    "openai": "openai" in sys.modules,
    "anthropic": "anthropic" in sys.modules,
    "app": "deeptutor.app" in sys.modules,
    "knowledge": "deeptutor.knowledge.manager" in sys.modules,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    proof = json.loads(completed.stdout)
    assert proof == {
        "fast_start": True,
        "openai": False,
        "anthropic": False,
        "app": False,
        "knowledge": False,
    }
