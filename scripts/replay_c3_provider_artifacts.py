#!/usr/bin/env python3
"""Write the deterministic C3 archived-provider failure ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from deeptutor.courses.content_quality_replay import replay_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    ledger = replay_manifest(args.manifest.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "cases": len(ledger["cases"]),
                "output": str(args.output),
                "provider_requests_made": ledger["provider_requests_made"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
