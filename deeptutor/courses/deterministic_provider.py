"""Explicit local-only Course provider used by integration and browser proof.

This module is unreachable unless the operator deliberately enables the
``TEEECHR_TEST_DETERMINISTIC_PROVIDER`` environment variable.  It never calls
an embedding or model service and is not a production provider option.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.paths import get_personal_path_service
from deeptutor.services.file_io import atomic_write_json

_ENV_NAME = "TEEECHR_TEST_DETERMINISTIC_PROVIDER"
_DELAY_ENV_NAME = "TEEECHR_TEST_DETERMINISTIC_DELAY_MS"


def enabled() -> bool:
    return os.getenv(_ENV_NAME, "").strip().lower() in {"1", "true", "yes", "on"}


def _delay_seconds() -> float:
    try:
        delay_ms = int(os.getenv(_DELAY_ENV_NAME, "0"))
    except ValueError:
        return 0
    return max(0, min(delay_ms, 5_000)) / 1_000


def _embedding(text: str) -> list[int]:
    digest = hashlib.sha256(text.lower().encode("utf-8")).digest()
    return [digest[0], digest[1], digest[2], digest[3]]


def build_index(kb_dir: Path, uploaded_paths: list[str]) -> bool:
    """Write a deterministic, private index for UTF-8-compatible source files."""
    chunks: list[dict[str, Any]] = []
    for raw_path in uploaded_paths:
        path = Path(raw_path)
        try:
            text = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            continue
        if text:
            chunks.append(
                {
                    "path": path.name,
                    "text": text,
                    "embedding": _embedding(text),
                }
            )
    if not chunks:
        return False
    kb_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    kb_dir.chmod(0o700)
    atomic_write_json(kb_dir / "deterministic-index.json", {"chunks": chunks})
    return True


def _authorized_chunks(knowledge_bases: list[Any]) -> list[dict[str, Any]]:
    owner = get_current_user()
    root = get_personal_path_service(owner.id).get_knowledge_bases_root().resolve()
    chunks: list[dict[str, Any]] = []
    for raw_ref in knowledge_bases:
        ref = str(raw_ref or "")
        name = ref.removeprefix("personal:kb:")
        if not name or "/" in name or "\\" in name:
            continue
        index_path = (root / name / "deterministic-index.json").resolve()
        try:
            index_path.relative_to(root)
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for item in payload.get("chunks") or []:
            if isinstance(item, dict) and str(item.get("text") or "").strip():
                chunks.append({**item, "knowledge_base": name})
    return chunks


async def course_chat_events(context: Any) -> AsyncIterator[StreamEvent]:
    """Return a known local response from only server-authorized Course shards."""
    chunks = _authorized_chunks(list(context.knowledge_bases or []))
    if chunks:
        selected = chunks[0]
        text = str(selected["text"])
        answer = f"Deterministic course answer: {text}"
        yield StreamEvent(
            type=StreamEventType.SOURCES,
            source="deterministic_course_provider",
            metadata={
                "sources": [
                    {
                        "type": "knowledge_base",
                        "name": str(selected["knowledge_base"]),
                        "path": str(selected.get("path") or "source"),
                    }
                ]
            },
        )
    else:
        answer = "Deterministic course answer: no authorized Course source was found."
    if delay := _delay_seconds():
        await asyncio.sleep(delay)
    yield StreamEvent(
        type=StreamEventType.CONTENT,
        source="deterministic_course_provider",
        stage="responding",
        content=answer,
        metadata={"call_kind": "llm_final_response"},
    )
    yield StreamEvent(
        type=StreamEventType.DONE,
        source="deterministic_course_provider",
        metadata={"status": "completed", "provider": "deterministic-local"},
    )
