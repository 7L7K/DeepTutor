from __future__ import annotations

from ipaddress import ip_address
import os
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

_ORIGIN_SEPARATORS = re.compile(r"[,;\n]+")


def _raw_origin_items(value: Any) -> Iterable[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            items.extend(_raw_origin_items(item))
        return items
    return _ORIGIN_SEPARATORS.split(str(value))


def normalize_origin(value: Any) -> str:
    """Normalize a browser Origin value for CORS allowlists.

    Operators often paste values as ``host:port`` or separate multiple origins
    with semicolons. Browsers always send an Origin as ``scheme://host[:port]``.
    This helper makes common deployment input tolerant while keeping the output
    as exact origins for Starlette's CORSMiddleware.
    """

    origin = str(value or "").strip().rstrip("/")
    if not origin:
        return ""
    if origin in {"*", "null"}:
        return origin
    if "://" not in origin:
        origin = f"http://{origin}"

    try:
        parsed = urlparse(origin)
    except ValueError:
        return origin
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return origin


def normalize_origins(value: Any) -> list[str]:
    origins: list[str] = []
    seen: set[str] = set()
    for raw in _raw_origin_items(value):
        origin = normalize_origin(raw)
        if origin and origin not in seen:
            origins.append(origin)
            seen.add(origin)
    return origins


def is_production_environment() -> bool:
    """Whether this process is running the container's production policy."""
    return os.getenv("TEEECHR_ENVIRONMENT", "").strip().lower() == "production"


def browser_origins(
    system_settings: Mapping[str, Any], *, production: bool | None = None
) -> list[str]:
    """Return browser origins safe for the active deployment policy.

    Local development deliberately supports the two loopback frontend forms.
    The production container has a different trust boundary: only explicitly
    configured HTTPS origins may participate in credentialed browser flows.
    ``*`` and ``null`` are never concrete credentialed principals.
    """
    if production is None:
        production = is_production_environment()

    configured = normalize_origins(
        [system_settings.get("cors_origin"), system_settings.get("cors_origins")]
    )

    if production:
        return [origin for origin in configured if _is_exact_https_origin(origin)]

    origins = [
        f"http://localhost:{system_settings['frontend_port']}",
        f"http://127.0.0.1:{system_settings['frontend_port']}",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    for origin in configured:
        # CORS wildcard semantics are incompatible with credentialed browser
        # sessions, so never add either special Origin value to an allowlist.
        if origin not in {"*", "null"} and origin not in origins:
            origins.append(origin)
    return origins


def _is_exact_https_origin(origin: str) -> bool:
    """Accept only browser-valid HTTPS origins for production allowlists."""
    if origin in {"*", "null"}:
        return False
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    hostname = parsed.hostname
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or hostname.lower() == "localhost"
    ):
        return False
    try:
        return not ip_address(hostname).is_loopback
    except ValueError:
        return True
