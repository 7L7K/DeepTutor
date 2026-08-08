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
_INGESTION_DELAY_ENV_NAME = "TEEECHR_TEST_DETERMINISTIC_INGESTION_DELAY_MS"


def enabled() -> bool:
    return os.getenv(_ENV_NAME, "").strip().lower() in {"1", "true", "yes", "on"}


def _delay_seconds() -> float:
    try:
        delay_ms = int(os.getenv(_DELAY_ENV_NAME, "0"))
    except ValueError:
        return 0
    return max(0, min(delay_ms, 5_000)) / 1_000


async def delay_ingestion_for_runtime_proof() -> None:
    """Hold only the explicit test provider's source task in processing.

    Browser proof needs a real, live task registration to distinguish a
    processing source from the restart-safe orphan reconciliation path.  The
    hook is unreachable unless the deterministic provider is explicitly
    enabled, and its separate environment variable never affects Chat turns.
    """

    if not enabled():
        return
    try:
        delay_ms = int(os.getenv(_INGESTION_DELAY_ENV_NAME, "0"))
    except ValueError:
        return
    if delay_ms > 0:
        await asyncio.sleep(min(delay_ms, 30_000) / 1_000)


def _embedding(text: str) -> list[int]:
    digest = hashlib.sha256(text.lower().encode("utf-8")).digest()
    return [digest[0], digest[1], digest[2], digest[3]]


def build_index_payload(
    uploaded_paths: list[str], *, source_content_sha256: str | None = None
) -> dict[str, Any] | None:
    """Derive the exact deterministic index without mutating storage."""
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
        return None
    payload: dict[str, Any] = {"chunks": chunks}
    # Chat deliberately remains backward-compatible with its existing index.
    # Course Practice generation independently requires this stamp.
    if source_content_sha256 is not None:
        payload["course_source_content_sha256"] = source_content_sha256
    return payload


def build_index(
    kb_dir: Path, uploaded_paths: list[str], *, source_content_sha256: str | None = None
) -> bool:
    """Write a deterministic, private index for UTF-8-compatible source files."""
    payload = build_index_payload(
        uploaded_paths, source_content_sha256=source_content_sha256
    )
    if payload is None:
        return False
    kb_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    kb_dir.chmod(0o700)
    atomic_write_json(kb_dir / "deterministic-index.json", payload)
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
        if provider_error := str(selected.get("provider_error") or "").strip():
            yield StreamEvent(
                type=StreamEventType.ERROR,
                source="deterministic_course_provider",
                content=provider_error,
                metadata={"turn_terminal": True, "status": "failed"},
            )
            yield StreamEvent(
                type=StreamEventType.DONE,
                source="deterministic_course_provider",
                metadata={"status": "failed", "provider": "deterministic-local"},
            )
            return
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
