"""Private-tester knowledge-base name scoping helpers."""

from __future__ import annotations

import re

_PREFIX_SEPARATOR = "__"


def tester_kb_prefix(tester_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(tester_id or "").strip()).strip("-")
    return f"{safe or 'tester'}{_PREFIX_SEPARATOR}"


def to_internal_kb_name(kb_name: str, tester_id: str) -> str:
    name = str(kb_name or "").strip()
    prefix = tester_kb_prefix(tester_id)
    if not name:
        return name
    if name.startswith(prefix):
        return name
    return f"{prefix}{name}"


def to_public_kb_name(kb_name: str, tester_id: str) -> str:
    name = str(kb_name or "").strip()
    prefix = tester_kb_prefix(tester_id)
    if name.startswith(prefix):
        return name[len(prefix):]
    return name


def is_visible_kb_name(kb_name: str, tester_id: str) -> bool:
    return str(kb_name or "").strip().startswith(tester_kb_prefix(tester_id))


def to_internal_kb_names(kb_names: list[str], tester_id: str) -> list[str]:
    return [to_internal_kb_name(name, tester_id) for name in kb_names if str(name or "").strip()]


def to_public_kb_names(kb_names: list[str], tester_id: str) -> list[str]:
    return [to_public_kb_name(name, tester_id) for name in kb_names if str(name or "").strip()]
