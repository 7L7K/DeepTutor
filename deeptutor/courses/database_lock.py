"""Process-local lock authority for one resolved Course database path."""

from __future__ import annotations

from pathlib import Path
import threading

_registry_lock = threading.Lock()
_database_locks: dict[Path, threading.RLock] = {}


def course_database_lock(db_path: Path | str) -> threading.RLock:
    """Return the one process-local re-entrant lock for ``db_path``.

    SQLite transactions remain the cross-process writer authority. This registry
    prevents separate repository wrappers in this process from using unrelated
    Python locks for the same private database.
    """

    resolved = Path(db_path).resolve()
    with _registry_lock:
        lock = _database_locks.get(resolved)
        if lock is None:
            lock = threading.RLock()
            _database_locks[resolved] = lock
        return lock
