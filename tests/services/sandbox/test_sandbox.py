"""Sandbox: backend selection, restricted subprocess exec, quota, level gating."""

from __future__ import annotations

import asyncio
import http.client
import json
import os
from pathlib import Path
import shlex
import socket
import sys
import threading
import time

import pytest

from deeptutor.services.sandbox.backends import BwrapBackend, RestrictedSubprocessBackend
from deeptutor.services.sandbox.config import SandboxSettings, build_backend
from deeptutor.services.sandbox.quota import QuotaExceeded, UserExecQuota
from deeptutor.services.sandbox.service import SandboxService
from deeptutor.services.sandbox.spec import (
    ExecRequest,
    ExecResult,
    IsolationLevel,
    Mount,
    ResourceLimits,
)


def test_backend_selection_runner_url() -> None:
    from deeptutor.services.sandbox.backends import RunnerSidecarBackend

    settings = SandboxSettings(runner_url="http://sandbox-runner:8900", runner_token="test-token")
    backend = build_backend(settings)
    assert isinstance(backend, RunnerSidecarBackend)
    assert backend.level is IsolationLevel.SYSTEM


@pytest.mark.asyncio
async def test_runner_backend_fails_closed_without_authentication_token(tmp_path) -> None:
    from deeptutor.services.sandbox.backends import RunnerSidecarBackend

    backend = RunnerSidecarBackend("http://sandbox-runner:8900")
    result = await backend.exec(
        ExecRequest(
            command="true",
            workdir=str(tmp_path),
            mounts=(
                Mount(
                    host_path=str(tmp_path),
                    sandbox_path=str(tmp_path),
                    read_only=False,
                ),
            ),
        )
    )

    assert "authentication token is not configured" in result.error


def test_sandbox_settings_reads_runner_token_and_keeps_host_fallback_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPTUTOR_SANDBOX_RUNNER_URL", "http://sandbox-runner:8900")
    monkeypatch.setenv("DEEPTUTOR_SANDBOX_RUNNER_TOKEN", "configured-token")
    monkeypatch.delenv("DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS", raising=False)

    settings = SandboxSettings.from_env()

    assert settings.runner_token == "configured-token"
    assert settings.allow_subprocess is False


def test_backend_selection_none_without_optin() -> None:
    # No runner, subprocess not allowed → no backend (on non-bwrap hosts).
    settings = SandboxSettings(runner_url="", allow_subprocess=False)
    backend = build_backend(settings)
    # On a Linux host with bwrap installed this could be BwrapBackend; the
    # invariant we assert is that subprocess fallback is NOT silently used.
    from deeptutor.services.sandbox.backends import RestrictedSubprocessBackend

    assert not isinstance(backend, RestrictedSubprocessBackend)


def test_backend_selection_subprocess_optin() -> None:
    settings = SandboxSettings(runner_url="", allow_subprocess=True)
    # build_backend prefers bwrap on Linux; force the subprocess path by
    # asserting only when no bwrap candidate is chosen.
    backend = build_backend(settings)
    assert backend is not None


