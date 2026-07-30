"""Bounded, deterministic context selection for General Chat Flashcards."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Iterable

_TOKEN = re.compile(r"[^\W_]+", flags=re.UNICODE)
_STOP = {
    "a",
    "about",
    "and",
    "are",
    "as",
    "at",
    "be",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "make",
    "of",
    "on",
    "or",
    "that",
    "the",
    "these",
    "this",
    "to",
    "what",
    "with",
}


@dataclass(frozen=True)
class SelectedConversationContext:
    message_ids: tuple[int, ...]
    context_sha256: str
    text: str
    summary: str


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in _TOKEN.findall(value.casefold())
        if len(token) >= 2 and token not in _STOP
    }


def _line(message: dict[str, Any]) -> str:
    role = str(message.get("role") or "").strip()
    content = " ".join(str(message.get("content") or "").split())
    return f"{role}: {content}"


def _summary(messages: list[dict[str, Any]]) -> str:
    user_text = next(
        (
            " ".join(str(item.get("content") or "").split())
            for item in reversed(messages)
            if item.get("role") == "user" and str(item.get("content") or "").strip()
        ),
        "",
    )
    if not user_text:
        user_text = "the recent conversation"
    return user_text[:157] + ("..." if len(user_text) > 160 else "")


def _usable_messages(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": int(item.get("id") or 0),
            "role": str(item.get("role") or ""),
            "content": str(item.get("content") or "").strip(),
        }
        for item in messages
        if str(item.get("role") or "") in {"user", "assistant"}
        and str(item.get("content") or "").strip()
        and int(item.get("id") or 0) > 0
    ]


def _selected_context(
    chronological: list[dict[str, Any]],
    *,
    assistant_message_id: int,
    max_chars: int,
) -> SelectedConversationContext:
    if (
        len(chronological) < 2
        or chronological[-1]["id"] != assistant_message_id
        or chronological[-1]["role"] != "assistant"
        or not any(item["role"] == "user" for item in chronological[:-1])
    ):
        raise ValueError("conversation requires a user and assistant exchange")
    text = "\n".join(_line(item) for item in chronological)
    if not text or len(text) > max_chars:
        raise ValueError("conversation context is too large")
    return SelectedConversationContext(
        message_ids=tuple(item["id"] for item in chronological),
        context_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
        summary=_summary(chronological),
    )


def select_conversation_context(
    messages: Iterable[dict[str, Any]],
    *,
    assistant_message_id: int,
    focus: str = "",
    max_messages: int = 12,
    max_chars: int = 12_000,
) -> SelectedConversationContext:
    """Select a stable relevant subset ending at one assistant response.

    The active branch is supplied by the personal session store. The selected
    response and its paired user message are mandatory. Additional messages
    are ranked by lexical overlap with the response/focus, with a small recency
    bonus, then restored to chronological order.
    """

    if not 2 <= max_messages <= 32 or not 1_000 <= max_chars <= 48_000:
        raise ValueError("conversation context limits are invalid")
    usable = _usable_messages(messages)
    leaf_index = next(
        (
            index
            for index, item in enumerate(usable)
            if item["id"] == assistant_message_id and item["role"] == "assistant"
        ),
        None,
    )
    if leaf_index is None:
        raise ValueError("conversation assistant message is unavailable")
    usable = usable[: leaf_index + 1]
    leaf = usable[-1]
    paired_index = next(
        (
            index
            for index in range(len(usable) - 2, -1, -1)
            if usable[index]["role"] == "user"
        ),
        None,
    )
    if paired_index is None:
        raise ValueError("conversation requires a user and assistant exchange")
    required = {len(usable) - 1}
    if paired_index is not None:
        required.add(paired_index)

    anchor_terms = _tokens(f"{focus}\n{leaf['content']}")
    ranked: list[tuple[int, int]] = []
    for index, item in enumerate(usable):
        if index in required:
            continue
        overlap = len(anchor_terms & _tokens(item["content"]))
        recency = max(0, index - max(0, len(usable) - 6))
        ranked.append((overlap * 100 + recency, index))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)

    selected = set(required)
    for _score, index in ranked:
        if len(selected) >= max_messages:
            break
        selected.add(index)

    chronological = [usable[index] for index in sorted(selected)]
    while sum(len(_line(item)) + 1 for item in chronological) > max_chars:
        removable = next(
            (
                index
                for index, item in enumerate(chronological)
                if item["id"] not in {usable[item_index]["id"] for item_index in required}
            ),
            None,
        )
        if removable is None:
            break
        chronological.pop(removable)

    return _selected_context(
        chronological,
        assistant_message_id=assistant_message_id,
        max_chars=max_chars,
    )


def resolve_frozen_conversation_context(
    messages: Iterable[dict[str, Any]],
    *,
    assistant_message_id: int,
    selected_message_ids: Iterable[int],
    max_chars: int = 12_000,
) -> SelectedConversationContext:
    """Rebuild exactly the reviewed message set without relevance re-ranking.

    Selection happens before the learner edits the generation focus. Provider
    admission must verify that frozen selection, not silently choose a
    different subset because the focus changed.
    """

    ids = tuple(int(value) for value in selected_message_ids)
    if not 2 <= len(ids) <= 32 or len(set(ids)) != len(ids):
        raise ValueError("frozen conversation message IDs are invalid")
    usable = _usable_messages(messages)
    by_id = {item["id"]: item for item in usable}
    try:
        chronological = [by_id[message_id] for message_id in ids]
    except KeyError as exc:
        raise ValueError("frozen conversation message is unavailable") from exc
    positions = {item["id"]: index for index, item in enumerate(usable)}
    if [positions[message_id] for message_id in ids] != sorted(
        positions[message_id] for message_id in ids
    ):
        raise ValueError("frozen conversation message order is invalid")
    return _selected_context(
        chronological,
        assistant_message_id=assistant_message_id,
        max_chars=max_chars,
    )
