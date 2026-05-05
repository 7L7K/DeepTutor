#!/usr/bin/env python
"""Create or update private tester access codes."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from deeptutor.services.access import hash_access_code
from deeptutor.services.session import get_sqlite_session_store


async def upsert_tester(args: argparse.Namespace) -> None:
    store = get_sqlite_session_store()
    tester = await store.upsert_tester(
        tester_id=args.tester_id,
        display_name=args.display_name,
        code_hash=hash_access_code(args.access_code),
        disabled_at=None,
    )
    print(f"saved tester {tester['id']} ({tester['display_name']})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    upsert = subcommands.add_parser("upsert", help="Create or update a tester code")
    upsert.add_argument("--tester-id", required=True, help="Stable internal tester id")
    upsert.add_argument("--display-name", required=True, help="Display name shown in the app")
    upsert.add_argument("--access-code", required=True, help="Private code given to the tester")
    upsert.set_defaults(func=upsert_tester)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    asyncio.run(args.func(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
