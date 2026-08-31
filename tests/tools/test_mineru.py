from __future__ import annotations

import io
import json
from pathlib import Path
import signal
import socket
import time
import zipfile

import httpx as real_httpx
import pytest

from deeptutor.services.parsing.engines.mineru import backend as mineru_backend
from deeptutor.services.parsing.engines.mineru import cloud as mineru_cloud
from deeptutor.services.parsing.engines.mineru import config as mineru_config
from deeptutor.services.parsing.engines.mineru.config import MinerUConfig, MinerUError

# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def test_resolve_mineru_config_reads_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mineru_config,
        "load_mineru_settings",
        lambda: {
            "mode": "cloud",
            "api_token": "tok",
            "model_version": "vlm",
            "language": "ch",
            "api_base_url": "https://x",
            "enable_formula": False,
            "enable_table": True,
            "is_ocr": True,
        },
    )
    cfg = mineru_config.resolve_mineru_config()
    assert cfg.is_cloud and not cfg.is_local
    assert cfg.api_token == "tok"
    assert cfg.model_version == "vlm"
    assert cfg.api_language == "ch"

    monkeypatch.setattr(
        mineru_config, "load_mineru_settings", lambda: {"mode": "local", "language": "auto"}
    )
    auto_cfg = mineru_config.resolve_mineru_config()
    assert auto_cfg.is_local
    assert auto_cfg.api_language is None  # "auto" → omit the language hint


# ---------------------------------------------------------------------------
# Backend dispatch
# ---------------------------------------------------------------------------


def test_parse_pdf_to_workdir_dispatches_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.parsing.engines.mineru import local as pdf_parser

    pdf = tmp_path / "exam.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    out = tmp_path / "out"

    def fake_local(p: str, base: str, **kwargs) -> bool:  # noqa: ANN003
        (Path(base) / Path(p).stem).mkdir(parents=True, exist_ok=True)
        return True

    monkeypatch.setattr(pdf_parser, "parse_pdf_with_mineru", fake_local)

    workdir = mineru_backend.parse_pdf_to_workdir(pdf, out, config=MinerUConfig(mode="local"))
    assert workdir == out / "exam"


def test_parse_pdf_to_workdir_local_failure_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.parsing.engines.mineru import local as pdf_parser

    pdf = tmp_path / "exam.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(pdf_parser, "parse_pdf_with_mineru", lambda *a, **k: False)

    with pytest.raises(MinerUError):
        mineru_backend.parse_pdf_to_workdir(
            pdf, tmp_path / "out", config=MinerUConfig(mode="local")
        )


def test_parse_pdf_to_workdir_dispatches_cloud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "exam.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    called: dict[str, bool] = {}

    def fake_cloud(p, base, cfg, **kwargs):  # noqa: ANN001, ANN003
        called["yes"] = True
        target = Path(base) / "clouddir"
        target.mkdir(parents=True, exist_ok=True)
        return target

    monkeypatch.setattr(mineru_cloud, "parse_cloud", fake_cloud)

    workdir = mineru_backend.parse_pdf_to_workdir(
        pdf, tmp_path / "out", config=MinerUConfig(mode="cloud", api_token="t")
    )
    assert called.get("yes") is True
    assert workdir.name == "clouddir"


# ---------------------------------------------------------------------------
# Cloud client internals
# ---------------------------------------------------------------------------


def test_verify_credentials_requires_token() -> None:
    with pytest.raises(MinerUError):
        mineru_cloud.verify_credentials(MinerUConfig(mode="cloud", api_token=""))


def test_local_cli_probe_reports_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mineru_backend.shutil,
        "which",
        lambda cmd: "/opt/env/bin/mineru" if cmd == "mineru" else None,
    )
    probe = mineru_backend.local_cli_probe()
    assert probe == {
        "found": True,
        "command": "mineru",
        "path": "/opt/env/bin/mineru",
        "source": "path",
    }

    monkeypatch.setattr(mineru_backend.shutil, "which", lambda cmd: None)
    assert mineru_backend.local_cli_probe()["found"] is False


def test_local_cli_probe_configured_path_takes_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Even with a PATH hit available, an explicit configured path wins.
    monkeypatch.setattr(mineru_backend.shutil, "which", lambda cmd: "/usr/bin/magic-pdf")

    exe = tmp_path / "mineru"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    probe = mineru_backend.local_cli_probe(str(exe))
    assert probe == {
        "found": True,
        "command": "mineru",
        "path": str(exe),
        "source": "configured",
    }

    # A configured path that isn't an executable file reports not-found
    # (no silent fallback to PATH — the admin asked for this exact binary).
    probe = mineru_backend.local_cli_probe(str(tmp_path / "missing"))
    assert probe["found"] is False
    assert probe["source"] == "configured"