def test_bwrap_binds_usr_local_when_available(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    usr = tmp_path / "usr"
    usr_local = tmp_path / "usr" / "local"
    missing = tmp_path / "missing"
    usr_local.mkdir(parents=True)

    monkeypatch.setattr(
        BwrapBackend,
        "_RO_SYSTEM_DIRS",
        (str(usr), str(usr_local), str(missing)),
    )

    argv = BwrapBackend(bwrap_path="bwrap")._build_argv(ExecRequest(command="true"))

    usr_index = argv.index(str(usr))
    assert argv[usr_index - 1 : usr_index + 2] == ["--ro-bind", str(usr), str(usr)]
    assert str(usr_local) in argv
    assert str(missing) not in argv


def test_bwrap_clears_application_secrets_and_restores_only_safe_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPTUTOR_TEST_PROVIDER_SECRET", "must-not-cross")
    monkeypatch.setenv("PATH", "/safe/bin")

    argv = BwrapBackend(bwrap_path="bwrap")._build_argv(
        ExecRequest(command="env", env={"REQUEST_VALUE": "allowed"})
    )

    assert "--clearenv" in argv
    assert "DEEPTUTOR_TEST_PROVIDER_SECRET" not in argv
    path_index = argv.index("PATH")
    assert argv[path_index - 1 : path_index + 2] == ["--setenv", "PATH", "/safe/bin"]
    request_index = argv.index("REQUEST_VALUE")
    assert argv[request_index - 1 : request_index + 2] == [
        "--setenv",
        "REQUEST_VALUE",
        "allowed",
    ]


@pytest.mark.asyncio
async def test_restricted_subprocess_runs() -> None:
    backend = RestrictedSubprocessBackend()
    result = await backend.exec(ExecRequest(command="echo hello"))
    assert result.ok
    assert "hello" in result.stdout
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_restricted_subprocess_timeout() -> None:
    backend = RestrictedSubprocessBackend()
    result = await backend.exec(ExecRequest(command="sleep 5", limits=ResourceLimits(timeout_s=1)))
    assert result.timed_out
    assert result.exit_code == 124


@pytest.mark.asyncio
async def test_restricted_subprocess_stops_when_output_budget_is_exceeded() -> None:
    request = ExecRequest(
        command=f"{shlex.quote(sys.executable)} -c \"print('x' * 20000)\"",
        limits=ResourceLimits(timeout_s=5, max_output_chars=100),
    )
    result = await RestrictedSubprocessBackend().exec(request)
    assert "output limit exceeded" in result.error
    assert len(result.stdout) <= 400


@pytest.mark.skipif(os.name != "posix", reason="process-group cleanup requires POSIX")
@pytest.mark.parametrize("limit", ["timeout", "output"])
@pytest.mark.asyncio
async def test_restricted_subprocess_limit_stops_descendant_processes(tmp_path, limit: str) -> None:
    """The local fallback must not leave a child alive after enforcement."""
    marker = tmp_path / f"{limit}-fallback-descendant-survived"
    child_script = (
        "import pathlib, time; "
        "time.sleep(1.5); "
        f"pathlib.Path({str(marker)!r}).write_text('survived', encoding='utf-8')"
    )
    parent_script = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child_script!r}]); "
        + (
            "time.sleep(30)"
            if limit == "timeout"
            else "print('x' * 100000, flush=True); time.sleep(30)"
        )
    )
    limits = ResourceLimits(timeout_s=1, max_output_chars=10_000)
    if limit == "output":
        limits = ResourceLimits(timeout_s=5, max_output_chars=16)

    result = await RestrictedSubprocessBackend().exec(
        ExecRequest.of_argv([sys.executable, "-c", parent_script], limits=limits)
    )

    if limit == "timeout":
        assert result.timed_out
        assert result.exit_code == 124
    else:
        assert "output limit exceeded" in result.error
    await asyncio.sleep(0.8 if limit == "timeout" else 1.8)
    assert not marker.exists(), "fallback limit left a descendant process alive"


@pytest.mark.asyncio
async def test_service_disabled_when_no_backend() -> None:
    svc = SandboxService(SandboxSettings(runner_url="", allow_subprocess=False))
    # Force the "no backend" branch deterministically.
    svc._backend = None
    assert await svc.isolation_level() is IsolationLevel.OFF
    result = await svc.run(ExecRequest(command="echo hi"), user_id="u1")
    assert not result.ok
    assert result.error


@pytest.mark.asyncio
async def test_service_runs_with_subprocess() -> None:
    svc = SandboxService(SandboxSettings(allow_subprocess=True))
    svc._backend = RestrictedSubprocessBackend()
    result = await svc.run(ExecRequest(command="echo sandboxed"), user_id="u1")
    assert "sandboxed" in result.stdout


@pytest.mark.asyncio
async def test_quota_rate_limit() -> None:
    quota = UserExecQuota(max_concurrent=5, max_per_minute=2)
    async with await quota.acquire("u1"):
        pass
    async with await quota.acquire("u1"):
        pass
    with pytest.raises(QuotaExceeded):
        await quota.acquire("u1")
    # a different user is unaffected
    async with await quota.acquire("u2"):
        pass


