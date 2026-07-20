from __future__ import annotations


def append_language_directive(prompt: str, language: str = "en") -> str:
    """Append a compact response-language directive to a prompt."""
    base = str(prompt or "").strip()
    lang = (language or "en").lower()
    directive = "Respond in Chinese." if lang.startswith("zh") else "Respond in English."
    return f"{base}\n\n{directive}".strip()