def test_parse_local_rejects_bad_configured_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "exam.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with pytest.raises(MinerUError) as exc:
        mineru_backend.parse_pdf_to_workdir(
            pdf,
            tmp_path / "out",
            config=MinerUConfig(mode="local", local_cli_path=str(tmp_path / "nope")),
        )
    assert "not an executable" in str(exc.value)


def test_local_cli_version_rejects_unknown_command() -> None:
    # Whitelist guard: bare names outside the whitelist (and non-executable
    # paths) never reach subprocess.
    assert mineru_backend.local_cli_version("definitely-not-a-cli") == ""


def test_pdf_parser_streams_output_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.parsing.engines.mineru import local as pdf_parser

    pdf = tmp_path / "exam.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    out = tmp_path / "out"

    class FakeProcess:
        def __init__(self, cmd, **kwargs):  # noqa: ANN002, ANN003
            # Simulate the CLI writing its artifacts under the -o directory.
            target = Path(cmd[cmd.index("-o") + 1]) / "exam"
            (target / "auto").mkdir(parents=True, exist_ok=True)
            (target / "auto" / "exam.md").write_text("# parsed", encoding="utf-8")
            self.stdout = iter(["downloading model...\n", "\n", "parsing page 1/3\n"])

        def wait(self):
            return 0

    monkeypatch.setattr(pdf_parser, "check_mineru_installed", lambda: "mineru")
    monkeypatch.setattr(pdf_parser.subprocess, "Popen", FakeProcess)

    seen: list[str] = []
    ok = pdf_parser.parse_pdf_with_mineru(str(pdf), str(out), on_output=seen.append)

    assert ok is True
    # Throttled, but the first line always gets through; blanks are dropped.
    assert seen and seen[0] == "downloading model..."
    assert (out / "exam" / "auto" / "exam.md").exists()