@pytest.mark.asyncio
async def test_quota_concurrency_limit() -> None:
    quota = UserExecQuota(max_concurrent=1, max_per_minute=100)
    lease = await quota.acquire("u1")
    with pytest.raises(QuotaExceeded):
        await quota.acquire("u1")
    await lease.__aexit__(None, None, None)
    # slot freed
    async with await quota.acquire("u1"):
        pass


def test_exec_result_render_truncates() -> None:
    result = ExecResult(stdout="x" * 1000, exit_code=0)
    rendered = result.render(max_chars=100)
    assert "truncated" in rendered
    assert len(rendered) < 400


def test_exec_result_render_error() -> None:
    assert "boom" in ExecResult(error="boom").render(100)


def _valid_runner_payload(root: Path, **updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "command": "true",
        "principal_root": str(root),
        "workdir": str(root),
        "mounts": [],
        "limits": {"timeout_s": 5},
    }
    payload.update(updates)
    return payload


def test_runner_server_validates_request_shape(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.sandbox.runner import server

    monkeypatch.setattr(server, "_ALLOWED_PRINCIPAL_ROOTS", [str(tmp_path)])
    assert "principal_root" in server.execute({})["error"]
    assert "command" in server.execute(_valid_runner_payload(tmp_path, command=""))["error"]
    assert "workdir" in server.execute(_valid_runner_payload(tmp_path, workdir=123))["error"]
    assert "env" in server.execute(_valid_runner_payload(tmp_path, env=["bad"]))["error"]
    assert (
        "mounts" in server.execute(_valid_runner_payload(tmp_path, mounts={"bad": True}))["error"]
    )
    assert "limits" in server.execute(_valid_runner_payload(tmp_path, limits=["bad"]))["error"]


def test_runner_server_executes_and_truncates_output(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.sandbox.runner import server

    monkeypatch.setattr(server, "_ALLOWED_PRINCIPAL_ROOTS", [str(tmp_path)])
    result = server.execute(
        _valid_runner_payload(
            tmp_path,
            command=f"{shlex.quote(sys.executable)} -c \"print('x' * 200)\"",
            limits={"timeout_s": 5, "max_output_chars": 40},
        )
    )

    assert result["exit_code"] == 0
    assert result["error"] == ""
    assert "truncated" in result["stdout"]
    assert len(result["stdout"]) < 120


def test_runner_server_clamps_request_limits(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.sandbox.runner import server

    monkeypatch.setattr(server, "_ALLOWED_PRINCIPAL_ROOTS", [str(tmp_path)])
    captured: dict[str, int] = {}

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN002
        captured.update(
            {
                "timeout_s": kwargs["timeout_s"],
                "max_output_chars": kwargs["max_output_chars"],
            }
        )
        return b"", b"", False, False, 0

    monkeypatch.setattr(server, "_run_bounded_process", fake_run)
    result = server.execute(
        _valid_runner_payload(
            tmp_path,
            limits={
                "timeout_s": 10**9,
                "memory_mb": 10**9,
                "cpu_seconds": 10**9,
                "max_output_chars": 10**9,
            },
        )
    )

    assert result["error"] == ""
    assert captured == {"timeout_s": 300, "max_output_chars": 1_000_000}


@pytest.mark.skipif(os.name != "posix", reason="runner process groups require POSIX")
@pytest.mark.parametrize("limit", ["timeout", "output"])
def test_runner_server_limit_stops_descendant_processes(
    tmp_path, limit: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A background child must not outlive a timeout or output-cap response."""
    from deeptutor.services.sandbox.runner import server

    monkeypatch.setattr(server, "_ALLOWED_PRINCIPAL_ROOTS", [str(tmp_path)])

    marker = tmp_path / f"{limit}-descendant-survived"
    child_script = (
        "import pathlib, time; "
        "time.sleep(1.5); "
        f"pathlib.Path({str(marker)!r}).write_text('survived', encoding='utf-8')"
    )
    parent_script = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child_script!r}]); "
        + (
            "time.sleep(30)"
            if limit == "timeout"
            else "print('x' * 100000, flush=True); time.sleep(30)"
        )
    )
    limits = {"timeout_s": 1, "max_output_chars": 10_000}
    if limit == "output":
        limits["max_output_chars"] = 16

    result = server.execute(
        {
            "command": "unused",
            "argv": [sys.executable, "-c", parent_script],
            "principal_root": str(tmp_path),
            "workdir": str(tmp_path),
            "limits": limits,
        }
    )

    if limit == "timeout":
        assert result["timed_out"] is True
        assert result["exit_code"] == 124
    else:
        assert result["timed_out"] is False
        assert result["exit_code"] == 0
    # Timeout returns after about one second; output capping returns almost
    # immediately. Wait long enough that an escaped child would write in both
    # cases, without making the test depend on process reaping details.
    time.sleep(0.8 if limit == "timeout" else 1.8)
    assert not marker.exists(), "runner limit left a descendant process alive"


def test_runner_server_rejects_workdir_outside_allowed_roots(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.sandbox.runner import server

    allowed = tmp_path / "workspace"
    allowed.mkdir()
    monkeypatch.setattr(server, "_ALLOWED_PRINCIPAL_ROOTS", [str(allowed)])

    outside = server.execute(
        _valid_runner_payload(
            allowed,
            principal_root=str(allowed),
            workdir=str(tmp_path / "elsewhere"),
        )
    )
    assert "outside the authenticated principal_root" in outside["error"]

    # Symlinks that point out of the allowed tree must not slip through.
    sneaky = allowed / "link"
    sneaky.symlink_to(tmp_path)
    via_link = server.execute(
        _valid_runner_payload(allowed, principal_root=str(allowed), workdir=str(sneaky))
    )
    assert "outside the authenticated principal_root" in via_link["error"]

    inside = server.execute(_valid_runner_payload(allowed))
    assert inside["error"] == ""
    assert inside["exit_code"] == 0


def test_runner_server_rejects_cross_principal_and_writable_mounts(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.sandbox.runner import server

    admin = tmp_path / "admin"
    other = tmp_path / "other"
    admin.mkdir()
    other.mkdir()
    monkeypatch.setattr(server, "_ALLOWED_PRINCIPAL_ROOTS", [str(admin)])

    cross_principal = server.execute(
        _valid_runner_payload(other, principal_root=str(other), workdir=str(other))
    )
    assert "deployment allowlist" in cross_principal["error"]

    cross_mount = server.execute(
        _valid_runner_payload(
            admin,
            mounts=[
                {
                    "host_path": str(other),
                    "sandbox_path": str(other),
                    "read_only": False,
                }
            ],
        )
    )
    assert "principal boundary" in cross_mount["error"]


def test_runner_http_requires_token_and_honors_authenticated_request(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.sandbox.runner import server

    monkeypatch.setattr(server, "_RUNNER_TOKEN", "correct-token")
    monkeypatch.setattr(server, "_ALLOWED_PRINCIPAL_ROOTS", [str(tmp_path)])
    httpd = server._RunnerHTTPServer(("127.0.0.1", 0), server._Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        from deeptutor.services.sandbox.backends import RunnerSidecarBackend

        healthy, detail = asyncio.run(
            RunnerSidecarBackend(
                f"http://127.0.0.1:{httpd.server_port}", token="correct-token"
            ).health()
        )
        assert healthy is True
        assert "protocol v2" in detail

        capabilities = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
        capabilities.request("GET", server._RUNNER_CAPABILITIES_PATH)
        unauthorized_capabilities = capabilities.getresponse()
        unauthorized_capabilities.read()
        assert unauthorized_capabilities.status == 401
        capabilities.close()

        capabilities = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
        capabilities.request(
            "GET",
            server._RUNNER_CAPABILITIES_PATH,
            headers={"Authorization": "Bearer correct-token"},
        )
        advertised = capabilities.getresponse()
        capability_body = json.loads(advertised.read())
        assert advertised.status == 200
        assert capability_body["protocol_version"] == server._RUNNER_PROTOCOL_VERSION
        assert set(capability_body["capabilities"]) >= {
            "authorization",
            "principal_root",
            "argv",
            "bounded_execution",
        }
        capabilities.close()

        body = json.dumps(_valid_runner_payload(tmp_path))
        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
        connection.request(
            "POST",
            server._RUNNER_EXEC_PATH,
            body=body,
            headers={"Content-Type": "application/json"},
        )
        unauthorized = connection.getresponse()
        unauthorized.read()
        assert unauthorized.status == 401
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
        connection.request(
            "POST",
            server._RUNNER_EXEC_PATH,
            body=body,
            headers={
                "Authorization": "Bearer correct-token",
                "Content-Type": "application/json",
            },
        )
        accepted = connection.getresponse()
        response = json.loads(accepted.read())
        assert accepted.status == 200
        assert response["error"] == ""
        assert response["exit_code"] == 0
        connection.close()

        # A pre-v2 runner only knows /exec. The app's versioned path must not
        # silently fall back to it during a mixed-version rollout.
        stale_path = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
        stale_path.request(
            "POST",
            "/exec",
            body=body,
            headers={
                "Authorization": "Bearer correct-token",
                "Content-Type": "application/json",
            },
        )
        stale_response = stale_path.getresponse()
        stale_response.read()
        assert stale_response.status == 404
        stale_path.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_runner_http_rejects_when_global_capacity_is_exhausted(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.sandbox.runner import server

    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(server, "_EXECUTION_SLOTS", slots)
    monkeypatch.setattr(server, "_RUNNER_TOKEN", "correct-token")
    httpd = server._RunnerHTTPServer(("127.0.0.1", 0), server._Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(_valid_runner_payload(tmp_path))
        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
        connection.request(
            "POST",
            server._RUNNER_EXEC_PATH,
            body=body,
            headers={"Authorization": "Bearer correct-token"},
        )
        response = connection.getresponse()
        response.read()
        assert response.status == 429
        connection.close()
    finally:
        slots.release()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_runner_http_times_out_partial_authenticated_body(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.sandbox.runner import server

    monkeypatch.setattr(server, "_RUNNER_TOKEN", "correct-token")
    monkeypatch.setattr(server, "_REQUEST_IO_TIMEOUT_S", 0.1)
    httpd = server._RunnerHTTPServer(("127.0.0.1", 0), server._Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    client = socket.create_connection(("127.0.0.1", httpd.server_port), timeout=2)
    try:
        client.sendall(
            f"POST {server._RUNNER_EXEC_PATH} HTTP/1.1\r\n".encode()
            + b"Host: runner\r\n"
            + b"Authorization: Bearer correct-token\r\n"
            + b"Content-Length: 100\r\n\r\n{}"
        )
        response = client.recv(4096)
        assert b"408 Request Timeout" in response
    finally:
        client.close()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_runner_child_preexec_drops_identity_after_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.sandbox.runner import server

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(server, "_POSIX", True)
    monkeypatch.setattr(server.sys, "platform", "linux")
    monkeypatch.setattr(server.os, "geteuid", lambda: 0)
    monkeypatch.setattr(server.os, "setgroups", lambda groups: calls.append(("groups", groups)))
    monkeypatch.setattr(server.os, "setgid", lambda gid: calls.append(("gid", gid)))
    monkeypatch.setattr(server.os, "setuid", lambda uid: calls.append(("uid", uid)))
    monkeypatch.setattr(server.resource, "setrlimit", lambda *_args: None)

    preexec = server._build_preexec_fn(memory_mb=32, cpu_seconds=3)
    assert preexec is not None
    preexec()

    assert calls == [("groups", []), ("gid", 1000), ("uid", 1000)]


def test_runner_orphan_cleanup_kills_every_adopted_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.sandbox.runner import server

    snapshots = iter([[101, 102], []])
    killed: list[int] = []
    monkeypatch.setattr(server.sys, "platform", "linux")
    monkeypatch.setattr(server, "_direct_child_pids", lambda: next(snapshots, []))
    monkeypatch.setattr(server.os, "kill", lambda pid, _signal: killed.append(pid))
    monkeypatch.setattr(
        server.os,
        "waitpid",
        lambda *_args: (_ for _ in ()).throw(ChildProcessError()),
    )

    server._terminate_adopted_children()

    assert killed == [101, 102]
