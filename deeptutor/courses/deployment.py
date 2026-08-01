"""Deployment invariants for the local private-Course foundation."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import IO, Mapping


def _configured_worker_count(env: Mapping[str, str] | None = None) -> int:
    values = env or os.environ
    counts: list[int] = []
    for name in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
        raw = str(values.get(name) or "").strip()
        if raw:
            try:
                counts.append(int(raw))
            except ValueError as exc:
                raise RuntimeError(f"{name} must be an integer") from exc
    gunicorn_args = str(values.get("GUNICORN_CMD_ARGS") or "")
    match = re.search(r"(?:^|\s)(?:--workers(?:=|\s+)|-w\s+)(\d+)(?:\s|$)", gunicorn_args)
    if match:
        counts.append(int(match.group(1)))
    return max(counts, default=1)


class SingleProcessCourseLock:
    """Hold an OS-level exclusive lock for one local runtime data tree."""

    def __init__(self, lock_path: Path) -> None:
        self.path = Path(lock_path)
        self._handle: IO[bytes] | None = None

    def acquire(self, env: Mapping[str, str] | None = None) -> None:
        workers = _configured_worker_count(env)
        if workers != 1:
            raise RuntimeError(
                "Private Courses require exactly one application worker; "
                f"configured worker count is {workers}"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        os.chmod(self.path, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                if self.path.stat().st_size == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise RuntimeError(
                "Another DeepTutor application process already owns the local Course data tree"
            ) from exc
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None

    def __enter__(self) -> "SingleProcessCourseLock":
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


__all__ = ["SingleProcessCourseLock", "_configured_worker_count"]
