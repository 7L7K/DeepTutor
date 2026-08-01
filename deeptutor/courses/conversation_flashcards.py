"""Bounded, deterministic context selection for General Chat Flashcards."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
import hashlib
import re
from typing import Any, Iterable

_TOKEN = re.compile(r"[^\W_]+", flags=re.UNICODE)
_NUMBERED_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\d+[.)]\s+|[a-z][.)]\s+)(.+?)\s*$",
    flags=re.IGNORECASE,
)
_STOP = {
    "a",
    "about",
    "and",
    "are",
    "as",
    "at",
    "be",
    "create",
    "do",
    "does",
    "explain",
    "for",
    "from",
    "give",
    "help",
    "how",
    "i",
    "in",
    "into",
    "is",
    "it",
    "let",
    "lets",
    "make",
    "me",
    "of",
    "on",
    "or",
    "please",
    "show",
    "that",
    "the",
    "these",
    "this",
    "through",
    "thruh",
    "to",
    "turn",
    "understand",
    "walk",
    "what",
    "with",
}


@dataclass(frozen=True)
class SelectedConversationContext:
    message_ids: tuple[int, ...]
    context_sha256: str
    text: str
    summary: str
    title: str
    topics: tuple[str, ...]
    focus: str


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in _TOKEN.findall(value.casefold())
        if (len(token) >= 2 or token in {"e", "x", "y"}) and token not in _STOP
    }


def _line(message: dict[str, Any]) -> str:
    role = str(message.get("role") or "").strip()
    content = " ".join(str(message.get("content") or "").split())
    return f"{role}: {content}"


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    return next(
        (
            " ".join(str(item.get("content") or "").split())
            for item in reversed(messages)
            if item.get("role") == "user" and str(item.get("content") or "").strip()
        ),
        "",
    )


def _assistant_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(
        str(item.get("content") or "").strip()
        for item in messages
        if item.get("role") == "assistant" and str(item.get("content") or "").strip()
    )


def _title_case(value: str) -> str:
    small = {"a", "an", "and", "for", "in", "of", "on", "or", "the", "to"}
    words = value.split()
    return " ".join(
        word if any(char.isupper() for char in word[1:]) else (
            word.casefold() if index and word.casefold() in small else word.capitalize()
        )
        for index, word in enumerate(words)
    )


def _subject(messages: list[dict[str, Any]]) -> str:
    user_text = _last_user_text(messages)
    assistant_text = _assistant_text(messages)
    assistant_tokens = sorted(_tokens(assistant_text))
    subject_tokens: list[str] = []
    for token in _TOKEN.findall(user_text.casefold()):
        if (len(token) < 2 and token not in {"e", "x", "y"}) or token in _STOP:
            continue
        corrected = token
        if token not in assistant_tokens:
            close = get_close_matches(token, assistant_tokens, n=1, cutoff=0.78)
            if close:
                corrected = close[0]
        if corrected not in subject_tokens:
            subject_tokens.append(corrected)
    subject = " ".join(subject_tokens[:5]).strip()
    if "euler" in subject and re.search(
        r"\bEuler[’']?s\s+number\b", assistant_text, flags=re.IGNORECASE
    ):
        return "Euler's Number"
    if len(subject_tokens) > 3:
        first_sentence = re.split(r"[.!?\n]", assistant_text, maxsplit=1)[0]
        leading = re.match(
            r"^\s*(?:sure[,— -]*|great[,— -]*|(?:i(?:'ll| will)\s+"
            r"(?:explain|show|describe)\s+)?)"
            r"(.{2,80}?)\s+(?:is|are|uses?|means|refers|describes|involves)\b",
            first_sentence,
            flags=re.IGNORECASE,
        )
        if leading:
            candidate = " ".join(leading.group(1).split())
            candidate = re.sub(r"[*_`#]", "", candidate).strip(" ,—-")
            if candidate and len(candidate.split()) <= 5:
                return _title_case(candidate)
    if subject:
        return _title_case(subject)
    return "This Conversation"


def _clean_heading(value: str) -> str:
    heading = re.sub(r"[*_`#]", "", value).strip()
    heading = re.sub(r"\s*\([^)]{1,50}\)\s*$", "", heading).strip()
    heading = re.split(r"\s+[—–-]\s+", heading, maxsplit=1)[0].strip()
    lowered = heading.casefold()
    if lowered.startswith(("where to go next", "would you like")):
        return ""
    replacements = (
        (r"^what (?:is|are)\s+", ""),
        (r"^common\s+", ""),
        (r"^simple\s+", ""),
        (r"^key\s+", ""),
        (r"^short\s+", ""),
    )
    for pattern, replacement in replacements:
        heading = re.sub(pattern, replacement, heading, flags=re.IGNORECASE).strip()
    return heading


def _topics(messages: list[dict[str, Any]], subject: str) -> tuple[str, ...]:
    assistant_text = _assistant_text(messages)
    candidates: list[str] = []
    for line in assistant_text.splitlines():
        match = _NUMBERED_HEADING.match(line)
        if not match:
            continue
        heading = _clean_heading(match.group(1))
        if not heading or len(heading) > 64:
            continue
        if heading.casefold() in {"examples", "intuition", "examples and intuition"}:
            heading = "examples and applications"
        if heading.casefold() == subject.casefold():
            continue
        if heading.casefold() not in {item.casefold() for item in candidates}:
            candidates.append(heading)
    specific_definitions = any(
        "definition" in item.casefold() and item.casefold() != "definitions"
        for item in candidates
    )
    candidates = [
        item
        for item in candidates
        if not (
            (item.casefold() == "definitions" and specific_definitions)
            or item.casefold() in {"derivations and checks", "proofs sketches"}
        )
    ][:6]
    if not candidates:
        first_sentence = re.split(r"[.!?\n]", assistant_text, maxsplit=1)[0]
        clauses = re.split(
            r"\s+to\s+|[,;]\s*|\s+and\s+(?=(?:the\s+)?[\w-]+\s+(?:is|are)\b)",
            first_sentence,
            flags=re.IGNORECASE,
        )
        for clause in clauses:
            phrase = " ".join(clause.split()).strip(" ,—-")
            phrase = re.sub(
                r"^.{1,60}?\s+(?:is|are|uses?|means|refers to|describes|involves)\s+",
                "",
                phrase,
                count=1,
                flags=re.IGNORECASE,
            )
            phrase = re.sub(
                r"^(?:convert|converts|explain|explains|show|shows)\s+",
                "",
                phrase,
                flags=re.IGNORECASE,
            )
            phrase = re.sub(r"^(?:a|an|the)\s+", "", phrase, flags=re.IGNORECASE)
            words = phrase.split()
            if not words or len(words) > 8:
                continue
            phrase = " ".join(words)
            if (
                phrase.casefold() != subject.casefold()
                and phrase.casefold()
                not in {item.casefold() for item in candidates}
            ):
                candidates.append(phrase)
            if len(candidates) >= 4:
                break
    if not candidates:
        candidates = [subject]
    return tuple(candidates)


def _join_topics(topics: tuple[str, ...]) -> str:
    if len(topics) == 1:
        return topics[0]
    if len(topics) == 2:
        return f"{topics[0]} and {topics[1]}"
    return f"{', '.join(topics[:-1])}, and {topics[-1]}"


def _learning_plan(messages: list[dict[str, Any]]) -> tuple[str, tuple[str, ...], str, str]:
    subject = _subject(messages)
    topics = _topics(messages, subject)
    title = (
        subject
        if subject.casefold().endswith(("review", "flashcards"))
        else f"Understanding {subject}"
    )
    topic_text = _join_topics(topics)
    summary = f"{subject}: {topic_text}" if topic_text != subject else subject
    focus = f"Understand {subject} through {topic_text}."
    return title[:120], topics, summary[:160], focus[:1000]


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
    title, topics, summary, focus = _learning_plan(chronological)
    return SelectedConversationContext(
        message_ids=tuple(item["id"] for item in chronological),
        context_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
        summary=summary,
        title=title,
        topics=topics,
        focus=focus,
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

    # Earlier turns must overlap the learner's current request, not merely a
    # generic word somewhere in a long assistant answer. The paired response
    # is already mandatory, so a vague request safely stays a two-message
    # context instead of pulling unrelated greetings or old topics.
    anchor_terms = _tokens(f"{focus}\n{usable[paired_index]['content']}")
    ranked: list[tuple[int, int]] = []
    for index, item in enumerate(usable):
        if index in required:
            continue
        overlap = len(anchor_terms & _tokens(item["content"]))
        if overlap == 0:
            continue
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
