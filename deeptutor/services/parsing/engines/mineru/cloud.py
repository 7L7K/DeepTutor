"""MinerU cloud (mineru.net) v4 API backend.

Implements the token-required *Precision API* flow for a single local PDF:

1. ``POST /api/v4/file-urls/batch`` → ``{batch_id, file_urls: [signed_url]}``
2. ``PUT`` the raw PDF bytes to ``signed_url`` (no auth, no Content-Type)
3. Poll ``GET /api/v4/extract-results/batch/{batch_id}`` until the file's
   ``state`` reaches ``done`` / ``failed``
4. Download the ``full_zip_url`` archive and extract it into a working dir
   whose layout matches the local CLI output (``*.md`` +
   ``*_content_list.json`` + ``images/``), so the downstream question
   extractor is backend-agnostic.

The module is synchronous on purpose: it runs inside the worker thread that
:func:`deeptutor.agents.question.mimic_source.parse_exam_paper_to_templates`
spawns via ``asyncio.to_thread``, so a blocking ``httpx.Client`` is the
simplest correct choice (no nested event loop).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import io
import ipaddress
import logging
from pathlib import Path
import socket
import time
from urllib.parse import urlsplit
import zipfile

import httpcore
import httpx

from .config import MinerUConfig, MinerUError

logger = logging.getLogger(__name__)

# Async polling defaults. MinerU recommends a 3–5s interval; parsing a typical
# exam paper completes well under a few minutes.
DEFAULT_POLL_INTERVAL_SECONDS = 4.0
DEFAULT_TIMEOUT_SECONDS = 300.0
_SUBMIT_TIMEOUT_SECONDS = 60.0
_UPLOAD_TIMEOUT_SECONDS = 300.0
_DOWNLOAD_TIMEOUT_SECONDS = 300.0

_TERMINAL_OK = "done"
_TERMINAL_FAIL = "failed"

# Bounds for the downloaded/extracted archive (defends a hostile/buggy CDN
# response). The download ceiling is checked before and while buffering; the
# extraction path applies the same aggregate budget while streaming members.
_MAX_TOTAL_BYTES = 128 * 1024 * 1024
_MAX_DOWNLOAD_BYTES = _MAX_TOTAL_BYTES
_DOWNLOAD_CHUNK_BYTES = 64 * 1024
_MAX_ENTRY_BYTES = 64 * 1024 * 1024
_MAX_ENTRIES = 2_000
_MAX_COMPRESSION_RATIO = 1_000


@dataclass(frozen=True)
class _PinnedAddress:
    """One policy-approved numeric address for a MinerU hostname."""

    family: socket.AddressFamily
    host: str


class _PinnedURL(str):
    """A URL paired with the addresses accepted for its next TCP connection."""

    host: str
    port: int
    addresses: tuple[_PinnedAddress, ...]

    def __new__(
        cls,
        value: str,
        *,
        host: str,
        port: int,
        addresses: tuple[_PinnedAddress, ...],
    ) -> _PinnedURL:
        instance = super().__new__(cls, value)
        instance.host = host
        instance.port = port
        instance.addresses = addresses
        return instance


class _PinnedNetworkBackend:
    """Dial vetted numeric addresses while HTTP/TLS retain the original host.

    httpcore asks this backend for a TCP connection immediately before a
    request.  By replacing only that dial with the address obtained during URL
    validation, DNS cannot change the destination after policy checks.  The
    request URL itself is intentionally untouched, so httpcore still emits the
    original Host header and passes the original hostname to TLS for SNI and
    certificate verification.
    """

    def __init__(self, destination: _PinnedURL) -> None:
        self._destination = destination
        self._backend = httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object = None,
    ) -> object:
        if (host.rstrip(".").lower(), port) != (self._destination.host, self._destination.port):
            raise httpcore.ConnectError("MinerU request attempted an unvalidated destination.")

        last_error: Exception | None = None
        for address in self._destination.addresses:
            try:
                # ``host`` is now a numeric literal; SyncBackend's
                # create_connection cannot perform a hostname lookup for it.
                return self._backend.connect_tcp(
                    host=address.host,
                    port=port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise httpcore.ConnectError("MinerU URL had no approved connection address.")

    def connect_unix_socket(self, *args: object, **kwargs: object) -> object:
        return self._backend.connect_unix_socket(*args, **kwargs)

    def sleep(self, seconds: float) -> None:
        self._backend.sleep(seconds)


class _PinnedHTTPTransport(httpx.HTTPTransport):
    """HTTPX transport with a connection pool bound to one vetted URL."""

    def __init__(self, destination: _PinnedURL) -> None:
        # Retain HTTPX's certificate-verifying context with environment trust
        # disabled. Replace only the direct connection pool so no proxy can
        # bypass the pin and the dial is delegated to _PinnedNetworkBackend.
        super().__init__(trust_env=False, retries=0)
        self._pool.close()
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=False),
            network_backend=_PinnedNetworkBackend(destination),
            retries=0,
        )


def _assert_public_https_url(value: str, *, purpose: str) -> _PinnedURL:
    """Return a safe external HTTPS URL or raise a user-safe error.

    MinerU returns the signed upload and result URLs at runtime.  Treating
    those values as data rather than executable destinations keeps a malformed
    provider response (or an unsafe administrator override) from turning the
    parsing worker into a request primitive for local services or cloud
    metadata.  DNS is checked immediately before each request; redirects are
    deliberately disabled on the transfer calls below so the validated URL is
    also the one requested.
    """
    candidate = str(value or "").strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise MinerUError(f"MinerU returned an invalid {purpose} URL.") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port == 0
    ):
        raise MinerUError(f"MinerU returned an unsafe {purpose} URL.")

    host = parsed.hostname.rstrip(".")
    try:
        connection_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise MinerUError(f"MinerU returned an invalid {purpose} URL.") from exc
    if connection_host in {
        "localhost",
        "ip6-localhost",
        "ip6-loopback",
    } or connection_host.endswith(".local"):
        raise MinerUError(f"MinerU returned an unsafe {purpose} URL.")
    connection_port = port or 443
    try:
        addresses = socket.getaddrinfo(
            connection_host, connection_port, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except OSError as exc:
        raise MinerUError(f"MinerU {purpose} URL could not be resolved safely.") from exc
    if not addresses:
        raise MinerUError(f"MinerU {purpose} URL could not be resolved safely.")
    pinned_addresses: list[_PinnedAddress] = []
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address[4][0])
        except (IndexError, ValueError):
            raise MinerUError(f"MinerU {purpose} URL resolved to an invalid address.") from None
        if not ip.is_global:
            raise MinerUError(f"MinerU returned an unsafe {purpose} URL.")
        pinned_addresses.append(_PinnedAddress(family=address[0], host=str(ip)))
    return _PinnedURL(
        candidate,
        host=connection_host,
        port=connection_port,
        addresses=tuple(pinned_addresses),
    )


def _transport_for(destination: str) -> httpx.BaseTransport | None:
    """Build a pinned transport for validated production URLs.

    Tests may replace ``_assert_public_https_url`` with a plain string to keep
    their fake HTTP clients isolated.  Real validation always returns
    ``_PinnedURL`` and therefore always uses the pinning transport.
    """
    if isinstance(destination, _PinnedURL):
        return _PinnedHTTPTransport(destination)
    return None


def _client_for(destination: str, *, headers: dict[str, str] | None = None) -> httpx.Client:
    return httpx.Client(
        base_url=str(destination),
        headers=headers,
        follow_redirects=False,
        trust_env=False,
        transport=_transport_for(destination),
    )


def _file_chunks(path: Path):
    """Yield a PDF incrementally so uploads do not duplicate it in memory."""
    with path.open("rb") as source:
        while chunk := source.read(_DOWNLOAD_CHUNK_BYTES):
            yield chunk


def parse_cloud(
    pdf_path: Path,
    output_base: Path,
    config: MinerUConfig,
    *,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Parse ``pdf_path`` via the MinerU cloud API; return the working dir.

    The working dir sits under ``output_base`` (named after the PDF stem) and
    holds the unzipped MinerU artifacts. ``on_progress`` (if given) receives a
    short status line whenever the polled task state / page count changes.
    Raises :class:`MinerUError` on any misconfiguration, API error, timeout,
    or extraction failure.
    """
    if not config.api_token:
        raise MinerUError(
            "MinerU cloud mode is selected but no API token is configured. "
            "Add a token in Settings → MinerU, or switch to local mode."
        )
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise MinerUError(f"PDF file not found: {pdf_path}")

    base_url = _assert_public_https_url(config.api_base_url.rstrip("/"), purpose="API")
    headers = {
        "Authorization": f"Bearer {config.api_token}",
        "Accept": "application/json",
    }

    def report(message: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(message)
        except Exception:
            logger.debug("on_progress callback failed", exc_info=True)

    with _client_for(base_url, headers=headers) as client:
        report(f"MinerU cloud: requesting upload slot for {pdf_path.name}")
        batch_id, upload_url = _request_upload(client, pdf_path, config)
        size_mb = pdf_path.stat().st_size / (1024 * 1024)
        report(f"MinerU cloud: uploading {pdf_path.name} ({size_mb:.1f} MB)")
        _upload_file(pdf_path, upload_url)
        zip_url = _poll_for_zip(
            client,
            batch_id,
            pdf_path.name,
            poll_interval=poll_interval,
            timeout=timeout,
            on_progress=on_progress,
        )
        report("MinerU cloud: downloading parsed result archive")
        archive_bytes = _download(zip_url)

    report("MinerU cloud: extracting archive")
    working_dir = output_base / pdf_path.stem
    _reset_dir(working_dir)
    _extract_archive(archive_bytes, working_dir)
    logger.info("MinerU cloud parse complete: %s → %s", pdf_path.name, working_dir)
    return working_dir


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def _request_upload(client: httpx.Client, pdf_path: Path, config: MinerUConfig) -> tuple[str, str]:
    """POST file-urls/batch → ``(batch_id, signed_upload_url)``."""
    file_entry: dict[str, object] = {"name": pdf_path.name, "is_ocr": config.is_ocr}
    body: dict[str, object] = {
        "files": [file_entry],
        "model_version": config.model_version,
        "enable_formula": config.enable_formula,
        "enable_table": config.enable_table,
    }
    if config.api_language:
        body["language"] = config.api_language

    payload = _post_json(client, "/api/v4/file-urls/batch", body)
    data = payload.get("data") or {}
    batch_id = str(data.get("batch_id") or "").strip()
    file_urls = data.get("file_urls") or []
    if not batch_id or not isinstance(file_urls, list) or not file_urls:
        raise MinerUError("MinerU API did not return an upload URL (missing batch_id/file_urls).")
    return batch_id, str(file_urls[0])


def _upload_file(pdf_path: Path, upload_url: str) -> None:
    """PUT the PDF bytes to the signed URL.

    The signed URL carries its own auth; per MinerU's docs we must NOT send an
    ``Authorization`` or ``Content-Type`` header (a stray Content-Type breaks
    the OSS signature).
    """
    safe_url = _assert_public_https_url(upload_url, purpose="upload")
    try:
        transport = _transport_for(safe_url)
        if transport is None:
            # Kept for the injectable test seam; real validated URLs always
            # take the pinned-client branch below.
            with httpx.stream(
                "PUT",
                safe_url,
                content=_file_chunks(pdf_path),
                timeout=_UPLOAD_TIMEOUT_SECONDS,
                follow_redirects=False,
                trust_env=False,
            ) as response:
                response.raise_for_status()
        else:
            with httpx.Client(
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client:
                with client.stream(
                    "PUT",
                    str(safe_url),
                    content=_file_chunks(pdf_path),
                    timeout=_UPLOAD_TIMEOUT_SECONDS,
                ) as response:
                    response.raise_for_status()
    except httpx.HTTPError as exc:
        raise MinerUError(f"Failed to upload PDF to MinerU: {exc}") from exc


def _poll_for_zip(
    client: httpx.Client,
    batch_id: str,
    file_name: str,
    *,
    poll_interval: float,
    timeout: float,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    """Poll the batch results until our file is ``done``; return full_zip_url."""
    deadline = time.monotonic() + timeout
    last_state = ""
    last_report = ""
    while True:
        payload = _get_json(client, f"/api/v4/extract-results/batch/{batch_id}")
        results = (payload.get("data") or {}).get("extract_result") or []
        entry = _match_entry(results, file_name)
        if entry is not None:
            state = str(entry.get("state") or "").strip().lower()
            last_state = state or last_state
            if on_progress is not None:
                progress = entry.get("extract_progress") or {}
                total_pages = progress.get("total_pages")
                report = f"MinerU cloud: {state or 'queued'}"
                if total_pages:
                    report += f" ({progress.get('extracted_pages') or 0}/{total_pages} pages)"
                if report != last_report:
                    last_report = report
                    try:
                        on_progress(report)
                    except Exception:
                        on_progress = None
            if state == _TERMINAL_OK:
                zip_url = str(entry.get("full_zip_url") or "").strip()
                if not zip_url:
                    raise MinerUError("MinerU reported done but returned no full_zip_url.")
                return zip_url
            if state == _TERMINAL_FAIL:
                err = str(entry.get("err_msg") or "unknown error")
                raise MinerUError(f"MinerU failed to parse the document: {err}")
        if time.monotonic() >= deadline:
            raise MinerUError(
                f"MinerU parsing timed out after {int(timeout)}s "
                f"(last state: {last_state or 'unknown'})."
            )
        time.sleep(poll_interval)


def verify_credentials(config: MinerUConfig) -> None:
    """Best-effort connectivity / token check for the Settings → MinerU "Test"
    button. Requests an upload slot (which does not consume parsing quota and
    is never followed by an upload, so it simply expires) and validates the
    business code. Raises :class:`MinerUError` with a user-facing message on
    any failure."""
    if not config.api_token:
        raise MinerUError("No API token configured.")
    base_url = _assert_public_https_url(config.api_base_url.rstrip("/"), purpose="API")
    headers = {
        "Authorization": f"Bearer {config.api_token}",
        "Accept": "application/json",
    }
    body: dict[str, object] = {
        "files": [{"name": "connectivity-check.pdf", "is_ocr": False}],
        "model_version": config.model_version,
        "enable_formula": config.enable_formula,
        "enable_table": config.enable_table,
    }
    if config.api_language:
        body["language"] = config.api_language
    with _client_for(base_url, headers=headers) as client:
        _post_json(client, "/api/v4/file-urls/batch", body)


def _download(zip_url: str) -> bytes:
    safe_url = _assert_public_https_url(zip_url, purpose="result archive")
    try:
        # ``httpx.get`` buffers the complete body before returning. Keep the
        # archive ceiling effective for chunked or dishonest CDN responses by
        # streaming into a bounded buffer instead.
        transport = _transport_for(safe_url)
        if transport is None:
            # See _upload_file: fake tests intentionally retain this module
            # level HTTPX seam, while production uses the pinned transport.
            with httpx.stream(
                "GET",
                safe_url,
                timeout=_DOWNLOAD_TIMEOUT_SECONDS,
                follow_redirects=False,
                trust_env=False,
            ) as response:
                return _bounded_download_bytes(response)
        with httpx.Client(
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            with client.stream(
                "GET",
                str(safe_url),
                timeout=_DOWNLOAD_TIMEOUT_SECONDS,
            ) as response:
                return _bounded_download_bytes(response)
    except MinerUError:
        raise
    except httpx.HTTPError as exc:
        raise MinerUError(f"Failed to download MinerU result archive: {exc}") from exc


def _bounded_download_bytes(response: httpx.Response) -> bytes:
    """Read one response without permitting an archive beyond the ceiling."""
    response.raise_for_status()
    headers = getattr(response, "headers", {}) or {}
    raw_length = headers.get("content-length")
    try:
        if raw_length is not None and int(raw_length) > _MAX_DOWNLOAD_BYTES:
            raise MinerUError("MinerU result archive exceeds the download size limit.")
    except (TypeError, ValueError):
        raise MinerUError("MinerU result archive returned an invalid content length.") from None

    content = bytearray()
    for chunk in response.iter_bytes(chunk_size=_DOWNLOAD_CHUNK_BYTES):
        if len(content) + len(chunk) > _MAX_DOWNLOAD_BYTES:
            raise MinerUError("MinerU result archive exceeds the download size limit.")
        content.extend(chunk)
    return bytes(content)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _match_entry(results: list, file_name: str) -> dict | None:
    """Pick our file's result row. Single-file batch → first row is ours, but
    match on ``file_name`` when present to be safe."""
    rows = [r for r in results if isinstance(r, dict)]
    if not rows:
        return None
    for row in rows:
        if str(row.get("file_name") or "") == file_name:
            return row
    return rows[0]


def _post_json(client: httpx.Client, path: str, body: dict) -> dict:
    try:
        response = client.post(path, json=body, timeout=_SUBMIT_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise MinerUError(_http_error_message(exc)) from exc
    except httpx.HTTPError as exc:
        raise MinerUError(f"MinerU API request failed: {exc}") from exc
    _check_code(payload)
    return payload


def _get_json(client: httpx.Client, path: str) -> dict:
    try:
        response = client.get(path, timeout=_SUBMIT_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise MinerUError(_http_error_message(exc)) from exc
    except httpx.HTTPError as exc:
        raise MinerUError(f"MinerU API request failed: {exc}") from exc
    _check_code(payload)
    return payload


def _check_code(payload: dict) -> None:
    """MinerU wraps errors in ``{"code": <non-zero>, "msg": ...}`` even on
    HTTP 200, so the business code must be inspected explicitly."""
    if not isinstance(payload, dict):
        raise MinerUError("MinerU API returned an unexpected (non-JSON) response.")
    code = payload.get("code")
    if code not in (0, None):
        msg = str(payload.get("msg") or "unknown error")
        raise MinerUError(f"MinerU API error (code {code}): {msg}")


def _http_error_message(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    if status in (401, 403):
        return "MinerU API rejected the token (401/403). Check the API token in Settings → MinerU."
    if status == 429:
        return "MinerU API rate limit hit (429). Try again later or reduce request volume."
    return f"MinerU API returned HTTP {status}."


def _reset_dir(path: Path) -> None:
    if path.exists():
        import shutil

        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _extract_archive(archive_bytes: bytes, target_dir: Path) -> None:
    """Extract the MinerU zip into ``target_dir``, preserving its directory
    tree (the ``images/`` subdir matters) while defending against Zip Slip and
    zip bombs. Unlike :func:`safe_extract_zip`, this keeps subdirectories and
    does not apply a document-extension whitelist — the archive is a trusted
    MinerU artifact, not a user upload."""
    target_root = target_dir.resolve()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if len(members) > _MAX_ENTRIES:
                raise MinerUError(f"MinerU archive has too many entries ({len(members)}).")
            for member in members:
                # Collapse to a POSIX-relative path and reject traversal.
                rel = Path(member.filename.replace("\\", "/"))
                if rel.is_absolute() or ".." in rel.parts:
                    logger.warning("Skipping unsafe zip member: %s", member.filename)
                    continue
                dest = (target_root / rel).resolve()
                if target_root not in dest.parents and dest != target_root:
                    logger.warning("Skipping zip member escaping root: %s", member.filename)
                    continue
                member_size = int(member.file_size)
                compressed_size = int(member.compress_size)
                if member_size > _MAX_ENTRY_BYTES:
                    raise MinerUError("MinerU archive entry exceeds the size limit.")
                if member_size and (
                    compressed_size <= 0 or member_size > compressed_size * _MAX_COMPRESSION_RATIO
                ):
                    raise MinerUError("MinerU archive entry has an unsafe compression ratio.")
                total += member_size
                if total > _MAX_TOTAL_BYTES:
                    raise MinerUError("MinerU archive exceeds the size limit.")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, open(dest, "wb") as out:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
    except zipfile.BadZipFile as exc:
        raise MinerUError(f"MinerU returned an invalid archive: {exc}") from exc


__all__ = ["parse_cloud", "verify_credentials"]
