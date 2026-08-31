"""
Sandbox backends: one class per isolation mechanism.

* :class:`RunnerSidecarBackend` — submits the command to a separate runner
  container over HTTP (SYSTEM isolation). The deployment answer for Docker:
  the main app stays least-privileged and never executes untrusted shell.
* :class:`BwrapBackend` — wraps the command in ``bwrap`` mount namespaces on
  Linux bare-metal (SYSTEM isolation).
* :class:`RestrictedSubprocessBackend` — a plain subprocess with cleaned env
  and path-confined cwd (APPLICATION isolation). Degraded fallback for local
  dev (e.g. macOS); admin-opt-in only because it does not OS-isolate.

Every backend is constructed from :class:`SandboxSettings` and reports the
isolation level it actually provides via :attr:`level`.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import os
from pathlib import Path
import resource
import shutil
import signal

import httpx

from deeptutor.services.sandbox.spec import (
    ExecRequest,
    ExecResult,
    IsolationLevel,
)


class SandboxBackend:
    """Abstract execution backend."""

    level: IsolationLevel = IsolationLevel.OFF

    async def exec(self, request: ExecRequest) -> ExecResult:
        raise NotImplementedError

    async def health(self) -> tuple[bool, str]:
        """Return ``(available, detail)`` — whether the backend can run now."""
        return True, ""


class RunnerSidecarBackend(SandboxBackend):
    """Delegate execution to the runner sidecar over HTTP."""

    level = IsolationLevel.SYSTEM

    def __init__(self, base_url: str, *, connect_timeout_s: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._connect_timeout_s = connect_timeout_s

    async def exec(self, request: ExecRequest) -> ExecResult:
        payload = {
            # Both spellings travel. A runner that understands ``argv`` prefers
            # it and runs without a shell; an older image ignores the unknown
            # field and executes the equivalent shell string. That keeps a
            # rolling deploy correct in either order, with no version handshake.
            "command": request.command,
            "argv": list(request.argv),
            "workdir": request.workdir,
            "env": request.env,
            "mounts": [
                {
                    "host_path": m.host_path,
                    "sandbox_path": m.sandbox_path,
                    "read_only": m.read_only,
                }
                for m in request.mounts
            ],
            "limits": {
                "timeout_s": request.limits.timeout_s,
                "memory_mb": request.limits.memory_mb,
                "cpu_seconds": request.limits.cpu_seconds,
                "max_output_chars": request.limits.max_output_chars,
            },
        }
        # Allow the HTTP call to outlast the command's own timeout a little so
        # the runner can report a clean timeout result instead of us aborting.
        http_timeout = httpx.Timeout(
            request.limits.timeout_s + 15,
            connect=self._connect_timeout_s,
        )
        try:
            async with httpx.AsyncClient(timeout=http_timeout) as client:
                resp = await client.post(f"{self._base_url}/exec", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            return ExecResult(error=f"runner unavailable: {type(exc).__name__}: {exc}")
        return ExecResult(
            stdout=str(data.get("stdout", "")),
            stderr=str(data.get("stderr", "")),
            exit_code=int(data.get("exit_code", 0)),
            timed_out=bool(data.get("timed_out", False)),
            error=str(data.get("error", "")),
        )

    async def health(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=self._connect_timeout_s) as client:
                resp = await client.get(f"{self._base_url}/health")
                resp.raise_for_status()
            return True, "runner reachable"
        except httpx.HTTPError as exc:
            return False, f"runner unreachable: {type(exc).__name__}"


class BwrapBackend(SandboxBackend):
    """Bubblewrap mount-namespace isolation (Linux only)."""

    level = IsolationLevel.SYSTEM

    _RO_SYSTEM_DIRS = ("/usr", "/usr/local", "/bin", "/lib", "/lib64", "/etc", "/sbin")

    def __init__(self, bwrap_path: str = "bwrap") -> None:
        self._bwrap = bwrap_path

    def _build_argv(self, request: ExecRequest) -> list[str]:
        argv = [
            self._bwrap,
            "--die-with-parent",
            "--unshare-all",
            "--new-session",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",  # nosec B108 — path inside the bwrap mount namespace, not the host
        ]
        for system_dir in self._RO_SYSTEM_DIRS:
            if Path(system_dir).exists():
                argv += ["--ro-bind", system_dir, system_dir]
        for mount in request.mounts:
            flag = "--ro-bind" if mount.read_only else "--bind"
            argv += [flag, mount.host_path, mount.sandbox_path]
        if request.workdir:
            argv += ["--chdir", request.workdir]
        for key, value in request.env.items():
            argv += ["--setenv", key, value]
        if request.argv:
            # No shell in between: bwrap execs the vector directly.
            argv += ["--", *request.argv]
        else:
            argv += ["/bin/sh", "-c", request.command]
        return argv

    async def exec(self, request: ExecRequest) -> ExecResult:
        argv = self._build_argv(request)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=_build_preexec_fn(request),
            )
        except FileNotFoundError:
            return ExecResult(error="bwrap not found on host")
        return await _communicate(
            process,
            request.limits.timeout_s,
            max_output_chars=request.limits.max_output_chars,
        )

    async def health(self) -> tuple[bool, str]:
        if shutil.which(self._bwrap) is None:
            return False, "bwrap not installed"
        # bwrap needs unprivileged user namespaces; a default-seccomp Docker
        # container blocks them, so confirm a trivial sandbox actually runs.
        probe = ExecRequest(command="true")
        result = await self.exec(probe)
        if result.error:
            return False, result.error
        return True, "bwrap functional"


class RestrictedSubprocessBackend(SandboxBackend):
    """Plain subprocess with a scrubbed env and confined cwd (no OS isolation)."""

    level = IsolationLevel.APPLICATION

    _SAFE_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")

    async def exec(self, request: ExecRequest) -> ExecResult:
        env = {k: os.environ[k] for k in self._SAFE_ENV_KEYS if k in os.environ}
        env.update(request.env)
        cwd = request.workdir or None
        try:
            if request.argv:
                process = await asyncio.create_subprocess_exec(
                    *request.argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                    preexec_fn=_build_preexec_fn(request),
                    start_new_session=os.name == "posix",
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    request.command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                    preexec_fn=_build_preexec_fn(request),
                    start_new_session=os.name == "posix",
                )
        except Exception as exc:
            return ExecResult(error=f"{type(exc).__name__}: {exc}")
        return await _communicate(
            process,
            request.limits.timeout_s,
            max_output_chars=request.limits.max_output_chars,
        )


def _build_preexec_fn(request: ExecRequest):
    """Apply resource limits in a local child before it executes."""
    if os.name != "posix":
        return None
    memory_mb = max(0, int(request.limits.memory_mb))
    cpu_seconds = max(0, int(request.limits.cpu_seconds))

    def _apply() -> None:
        if memory_mb:
            try:
                limit = memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            except (ValueError, OSError):
                pass
        if cpu_seconds:
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            except (ValueError, OSError):
                pass

    return _apply


async def _communicate(
    process: asyncio.subprocess.Process,
    timeout_s: int,
    *,
    max_output_chars: int,
) -> ExecResult:
    """Read both pipes with a byte budget so output cannot fill memory."""
    max_bytes = max(1, int(max_output_chars)) * 4
    overflow = asyncio.Event()

    def _stop_process_tree() -> None:
        """Terminate the request's process group, including descendants."""
        if os.name == "posix":
            with suppress(ProcessLookupError, OSError):
                os.killpg(process.pid, signal.SIGKILL)
                return
        with suppress(ProcessLookupError):
            process.kill()

    async def _read_bounded(stream: asyncio.StreamReader | None) -> bytes:
        if stream is None:
            return b""
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await stream.read(min(64 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            remaining = max_bytes - total
            if len(chunk) > remaining:
                chunks.append(chunk[:remaining])
                overflow.set()
                _stop_process_tree()
                break
            chunks.append(chunk)
            total += len(chunk)
        return b"".join(chunks)

    try:
        stdout, stderr = await asyncio.wait_for(
            asyncio.gather(_read_bounded(process.stdout), _read_bounded(process.stderr)),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        _stop_process_tree()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=5.0)
        return ExecResult(timed_out=True, exit_code=124)
    if overflow.is_set():
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=5.0)
        return ExecResult(
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            exit_code=process.returncode if process.returncode is not None else 137,
            error="sandbox output limit exceeded",
        )
    await process.wait()
    return ExecResult(
        stdout=stdout.decode("utf-8", errors="replace") if stdout else "",
        stderr=stderr.decode("utf-8", errors="replace") if stderr else "",
        exit_code=process.returncode if process.returncode is not None else 0,
    )


__all__ = [
    "BwrapBackend",
    "RestrictedSubprocessBackend",
    "RunnerSidecarBackend",
    "SandboxBackend",
]
