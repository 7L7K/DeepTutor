"""Unit tests for the ``web_fetch`` tool's pure helpers."""

from __future__ import annotations

import socket

import pytest

from deeptutor.tools.web_fetch import (
    _NUMERIC_SOCKET_FLAGS,
    DEFAULT_MAX_CHARS,
    FetchOutcome,
    _BlockedDestinationError,
    _default_client_factory,
    _extract_readable,
    _is_disallowed_host,
    _VettedResolver,
    fetch_url_as_markdown,
)

# ---------------------------------------------------------------------------
# Host validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "localhost",
        "10.0.0.1",
        "192.168.1.1",
        "169.254.1.1",
        "100.64.0.1",
        "::1",
        "[::1]",
        "metadata.local",
    ],
)
def test_is_disallowed_host_blocks_private_addresses(host: str) -> None:
    assert _is_disallowed_host(host) is True, f"{host!r} should be disallowed"


def test_is_disallowed_host_allows_public_hostname() -> None:
    # The DNS-dependent positive test is environment-fragile (CI sandboxes
    # often block outbound DNS). The negative coverage above plus the
    # injectable ``host_validator`` (used in fetch tests) makes a fully-
    # offline public-host assertion unnecessary.
    pytest.skip("public DNS check skipped; relies on injectable validator in tests")


@pytest.mark.asyncio
async def test_vetted_resolver_pins_public_dns_answers_without_changing_hostname() -> None:
    async def lookup(host: str, port: int, family: socket.AddressFamily):
        assert (host, port, family) == ("example.com", 443, socket.AF_UNSPEC)
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ]

    addresses = await _VettedResolver(lookup=lookup).resolve("example.com", 443)

    assert addresses == [
        {
            "hostname": "example.com",
            "host": "93.184.216.34",
            "port": 443,
            "family": socket.AF_INET,
            "proto": 6,
            "flags": _NUMERIC_SOCKET_FLAGS,
        }
    ]


@pytest.mark.asyncio
async def test_vetted_resolver_rejects_private_address_at_connection_time() -> None:
    async def rebinding_lookup(host: str, port: int, family: socket.AddressFamily):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
        ]

    resolver = _VettedResolver(lookup=rebinding_lookup)
    with pytest.raises(_BlockedDestinationError, match="Blocked DNS address"):
        await resolver.resolve("previously-public.example", 443)


@pytest.mark.asyncio
async def test_default_client_bypasses_environment_proxies_and_uses_vetted_resolver() -> None:
    client = _default_client_factory(timeout=1.0, user_agent="test-agent")
    async with client:
        assert client._session is not None
        assert client._session._trust_env is False
        assert client._session.connector is not None
        assert client._session.connector._resolver is client._resolver


@pytest.mark.asyncio
async def test_default_client_translates_follow_redirects_for_aiohttp() -> None:
    seen: dict[str, object] = {}

    class RequestContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    client = _default_client_factory(timeout=1.0, user_agent="test-agent")
    async with client:
        assert client._session is not None

        def request(method: str, url: str, **kwargs: object) -> RequestContext:
            seen.update(method=method, url=url, **kwargs)
            return RequestContext()

        client._session.request = request  # type: ignore[method-assign]
        async with client.stream(
            "GET",
            "https://example.com/",
            follow_redirects=False,
        ):
            pass

    assert seen["allow_redirects"] is False
    assert "follow_redirects" not in seen


# ---------------------------------------------------------------------------
# HTML readability extraction
# ---------------------------------------------------------------------------


def test_extract_readable_strips_scripts_and_styles() -> None:
    html = """
    <html><head><title>Hello</title><style>body {color:red;}</style></head>
    <body><p>Visible.</p><script>alert('no');</script></body></html>
    """
    title, body = _extract_readable(html)
    assert title == "Hello"
    assert "Visible." in body
    assert "alert" not in body
    assert "color:red" not in body
    # Title is prepended as h1 markdown
    assert body.startswith("# Hello")


def test_extract_readable_passes_through_plain_text() -> None:
    title, body = _extract_readable("Plain text payload\nwith two lines.")
    assert title == ""
    assert "Plain text payload" in body
    assert "with two lines" in body


