#!/usr/bin/env python
"""Create the first durable TEEECHR administrator before a production start.

Production images intentionally refuse to start with disabled authentication or
an empty identity store. Run this helper once against the mounted runtime data
volume, then start the image normally. Password input is interactive and is
never accepted as a command-line argument or printed to stdout.
"""

from __future__ import annotations

import argparse
from getpass import getpass
import os
from pathlib import Path
import sys

# The published image copies the source tree but does not install the package
# into site-packages.  Make the image root importable when this file is invoked
# directly as ``python /app/scripts/bootstrap-teeechr-owner.py``.
_IMAGE_ROOT = Path(__file__).resolve().parents[1]
if str(_IMAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMAGE_ROOT))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        default=None,
        help="runtime home whose data/ directory is mounted (defaults to DEEPTUTOR_HOME or cwd)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.home:
        os.environ["DEEPTUTOR_HOME"] = str(Path(args.home).expanduser().resolve())

    import bcrypt

    from deeptutor.multi_user.identity import load_users, save_user
    from deeptutor.services.config import get_runtime_settings_service

    runtime = get_runtime_settings_service()
    runtime.ensure_defaults()
    auth = runtime.load_auth(include_process_overrides=False)
    users = load_users()
    if users:
        raise SystemExit("An identity store already exists; refusing to replace its administrator.")
    if str(auth.get("password_hash") or "").strip():
        raise SystemExit("A bootstrap password is already configured; refusing to replace it.")

    username = input("Owner username: ").strip()
    if not username or len(username) > 128 or any(char.isspace() for char in username):
        raise SystemExit("Owner username must be 1-128 non-whitespace characters.")
    password = getpass("Owner password (12+ characters): ")
    if len(password) < 12:
        raise SystemExit("Owner password must contain at least 12 characters.")
    if password != getpass("Repeat owner password: "):
        raise SystemExit("Passwords did not match.")

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    # Write the identity first. If the later settings write fails, production
    # remains fail-closed rather than starting with an enabled empty store.
    save_user(username, hashed, role="admin")
    runtime.save_auth(
        {
            **auth,
            "enabled": True,
            "cookie_secure": True,
            # Keep identity authority in data/system/auth/users.json rather than
            # duplicating a second password-bearing bootstrap record.
            "password_hash": "",
        }
    )
    print("TEEECHR owner bootstrap complete. Start the production image behind HTTPS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
