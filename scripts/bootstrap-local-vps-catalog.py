#!/usr/bin/env python3
"""Seed the local mirror with a credential-free provider profile.

The local mirror must be able to exercise real chat after a fresh checkout,
but credentials remain process environment only. This script intentionally
does nothing when an operator has already configured an LLM profile.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

PROFILE_ID = "local-openai-env"
MODEL_ID = "local-openai-gpt-5.6-luna"
DEFAULT_MODEL = "gpt-5.6-luna"


def load_catalog(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def bootstrap(path: Path) -> bool:
    catalog = load_catalog(path)
    services = catalog.setdefault("services", {})
    llm = services.setdefault("llm", {})
    profiles = llm.setdefault("profiles", [])
    if profiles:
        return False

    text_generation = catalog.setdefault("text_generation", {})
    model = str(text_generation.get("default_model") or DEFAULT_MODEL)
    profile = {
        "id": PROFILE_ID,
        "name": "Local OpenAI (env)",
        "binding": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "api_version": "",
        "extra_headers": {},
        "models": [
            {
                "id": MODEL_ID,
                "name": model,
                "model": model,
                "reasoning_effort": "low",
            }
        ],
    }
    llm["active_profile_id"] = PROFILE_ID
    llm["active_model_id"] = MODEL_ID
    llm["profiles"] = [profile]

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(catalog, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} CATALOG_PATH", file=sys.stderr)
        return 2
    path = Path(sys.argv[1]).resolve()
    print("bootstrapped" if bootstrap(path) else "unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
