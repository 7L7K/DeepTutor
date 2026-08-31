"""HTTP fetch + readable-content extraction for the chat ``web_fetch`` tool.

Kept deliberately self-contained: a single async entrypoint
:py:func:`fetch_url_as_markdown` that takes a URL and returns either the
extracted text (with a ``url`` field for citation) or a structured error.
The chat pipeline calls it via the thin ``WebFetchTool`` wrapper in
``deeptutor/tools/builtin/__init__.py``; no internal global state, no
hidden side-effects — easy to test by passing a mock httpx client.

Security stance (kept tight on purpose because the model decides
arguments, not a human):

* Only ``http://`` / ``https://`` schemes accepted.
* IP literals and hostnames resolving to **private / loopback / link-local**
  ranges are rejected up front.  The connector independently resolves and
  pins every address it actually dials through the same policy, preventing a
  DNS rebinding between validation and connection. Redirects are followed
  manually and each ``Location`` target is validated before the next request,
  so a redirect to ``127.0.0.1`` is never issued.
* Response size is hard-capped at ``MAX_RESPONSE_BYTES``; we stop reading
  once the body grows past this even before the server finishes.
* Extracted text is truncated to ``max_chars`` (default 50 000 chars,
  caller-overridable) with a ``…[truncated]`` marker.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import ipaddress
import logging
import re
import socket
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlparse

import aiohttp
from aiohttp.abc import AbstractResolver

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 50_000
MAX_RESPONSE_BYTES = 4 * 1024 * 1024  # 4 MB — safety cap on raw download
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_USER_AGENT = "DeepTutor/1.0 (+https://hkuds.dev/deeptutor)"
ALLOWED_SCHEMES = {"http", "https"}
MAX_REDIRECTS = 5
_NUMERIC_SOCKET_FLAGS = getattr(socket, "AI_NUMERICHOST", 0) | getattr(socket, "AI_NUMERICSERV", 0)


class _BlockedDestinationError(OSError):
    """DNS lookup produced an address that is unsafe for web_fetch."""


Getaddrinfo = Callable[[str, int, socket.AddressFamily], Awaitable[list[tuple[Any, ...]]]]


class _VettedResolver(AbstractResolver):
    """Resolve each connection target and return only policy-approved IPs.

    ``aiohttp`` passes the original hostname to TLS and HTTP while using the
    returned ``host`` values for the TCP connection.  That retains normal SNI,
    certificate verification, virtual-host routing, and redirect behavior while
    ensuring the DNS answer inspected here is the one actually dialed.
    """

    def __init__(self, *, lookup: Getaddrinfo | None = None) -> None:
        self._lookup = lookup or self._getaddrinfo

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_UNSPEC,
    ) -> list[dict[str, Any]]:
        infos = await self._lookup(host, port, family)
        addresses: list[dict[str, Any]] = []
        for resolved_family, socktype, proto, _canonname, sockaddr in infos:
            address = sockaddr[0]
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise _BlockedDestinationError(f"Invalid DNS address for {host}") from exc
            if _is_disallowed_ip(ip):
                raise _BlockedDestinationError(f"Blocked DNS address for {host}")
            addresses.append(
                {
                    "hostname": host,
                    "host": str(ip),
                    "port": port,
                    "family": resolved_family,
                    "proto": proto,
                    "flags": _NUMERIC_SOCKET_FLAGS,
                }
            )
        if not addresses:
            raise _BlockedDestinationError(f"No usable DNS addresses for {host}")
        return addresses

    async def close(self) -> None:
        return None

    @staticmethod
    async def _getaddrinfo(
        host: str,
        port: int,
        family: socket.AddressFamily,
    ) -> list[tuple[Any, ...]]:
        loop = asyncio.get_running_loop()
        return await loop.getaddrinfo(
            host,
            port,
            family=family,
            type=socket.SOCK_STREAM,
        )


class _AiohttpClient:
    """Small adapter preserving the injectable ``client.stream`` test seam."""

    def __init__(self, *, timeout: float, user_agent: str) -> None:
        self._resolver = _VettedResolver()
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._user_agent = user_agent
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> _AiohttpClient:
        connector = aiohttp.TCPConnector(
            resolver=self._resolver,
            use_dns_cache=False,
        )
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=self._timeout,
            headers={"User-Agent": self._user_agent},
            trust_env=False,
        )
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if self._session is not None:
            await self._session.close()
        return False

    def stream(self, method: str, url: str, **kwargs: Any) -> Any:
        if self._session is None:  # pragma: no cover - construction misuse
            raise RuntimeError("HTTP client must be entered before use")
        if "follow_redirects" in kwargs:
            kwargs["allow_redirects"] = kwargs.pop("follow_redirects")
        return self._session.request(method, url, **kwargs)


# Cheap inline HTML → text. Good enough for blog / docs / arxiv abstract
# pages. For JS-heavy SPAs the tool will return the bare HTML scaffold —
# the docstring tells the model it may fail in that case, so it won't
# fabricate around an empty result.
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINE_RE = re.compile(r"\n{3,}")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class FetchOutcome:
    """Result of a single ``web_fetch`` invocation.

    ``ok=True`` paths populate ``markdown`` and ``url`` (the final
    resolved URL after redirects). ``ok=False`` paths populate ``error``
    with a one-line description suitable to surface back to the model.
    """

    ok: bool
    markdown: str = ""
    url: str = ""
    title: str = ""
    truncated: bool = False
    error: str = ""


async def fetch_url_as_markdown(
    url: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    user_agent: str = DEFAULT_USER_AGENT,
    client_factory: Any = None,
    host_validator: Any = None,
) -> FetchOutcome:
    """Fetch ``url`` and extract readable text.

    ``client_factory`` accepts a no-arg callable returning an async context
    manager with a ``stream`` method. ``host_validator``
    is a ``(host: str) -> bool`` that returns ``True`` iff the host
    should be **rejected** as private/loopback — defaults to
    :py:func:`_is_disallowed_host`. Both default to real production
    behaviour; tests inject stubs to bypass DNS or network I/O.
    """
    url_clean = (url or "").strip().strip("`\"'")
    parsed = urlparse(url_clean)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return FetchOutcome(
            ok=False,
            error=f"Unsupported URL scheme: {parsed.scheme or '(empty)'}. Use http:// or https://.",
        )
    host = (parsed.hostname or "").strip()
    if not host:
        return FetchOutcome(ok=False, error="URL is missing a host.")
    validator = host_validator or _is_disallowed_host
    if validator(host):
        return FetchOutcome(
            ok=False,
            error=f"Refusing to fetch private/loopback host: {host}.",
        )

    factory = client_factory or _default_client_factory
    try:
        async with factory(timeout=timeout_s, user_agent=user_agent) as client:
            try:
                current_url = url_clean
                raw = ""
                final_url = current_url
                for redirect_count in range(MAX_REDIRECTS + 1):
                    # Validate every hop before issuing its request. Automatic
                    # redirect handling would send the next GET before this
                    # application had a chance to reject a private target.
                    current = urlparse(current_url)
                    current_host = (current.hostname or "").strip()
                    if current.scheme.lower() not in ALLOWED_SCHEMES or not current_host:
                        return FetchOutcome(ok=False, error="Redirect target URL is invalid.")
                    if validator(current_host):
                        return FetchOutcome(
                            ok=False,
                            error=f"Redirect to private/loopback host blocked: {current_host}.",
                        )

                    async with client.stream(
                        "GET",
                        current_url,
                        headers={"User-Agent": user_agent, "Accept": "text/html,*/*;q=0.5"},
                        follow_redirects=False,
                    ) as response:
                        response_url = str(response.url)
                        status = int(
                            response.status_code
                            if hasattr(response, "status_code")
                            else response.status
                        )
                        location = response.headers.get("location")
                        if 300 <= status < 400 and location:
                            if redirect_count >= MAX_REDIRECTS:
                                return FetchOutcome(
                                    ok=False,
                                    url=response_url,
                                    error=f"Too many redirects (maximum {MAX_REDIRECTS}).",
                                )
                            next_url = urljoin(current_url, location)
                            next_parsed = urlparse(next_url)
                            next_host = (next_parsed.hostname or "").strip()
                            if next_parsed.scheme.lower() not in ALLOWED_SCHEMES or not next_host:
                                return FetchOutcome(
                                    ok=False,
                                    error="Redirect target URL is invalid.",
                                )
                            if validator(next_host):
                                return FetchOutcome(
                                    ok=False,
                                    error=f"Redirect to private/loopback host blocked: {next_host}.",
                                )
                            current_url = next_url
                            continue

                        final_url = response_url
                        final_host = (urlparse(final_url).hostname or "").strip()
                        if final_host and validator(final_host):
                            return FetchOutcome(
                                ok=False,
                                error=f"Redirect to private/loopback host blocked: {final_host}.",
                            )
                        if status >= 400:
                            return FetchOutcome(
                                ok=False,
                                url=final_url,
                                error=f"HTTP {status} from {final_url}.",
                            )
                        raw = await _bounded_read(response, MAX_RESPONSE_BYTES)
                        break
                else:  # pragma: no cover - range always includes a terminal iteration
                    return FetchOutcome(ok=False, error="Too many redirects.")
            except (aiohttp.ClientError, OSError) as exc:
                return FetchOutcome(ok=False, error=f"Network error: {exc}")
    except Exception as exc:  # pragma: no cover — defensive
        return FetchOutcome(ok=False, error=f"Unexpected fetch failure: {exc}")

    title, body = _extract_readable(raw)
    truncated = False
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "\n…[truncated]"
        truncated = True
    return FetchOutcome(ok=True, markdown=body, url=final_url, title=title, truncated=truncated)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _default_client_factory(*, timeout: float, user_agent: str) -> _AiohttpClient:
    """Create a direct-only client whose resolver vets the dialed address.

    ``trust_env=False`` deliberately ignores ambient proxy configuration: a
    proxy would create another resolution and connection hop outside the
    resolver's address policy.
    """
    return _AiohttpClient(timeout=timeout, user_agent=user_agent)


def _is_disallowed_host(host: str) -> bool:
    """Block hosts that resolve to private / loopback / link-local IPs.

    Handles both raw IP literals (``127.0.0.1`` / ``[::1]``) and DNS
    names (resolves them once via ``socket.getaddrinfo`` and checks ALL
    returned addresses). DNS failures are treated as disallowed to fail
    closed when in doubt.
    """
    candidate = host.strip("[]")
    # Direct IP literal check
    try:
        ip = ipaddress.ip_address(candidate)
        return _is_disallowed_ip(ip)
    except ValueError:
        pass
    # Common loopback / metadata hostnames before DNS even tries.
    lower = candidate.lower()
    if lower in {"localhost", "ip6-localhost", "ip6-loopback"}:
        return True
    if lower.endswith(".local"):
        return True
    # Resolve once; treat resolution failure as "disallowed" so a typo
    # plus an unlucky stub doesn't accidentally hit a private network.
    try:
        infos = socket.getaddrinfo(candidate, None)
    except OSError:
        return True
    for info in infos:
        addr = info[4][0]
        try:
            if _is_disallowed_ip(ipaddress.ip_address(addr)):
                return True
        except ValueError:
            continue
    return False


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


async def _bounded_read(response: Any, limit: int) -> str:
    """Stream-read at most ``limit`` bytes from ``response`` then stop.

    Avoids holding hundreds of MB if a server (or an LLM-supplied URL)
    points at a huge resource. Encoding falls back from response.encoding
    → utf-8 with replacement.
    """
    buf = bytearray()
    if hasattr(response, "aiter_bytes"):
        chunks = response.aiter_bytes()
    else:
        chunks = response.content.iter_chunked(64 * 1024)
    async for chunk in chunks:
        buf.extend(chunk)
        if len(buf) >= limit:
            break
    encoding = getattr(response, "encoding", None) or getattr(response, "charset", None) or "utf-8"
    try:
        return buf.decode(encoding, errors="replace")
    except (LookupError, TypeError):
        return buf.decode("utf-8", errors="replace")


def _extract_readable(html_or_text: str) -> tuple[str, str]:
    """Return ``(title, body_text)`` extracted from an HTML string.

    For non-HTML payloads (plain text, JSON dumps) just normalises
    whitespace and returns the input as-is — the model still gets
    something usable.
    """
    title = ""
    if "<" in html_or_text and ">" in html_or_text:
        title_match = _TITLE_RE.search(html_or_text)
        if title_match:
            title = re.sub(r"\s+", " ", title_match.group(1)).strip()
        stripped = _SCRIPT_STYLE_RE.sub(" ", html_or_text)
        stripped = _TAG_RE.sub(" ", stripped)
        # Decode common entities cheaply (full entity table is overkill).
        stripped = (
            stripped.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
        )
        body = stripped
    else:
        body = html_or_text
    body = _WHITESPACE_RE.sub(" ", body)
    body = "\n".join(line.strip() for line in body.splitlines())
    body = _BLANK_LINE_RE.sub("\n\n", body).strip()
    if title:
        body = f"# {title}\n\n{body}"
    return title, body


__all__ = [
    "DEFAULT_MAX_CHARS",
    "MAX_REDIRECTS",
    "FetchOutcome",
    "fetch_url_as_markdown",
]
