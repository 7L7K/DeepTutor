"""
Session Management Module
=========================
"""

from .base_session_manager import BaseSessionManager

try:
    from .turn_runtime import TurnRuntimeManager, get_turn_runtime_manager
except ModuleNotFoundError:
    TurnRuntimeManager = None  # type: ignore[assignment]

    def get_turn_runtime_manager():  # type: ignore[no-untyped-def]
        raise RuntimeError("Turn runtime dependencies are missing from this checkout")

try:
    from .sqlite_store import SQLiteSessionStore, get_sqlite_session_store
except ModuleNotFoundError:
    SQLiteSessionStore = None  # type: ignore[assignment]

    def get_sqlite_session_store():  # type: ignore[no-untyped-def]
        raise RuntimeError("SQLite session store module is missing from this checkout")


__all__ = [
    "BaseSessionManager",
    "SQLiteSessionStore",
    "TurnRuntimeManager",
    "get_sqlite_session_store",
    "get_turn_runtime_manager",
]