# ---------------------------------------------------------------------------
# Top-level fetch — uses injected client_factory so no real network I/O.
# ---------------------------------------------------------------------------


class _StubResponse:
    def __init__(
        self,
        *,
        body: bytes = b"<html><title>T</title><body><p>x</p></body></html>",
        status: int = 200,
        url: str = "https://example.com/p",
        encoding: str = "utf-8",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = body
        self.status_code = status
        self.url = url
        self.encoding = encoding
        self.headers = {
            "content-type": "text/html; charset=utf-8",
            **(headers or {}),
        }

    async def aiter_bytes(self):
        yield self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _StubAsyncClient:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, _method, _url, **_kwargs):
        outer = self

        class _Ctx:
            async def __aenter__(self):
                return outer._response

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return _Ctx()


def _factory_returning(response: _StubResponse):
    def _factory(*, timeout: float, user_agent: str):
        return _StubAsyncClient(response)

    return _factory


class _SequenceAsyncClient(_StubAsyncClient):
    def __init__(self, responses: list[_StubResponse], requested: list[str]) -> None:
        self._responses = iter(responses)
        self.requested = requested

    def stream(self, _method, url, **_kwargs):
        outer = self
        outer.requested.append(url)

        class _Ctx:
            async def __aenter__(self):
                return next(outer._responses)

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return _Ctx()


@pytest.mark.asyncio
async def test_fetch_rejects_unsupported_scheme() -> None:
    outcome = await fetch_url_as_markdown("ftp://example.com/x")
    assert outcome.ok is False
    assert "scheme" in outcome.error.lower()


@pytest.mark.asyncio
async def test_fetch_rejects_private_host() -> None:
    outcome = await fetch_url_as_markdown("http://127.0.0.1/x")
    assert outcome.ok is False
    assert "private" in outcome.error.lower() or "loopback" in outcome.error.lower()


# Bypass DNS in every stubbed-network test — the validator is treated as
# trusted here because ``client_factory`` already pins the response.
_ALLOW_ALL = lambda host: False  # noqa: E731 — single-use stub


@pytest.mark.asyncio
async def test_fetch_extracts_html_via_stubbed_client() -> None:
    outcome = await fetch_url_as_markdown(
        "https://example.com/p",
        client_factory=_factory_returning(_StubResponse()),
        host_validator=_ALLOW_ALL,
    )
    assert outcome.ok is True
    assert outcome.title == "T"
    assert "x" in outcome.markdown


@pytest.mark.asyncio
async def test_fetch_truncates_at_max_chars() -> None:
    big_body = b"<html><body>" + (b"a" * 5000) + b"</body></html>"
    outcome = await fetch_url_as_markdown(
        "https://example.com/big",
        max_chars=200,
        client_factory=_factory_returning(_StubResponse(body=big_body)),
        host_validator=_ALLOW_ALL,
    )
    assert outcome.ok is True
    assert outcome.truncated is True
    assert outcome.markdown.endswith("…[truncated]")
    assert len(outcome.markdown) <= 220  # cap + marker headroom


@pytest.mark.asyncio
async def test_fetch_propagates_http_error_as_outcome_not_exception() -> None:
    outcome = await fetch_url_as_markdown(
        "https://example.com/missing",
        client_factory=_factory_returning(_StubResponse(status=404, body=b"<p>missing</p>")),
        host_validator=_ALLOW_ALL,
    )
    assert outcome.ok is False
    assert "404" in outcome.error


@pytest.mark.asyncio
async def test_fetch_validates_redirect_target_before_requesting_next_hop() -> None:
    requested: list[str] = []
    client = _SequenceAsyncClient(
        [
            _StubResponse(
                status=302,
                url="https://example.com/start",
                headers={"location": "http://127.0.0.1/internal"},
            ),
            _StubResponse(url="http://127.0.0.1/internal"),
        ],
        requested,
    )

    def factory(*, timeout: float, user_agent: str):
        return client

    outcome = await fetch_url_as_markdown(
        "https://example.com/start",
        client_factory=factory,
        host_validator=_is_disallowed_host,
    )

    assert outcome.ok is False
    assert "private" in outcome.error.lower() or "loopback" in outcome.error.lower()
    assert requested == ["https://example.com/start"]
