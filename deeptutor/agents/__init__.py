"""Agents package exports.

Exports are resolved lazily so importing a focused subpackage such as
``deeptutor.agents.question`` does not pull in the full chat stack.
"""

from importlib import import_module
from typing import Any

__all__ = ["BaseAgent", "ChatAgent", "SessionManager"]


def __getattr__(name: str) -> Any:
    if name == "BaseAgent":
        module = import_module("deeptutor.agents.base_agent")
        return getattr(module, name)
    if name in {"ChatAgent", "SessionManager"}:
        module = import_module("deeptutor.agents.chat")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