def test_local_parser_deadline_terminates_the_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A silent local CLI cannot keep a parsing worker forever."""

    from deeptutor.services.parsing.engines.mineru import local as pdf_parser

    class BlockingStdout:
        def __iter__(self):
            return self

        def __next__(self):
            time.sleep(60)
            return ""

    class FakeProcess:
        pid = 4242
        stdout = BlockingStdout()

        def poll(self):
            return None

        def wait(self, timeout=None):  # noqa: ANN001
            return 0

    killed: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(pdf_parser.os, "killpg", lambda pid, sig: killed.append((pid, sig)))

    result = pdf_parser._stream_process_output(
        FakeProcess(),
        tail=pdf_parser.deque(maxlen=40),
        on_output=None,
        timeout=0.01,
    )

    assert result is None
    assert killed == [(4242, signal.SIGTERM)]


def test_parse_cloud_reports_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "exam.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    poll_count = {"n": 0}

    def poll(path):  # noqa: ANN001
        poll_count["n"] += 1
        if poll_count["n"] == 1:
            return _Resp(
                {
                    "code": 0,
                    "data": {
                        "extract_result": [
                            {
                                "file_name": "exam.pdf",
                                "state": "running",
                                "extract_progress": {"extracted_pages": 1, "total_pages": 3},
                            }
                        ]
                    },
                }
            )
        return _Resp(
            {
                "code": 0,
                "data": {
                    "extract_result": [
                        {"file_name": "exam.pdf", "state": "done", "full_zip_url": "https://zip"}
                    ]
                },
            }
        )

    _install_fake_httpx(
        monkeypatch,
        submit=lambda path, body: _Resp(
            {"code": 0, "data": {"batch_id": "B", "file_urls": ["https://up"]}}
        ),
        poll=poll,
        download=lambda url: _Resp(content=_zip_bytes(), status=200),
    )

    reports: list[str] = []
    mineru_cloud.parse_cloud(
        pdf,
        tmp_path / "out",
        MinerUConfig(mode="cloud", api_token="tok"),
        poll_interval=0,
        timeout=10,
        on_progress=reports.append,
    )
    assert any("1/3 pages" in r for r in reports)
    assert any("done" in r for r in reports)


def test_match_entry_prefers_filename_then_first() -> None:
    rows = [
        {"file_name": "a.pdf", "state": "running"},
        {"file_name": "b.pdf", "state": "done"},
    ]
    assert mineru_cloud._match_entry(rows, "b.pdf")["state"] == "done"
    assert mineru_cloud._match_entry(rows, "zzz.pdf")["file_name"] == "a.pdf"
    assert mineru_cloud._match_entry([], "x.pdf") is None


def test_extract_archive_rejects_zip_slip(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("../evil.txt", "pwned")
        archive.writestr("safe.md", "ok")
        archive.writestr("images/fig.png", b"img")
    workdir = tmp_path / "wd"

    mineru_cloud._extract_archive(buf.getvalue(), workdir)

    assert (workdir / "safe.md").exists()
    assert (workdir / "images" / "fig.png").exists()
    # The traversal member must not escape the working dir.
    assert not (tmp_path / "evil.txt").exists()


def test_extract_archive_rejects_unsafe_compression_ratio(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("huge.md", b"0" * (2 * 1024 * 1024))

    with pytest.raises(MinerUError, match="compression ratio"):
        mineru_cloud._extract_archive(buf.getvalue(), tmp_path / "wd")


def test_download_rejects_oversized_response_before_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Response:
        headers = {"content-length": str(mineru_cloud._MAX_DOWNLOAD_BYTES + 1)}

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self, *, chunk_size: int):
            assert chunk_size == mineru_cloud._DOWNLOAD_CHUNK_BYTES
            yield b""

    response = _Response()
    from types import SimpleNamespace

    fake = SimpleNamespace(
        stream=lambda *args, **kwargs: response,
        HTTPError=real_httpx.HTTPError,
    )
    monkeypatch.setattr(mineru_cloud, "httpx", fake)
    monkeypatch.setattr(mineru_cloud, "_assert_public_https_url", lambda value, **kwargs: value)

    with pytest.raises(MinerUError, match="download size limit"):
        mineru_cloud._download("https://zip")


def test_download_streams_and_rejects_oversized_chunked_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StreamingResponse:
        headers: dict[str, str] = {}

        def __enter__(self) -> "_StreamingResponse":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def raise_for_status(self) -> None:
            return None

        @property
        def content(self) -> bytes:
            raise AssertionError("download must not materialize response.content")

        def iter_bytes(self, *, chunk_size: int):
            assert chunk_size == mineru_cloud._DOWNLOAD_CHUNK_BYTES
            yield b"12345"
            yield b"67890"
            yield b"x"

    from types import SimpleNamespace

    fake = SimpleNamespace(
        stream=lambda *args, **kwargs: _StreamingResponse(),
        HTTPError=real_httpx.HTTPError,
    )
    monkeypatch.setattr(mineru_cloud, "httpx", fake)
    monkeypatch.setattr(mineru_cloud, "_MAX_DOWNLOAD_BYTES", 10)
    monkeypatch.setattr(mineru_cloud, "_assert_public_https_url", lambda value, **kwargs: value)

    with pytest.raises(MinerUError, match="download size limit"):
        mineru_cloud._download("https://zip")


def test_provider_urls_require_public_https(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(MinerUError, match="unsafe"):
        mineru_cloud._assert_public_https_url("http://example.test/upload", purpose="upload")

    monkeypatch.setattr(
        mineru_cloud.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(MinerUError, match="unsafe"):
        mineru_cloud._assert_public_https_url("https://example.test/upload", purpose="upload")


def test_provider_connection_uses_validated_numeric_address_without_reresolving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DNS rebinding after validation cannot change the TCP destination."""

    calls: list[tuple[object, ...]] = []

    def initial_lookup(*args: object, **kwargs: object):  # noqa: ANN002, ANN003
        calls.append(args)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(mineru_cloud.socket, "getaddrinfo", initial_lookup)
    destination = mineru_cloud._assert_public_https_url(
        "https://provider.example.test/upload", purpose="upload"
    )
    assert calls

    # A later resolver answer is malicious, but the pinning backend must not
    # consult DNS again and therefore never sees/dials it.
    monkeypatch.setattr(
        mineru_cloud.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    backend = mineru_cloud._PinnedNetworkBackend(destination)
    dialed: dict[str, object] = {}

    class Delegate:
        def connect_tcp(self, **kwargs: object) -> str:
            dialed.update(kwargs)
            return "connected"

        def connect_unix_socket(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("unexpected Unix socket connection")

        def sleep(self, seconds: float) -> None:
            return None

    backend._backend = Delegate()  # type: ignore[assignment]
    assert backend.connect_tcp("provider.example.test", 443) == "connected"
    assert dialed["host"] == "93.184.216.34"


def test_provider_connection_rejects_unvalidated_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mineru_cloud.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    destination = mineru_cloud._assert_public_https_url(
        "https://provider.example.test/upload", purpose="upload"
    )
    backend = mineru_cloud._PinnedNetworkBackend(destination)

    with pytest.raises(mineru_cloud.httpcore.ConnectError, match="unvalidated"):
        backend.connect_tcp("other.example.test", 443)


def test_upload_streams_pdf_without_reading_the_whole_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "exam.pdf"
    pdf.write_bytes(b"123456789")
    captured: list[bytes] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):  # noqa: ANN002
            return False

        def raise_for_status(self) -> None:
            return None

    def stream(method, url, **kwargs):  # noqa: ANN001
        assert method == "PUT"
        assert url == "https://uploads.example.test/signed"
        captured.extend(kwargs["content"])
        return Response()

    from types import SimpleNamespace

    monkeypatch.setattr(
        mineru_cloud, "httpx", SimpleNamespace(stream=stream, HTTPError=real_httpx.HTTPError)
    )
    monkeypatch.setattr(mineru_cloud, "_assert_public_https_url", lambda value, **kwargs: value)

    mineru_cloud._upload_file(pdf, "https://uploads.example.test/signed")

    assert b"".join(captured) == b"123456789"


# ---------------------------------------------------------------------------
# Cloud client end-to-end (mocked transport)
# ---------------------------------------------------------------------------


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("full.md", "# Exam\n1. Question one")
        archive.writestr("exam_content_list.json", json.dumps([{"type": "text", "text": "Q1"}]))
        archive.writestr("images/fig.png", b"img")
    return buf.getvalue()


class _Resp:
    def __init__(self, json_data=None, content=b"", status=200):  # noqa: ANN001
        self._json = json_data
        self.content = content
        self.status_code = status

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            request = real_httpx.Request("GET", "http://x")
            response = real_httpx.Response(self.status_code, request=request)
            raise real_httpx.HTTPStatusError("err", request=request, response=response)

    def __enter__(self):
        return self

    def __exit__(self, *args):  # noqa: ANN002
        return False

    def iter_bytes(self, *, chunk_size: int):
        yield self.content


def _install_fake_httpx(monkeypatch: pytest.MonkeyPatch, *, submit, poll, download) -> None:
    from types import SimpleNamespace

    class FakeClient:
        def __init__(self, *a, **k):  # noqa: ANN002, ANN003
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):  # noqa: ANN002
            return False

        def post(self, path, json=None, timeout=None):  # noqa: A002, ANN001
            return submit(path, json)

        def get(self, path, timeout=None):  # noqa: ANN001
            return poll(path)

    def stream(method, url, **kwargs):  # noqa: ANN001
        if method == "PUT":
            # Consume the iterator to retain the same file-read behavior as a
            # real HTTP client while keeping this transport fully local.
            list(kwargs.get("content") or [])
            return _Resp(status=200)
        return download(url)

    fake = SimpleNamespace(
        Client=FakeClient,
        stream=stream,
        HTTPError=real_httpx.HTTPError,
        HTTPStatusError=real_httpx.HTTPStatusError,
    )
    monkeypatch.setattr(mineru_cloud, "httpx", fake)
    monkeypatch.setattr(mineru_cloud, "_assert_public_https_url", lambda value, **kwargs: value)


