from __future__ import annotations

import re

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

_DOMAIN_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    (
        "Professional Orientation and Ethical Practice",
        (
            "ethic",
            "ethical",
            "professional orientation",
            "professional practice",
            "orientation and ethical",
            "legal and ethical",
        ),
    ),
    (
        "Social and Cultural Diversity",
        (
            "social and cultural",
            "multicultural",
            "cultural diversity",
            "diversity and inclusion",
        ),
    ),
    (
        "Human Growth and Development",
        (
            "human growth",
            "growth and development",
            "lifespan",
            "developmental",
        ),
    ),
    (
        "Career Development",
        (
            "career",
            "vocational",
            "workforce development",
        ),
    ),
    (
        "Helping Relationships",
        (
            "helping relationship",
            "counseling relationship",
            "therapeutic relationship",
            "rapport",
        ),
    ),
    (
        "Group Work",
        (
            "group work",
            "group counseling",
            "group process",
            "group dynamics",
        ),
    ),
    (
        "Assessment and Testing",
        (
            "assessment",
            "testing",
            "appraisal",
            "measurement",
        ),
    ),
    (
        "Research and Program Evaluation",
        (
            "research",
            "program evaluation",
            "statistics",
            "data literacy",
        ),
    ),
]


def _simplify(value: str) -> str:
    return _NON_ALNUM_RE.sub(" ", value.lower()).strip()


def _titleize(value: str) -> str:
    words = [part for part in re.split(r"\s+", value.strip()) if part]
    if not words:
        return ""
    small_words = {"and", "of", "the", "to", "for"}
    titled: list[str] = []
    for index, word in enumerate(words):
        if index > 0 and word.lower() in small_words:
            titled.append(word.lower())
        else:
            titled.append(word.capitalize())
    return " ".join(titled)


def normalize_practice_domain(domain: str) -> str:
    cleaned = _titleize(_simplify(str(domain or "")))
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    for canonical, aliases in _DOMAIN_ALIASES:
        if any(alias in lowered for alias in aliases):
            return canonical
    return cleaned


__all__ = ["normalize_practice_domain"]