def test_parse_cloud_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "exam.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")

    _install_fake_httpx(
        monkeypatch,
        submit=lambda path, body: _Resp(
            {"code": 0, "data": {"batch_id": "B", "file_urls": ["https://up"]}}
        ),
        poll=lambda path: _Resp(
            {
                "code": 0,
                "data": {
                    "extract_result": [
                        {"file_name": "exam.pdf", "state": "done", "full_zip_url": "https://zip"}
                    ]
                },
            }
        ),
        download=lambda url: _Resp(content=_zip_bytes(), status=200),
    )

    workdir = mineru_cloud.parse_cloud(
        pdf,
        tmp_path / "out",
        MinerUConfig(mode="cloud", api_token="tok"),
        poll_interval=0,
        timeout=10,
    )
    assert (workdir / "full.md").exists()
    assert (workdir / "exam_content_list.json").exists()
    assert (workdir / "images" / "fig.png").exists()


def test_parse_cloud_surfaces_api_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "exam.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    _install_fake_httpx(
        monkeypatch,
        submit=lambda path, body: _Resp({"code": 401, "msg": "bad token"}),
        poll=lambda path: _Resp({"code": 0, "data": {"extract_result": []}}),
        download=lambda url: _Resp(content=b"", status=200),
    )

    with pytest.raises(MinerUError) as exc:
        mineru_cloud.parse_cloud(
            pdf,
            tmp_path / "out",
            MinerUConfig(mode="cloud", api_token="bad"),
            poll_interval=0,
            timeout=10,
        )
    assert "401" in str(exc.value)


def test_parse_cloud_failed_state_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "exam.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    _install_fake_httpx(
        monkeypatch,
        submit=lambda path, body: _Resp(
            {"code": 0, "data": {"batch_id": "B", "file_urls": ["https://up"]}}
        ),
        poll=lambda path: _Resp(
            {
                "code": 0,
                "data": {
                    "extract_result": [
                        {"file_name": "exam.pdf", "state": "failed", "err_msg": "corrupt pdf"}
                    ]
                },
            }
        ),
        download=lambda url: _Resp(content=b"", status=200),
    )

    with pytest.raises(MinerUError) as exc:
        mineru_cloud.parse_cloud(
            pdf,
            tmp_path / "out",
            MinerUConfig(mode="cloud", api_token="tok"),
            poll_interval=0,
            timeout=10,
        )
    assert "corrupt pdf" in str(exc.value)
