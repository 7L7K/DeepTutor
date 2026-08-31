"""Sandbox runner sidecar HTTP server (standard-library only).

This process runs *inside* the dedicated ``sandbox-runner`` container and is the
only place where untrusted shell commands are actually executed. The main app
never runs them itself; it submits work here over HTTP
(:class:`deeptutor.services.sandbox.backends.RunnerSidecarBackend`).

Design constraints:
  * No third-party deps (no FastAPI/Flask): the runner image must stay tiny and
    free of heavy frameworks. We use :mod:`http.server` directly.
  * Defence in depth: the container already drops privileges (non-root
    ``runner`` user, ``cap_drop: ALL``, ``no-new-privileges``, read-only rootfs
    — see ``Dockerfile.runner`` / ``docker-compose.yml``). On top of that we
    apply per-command resource limits via :func:`resource.setrlimit`.

Wire contract (must match ``RunnerSidecarBackend``):

  ``GET  /health`` -> 200, any body, means alive (unauthenticated for the
                      container liveness probe).
  ``GET  /capabilities`` -> authenticated protocol/version handshake.
  ``POST /v2/exec``   -> request/response JSON described by the dataclasses in
                      :mod:`deeptutor.services.sandbox.spec`. Requires
                      ``Authorization: Bearer $DEEPTUTOR_SANDBOX_RUNNER_TOKEN``.
                      Request::

      {
        "command": "str",                 # shell string; used when argv is absent
        "argv": ["str", ...],             # optional; when present, run WITHOUT a shell
        "workdir": "str | null",          # path inside the container
        "principal_root": "str",          # authenticated workspace boundary
        "env": {"K": "V"},
        "mounts": [{"host_path": "...",     # informational only (see below)
                    "sandbox_path": "...",
                    "read_only": true}],
        "limits": {"timeout_s": 30, "memory_mb": 512,
                   "cpu_seconds": 30, "max_output_chars": 10000}
      }

  Response::

      {"stdout": "...", "stderr": "...", "exit_code": 0,
       "timed_out": false, "error": ""}

  ``error`` is non-empty *only* when the runner itself failed (bad JSON,
  spawn error, ...), never merely because the command exited non-zero.

Argv note:
  The app sends ``command`` and ``argv`` together and they describe the same
  execution (``command == shlex.join(argv)``). ``argv`` wins here, so a caller
  that assembles arguments from model output runs with no shell in the path and
  shell metacharacters cannot matter. The versioned endpoint is deliberate: a
  runner image from before the authenticated principal-boundary contract only
  knows ``/exec`` and returns 404 without executing a request. App and runner
  must be rolled out as one protocol-compatible pair.

Principal and mounts note:
  This server does **not** perform any mounting. The runner container shares
  the admin task-workspace subtree with the main app at the same path. The app
  binds each authenticated request to a narrow ``principal_root`` and the
  runner validates ``workdir`` and writable mounts beneath it. The deployment
  allowlist is ``DEEPTUTOR_RUNNER_ALLOWED_PRINCIPAL_ROOTS``. A broad per-user
  tree is intentionally not mounted because path validation cannot confine an
  arbitrary child process after it starts.
"""

from __future__ import annotations

import contextlib
import ctypes
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import resource
import selectors
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
from typing import Any, cast

logger = logging.getLogger(__name__)

# Port to listen on inside the container; overridable for local testing.
DEFAULT_PORT = 8900

# Hard cap on the request body we are willing to read, to avoid a hostile or
# buggy caller exhausting memory before we even parse the command.
_MAX_REQUEST_BYTES = 4 * 1024 * 1024

# Fallback ceilings used when the caller omits a limit (mirrors
# ResourceLimits defaults in spec.py).
_DEFAULT_TIMEOUT_S = 30
_DEFAULT_MEMORY_MB = 512
_DEFAULT_CPU_SECONDS = 30
_DEFAULT_MAX_OUTPUT_CHARS = 10_000

# Per-request ceilings are deliberately stricter than the container's cgroup
# limits. A caller must not turn a valid request into an unbounded wait,
# allocation, or output buffer by supplying a large positive integer.
_MAX_TIMEOUT_S = 300
_MAX_MEMORY_MB = 1_024
_MAX_CPU_SECONDS = 300
_MAX_OUTPUT_CHARS = 1_000_000

# Generous file-descriptor ceiling: high enough for normal tooling (git, build
# steps), low enough to bound a runaway fd leak.
_RLIMIT_NOFILE = 4096
# Keep the per-command process ceiling below the runner container's cgroup
# ``pids_limit`` (256), but leave enough headroom for the Python runtime and
# normal child-process fan-out. Linux enforces RLIMIT_NPROC per real UID; a
# value of 64 is below the effective UID quota in some hosted/container user
# namespaces and can make even the first ``/bin/sh`` fork fail with EAGAIN.
# The local fallback deliberately does not apply this UID-global limit because
# it shares the application's UID and would starve unrelated app/test workers.
_RLIMIT_NPROC = 128
_RLIMIT_FSIZE_BYTES = 256 * 1024 * 1024


def _positive_env_int(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except ValueError:
        value = default
    return min(max(1, value), maximum)


# Authenticate execution requests from the application container. Health stays
# unauthenticated so Docker can probe it without distributing the credential to
# a second command surface. An empty token never degrades to open access.
_RUNNER_TOKEN = os.environ.get("DEEPTUTOR_SANDBOX_RUNNER_TOKEN", "").strip()
# Keep these values in sync with deeptutor.services.sandbox.spec. The runner
# image intentionally copies only this stdlib module, so it cannot import that
# application-side module at runtime.
_RUNNER_PROTOCOL_VERSION = 2
_RUNNER_EXEC_PATH = "/v2/exec"
_RUNNER_CAPABILITIES_PATH = "/capabilities"
_RUNNER_CAPABILITIES = (
    "authorization",
    "principal_root",
    "argv",
    "bounded_execution",
)
_EXEC_UID = _positive_env_int("DEEPTUTOR_RUNNER_EXEC_UID", 1000, 65_535)
_EXEC_GID = _positive_env_int("DEEPTUTOR_RUNNER_EXEC_GID", 1000, 65_535)


def _authorization_valid(value: str) -> bool:
    scheme, separator, credential = value.partition(" ")
    return bool(
        _RUNNER_TOKEN
        and separator
        and scheme.lower() == "bearer"
        and hmac.compare_digest(credential, _RUNNER_TOKEN)
    )


def _configure_server_process() -> None:
    """Protect credentials and adopt escaped descendants on Linux.

    The image runs tini and this server as root with only SETUID, SETGID, and
    KILL capabilities; each command drops to the unprivileged runner identity.
    That separation keeps the bearer out of child-readable procfs. The server
    is also a child subreaper so a descendant that calls setsid/daemonizes is
    adopted here and can be killed before the sole execution slot is released.
    """
    if not _RUNNER_TOKEN:
        raise RuntimeError("DEEPTUTOR_SANDBOX_RUNNER_TOKEN is required")
    if not sys.platform.startswith("linux"):
        return
    if os.geteuid() != 0 or _EXEC_UID == 0:
        raise RuntimeError("Linux runner server must be root and commands must use a non-root uid")
    libc = ctypes.CDLL(None, use_errno=True)
    pr_set_dumpable = 4
    pr_set_child_subreaper = 36
    if libc.prctl(pr_set_dumpable, 0, 0, 0, 0) != 0:
        errno = ctypes.get_errno()
        raise RuntimeError(f"could not protect runner credential memory (errno={errno})")
    if libc.prctl(pr_set_child_subreaper, 1, 0, 0, 0) != 0:
        errno = ctypes.get_errno()
        raise RuntimeError(f"could not configure runner child reaping (errno={errno})")


# One job at a time makes every orphan adopted by the subreaper attributable to
# that job. Per-user concurrency still exists at the application layer; this
# sidecar is deliberately a narrow serialized security boundary.
_MAX_CONCURRENT_EXECUTIONS = 1
_EXECUTION_SLOTS = threading.BoundedSemaphore(_MAX_CONCURRENT_EXECUTIONS)
_MAX_CONNECTIONS = 16
_CONNECTION_SLOTS = threading.BoundedSemaphore(_MAX_CONNECTIONS)
_REQUEST_IO_TIMEOUT_S = 10.0

# POSIX-only: setrlimit / preexec_fn are not available on Windows. The runner
# always ships in a Linux container, but guard so the module stays importable
# (e.g. for syntax checks / unit tests) on any platform.
_POSIX = os.name == "posix"


def _truncate_head_tail(text: str, max_chars: int) -> str:
    """Cap *text* to *max_chars*, keeping the head and tail (eliding the middle).

    Matches the head+tail style used by ``ExecResult.render`` so the most
    useful context (start of output and final error lines) survives.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    half = max_chars // 2
    dropped = len(text) - max_chars
    return text[:half] + f"\n\n... ({dropped:,} chars truncated) ...\n\n" + text[-half:]


def _build_preexec_fn(memory_mb: int, cpu_seconds: int):
    """Return a ``preexec_fn`` that applies rlimits in the forked child (POSIX).

    The closure runs after ``fork`` and before ``exec`` in the child process,
    so the limits apply to the command and everything it spawns. Returns
    ``None`` on non-POSIX platforms (no rlimit support there).

    Notes on portability:
      * ``RLIMIT_AS`` (address space) is the most portable memory cap but it
        bounds *virtual* memory, not RSS. Some runtimes (notably the JVM, and
        occasionally glibc/threaded allocators) reserve large virtual ranges
        and may fail under a tight ``RLIMIT_AS`` even with low real usage. The
        compose ``mem_limit`` (cgroup-enforced RSS) is the authoritative
        backstop; this rlimit is a cheap secondary guard.
      * ``RLIMIT_CPU`` counts CPU seconds, not wall-clock; wall-clock is
        enforced separately via ``subprocess`` ``timeout``.
    """
    if not _POSIX:
        return None

    def _apply() -> None:
        # Address space (bytes). Cap virtual memory as a secondary guard.
        if memory_mb > 0:
            mem_bytes = memory_mb * 1024 * 1024
            try:
                resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            except (ValueError, OSError):
                pass
        # CPU time (seconds). SIGXCPU/SIGKILL the child if it burns this much CPU.
        if cpu_seconds > 0:
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            except (ValueError, OSError):
                pass
        # Open file descriptors.
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (_RLIMIT_NOFILE, _RLIMIT_NOFILE))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(
                resource.RLIMIT_FSIZE,
                (_RLIMIT_FSIZE_BYTES, _RLIMIT_FSIZE_BYTES),
            )
        except (AttributeError, ValueError, OSError):
            pass
        if sys.platform.startswith("linux"):
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (_RLIMIT_NPROC, _RLIMIT_NPROC))
            except (AttributeError, ValueError, OSError):
                pass
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (AttributeError, ValueError, OSError):
            pass
        if sys.platform.startswith("linux") and os.geteuid() == 0:
            # Drop every supplementary group before changing real/effective
            # gid and uid. The command cannot recover the server's credentials
            # or signal/read the root-owned tini/server processes afterward.
            os.setgroups([])
            os.setgid(_EXEC_GID)
            os.setuid(_EXEC_UID)

    return _apply


# Workdirs must stay inside the shared workspace volumes (defence in depth:
# the app only ever sends task-workspace paths; a request outside them means
# a bug or a forged request). Colon-separated, overridable per deployment.
_ALLOWED_PRINCIPAL_ROOTS = [
    root
    for root in os.environ.get(
        "DEEPTUTOR_RUNNER_ALLOWED_PRINCIPAL_ROOTS",
        "/app/data/user/workspace",
    ).split(":")
    if root
]

_ALLOWED_READ_ONLY_ROOTS = [
    root
    for root in os.environ.get(
        "DEEPTUTOR_RUNNER_ALLOWED_READ_ONLY_ROOTS",
        "/app/data/cli-apps",
    ).split(":")
    if root
]


def _path_within(path: str, root: str) -> bool:
    resolved = os.path.realpath(path)
    root_real = os.path.realpath(root)
    return resolved == root_real or resolved.startswith(root_real + os.sep)


def _principal_root(payload: dict[str, Any]) -> tuple[str, str]:
    """Resolve and validate the app-authenticated workspace boundary."""
    raw = payload.get("principal_root")
    if not isinstance(raw, str) or not raw or not os.path.isabs(raw):
        return "", "missing or invalid 'principal_root'"
    resolved = os.path.realpath(raw)
    if not any(_path_within(resolved, root) for root in _ALLOWED_PRINCIPAL_ROOTS):
        return "", "principal_root is outside the deployment allowlist"
    return resolved, ""


def _workdir_violation(workdir: str, principal_root: str) -> str:
    """Return a rejection reason, or '' when *workdir* is acceptable."""
    if not os.path.isabs(workdir) or not _path_within(workdir, principal_root):
        return "workdir is outside the authenticated principal_root; refusing to execute"
    return ""


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one command described by *payload* and return the response dict.

    Never raises for command-level failures (those land in ``exit_code`` /
    ``stderr``); only the runner's own failures populate ``error``.
    """
    principal_root, principal_error = _principal_root(payload)
    if principal_error:
        return _error_result(principal_error)

    command = payload.get("command")
    if not isinstance(command, str) or not command:
        return _error_result("missing or empty 'command'")

    raw_argv = payload.get("argv") or []
    if not isinstance(raw_argv, list):
        return _error_result("'argv' must be a list of strings")
    if any(not isinstance(item, str) for item in raw_argv):
        return _error_result("'argv' must be a list of strings")
    argv: list[str] = list(raw_argv)

    workdir = payload.get("workdir") or None
    if not isinstance(workdir, str) or not workdir:
        return _error_result("'workdir' must be a non-empty absolute path")
    reason = _workdir_violation(workdir, principal_root)
    if reason:
        return _error_result(reason)

    # Build the child environment. The caller's env fully replaces ours except
    # for PATH, which we always provide so basic tooling resolves even if the
    # caller sends an empty env.
    raw_env = payload.get("env") or {}
    if not isinstance(raw_env, dict):
        return _error_result("'env' must be an object")
    env: dict[str, str] = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}
    for key, value in raw_env.items():
        env[str(key)] = str(value)

    # Mounts are informational here — the compose volume layout does the real
    # work (see module docstring). We only validate the shape so a malformed
    # request fails loudly rather than silently.
    mounts = payload.get("mounts") or []
    if not isinstance(mounts, list):
        return _error_result("'mounts' must be a list")
    for mount in mounts:
        if not isinstance(mount, dict):
            return _error_result("each mount must be an object")
        sandbox_path = mount.get("sandbox_path")
        read_only = mount.get("read_only")
        if not isinstance(sandbox_path, str) or not os.path.isabs(sandbox_path):
            return _error_result("mount sandbox_path must be an absolute path")
        if not isinstance(read_only, bool):
            return _error_result("mount read_only must be a boolean")
        if read_only:
            allowed = _path_within(sandbox_path, principal_root) or any(
                _path_within(sandbox_path, root) for root in _ALLOWED_READ_ONLY_ROOTS
            )
        else:
            allowed = _path_within(sandbox_path, principal_root)
        if not allowed:
            return _error_result("mount is outside the authenticated principal boundary")

    limits = payload.get("limits") or {}
    if not isinstance(limits, dict):
        return _error_result("'limits' must be an object")
    timeout_s = _bounded_int(limits.get("timeout_s"), _DEFAULT_TIMEOUT_S, _MAX_TIMEOUT_S)
    memory_mb = _bounded_int(limits.get("memory_mb"), _DEFAULT_MEMORY_MB, _MAX_MEMORY_MB)
    cpu_seconds = _bounded_int(limits.get("cpu_seconds"), _DEFAULT_CPU_SECONDS, _MAX_CPU_SECONDS)
    max_output_chars = _bounded_int(
        limits.get("max_output_chars"), _DEFAULT_MAX_OUTPUT_CHARS, _MAX_OUTPUT_CHARS
    )

    preexec_fn = _build_preexec_fn(memory_mb, cpu_seconds)

    try:
        stdout_bytes, stderr_bytes, timed_out, output_limited, returncode = _run_bounded_process(
            argv or command,
            # A shell string is the legacy runner contract; argv requests take
            # the no-shell branch above. nosec B602,B604.
            shell=not argv,  # nosec B602,B604
            cwd=workdir,
            env=env,
            timeout_s=timeout_s,
            max_output_chars=max_output_chars,
            preexec_fn=preexec_fn,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # Spawn failure (bad cwd, exec error, ...) — a runner-level problem.
        return _error_result(f"{type(exc).__name__}: {exc}")

    stdout = _decode(stdout_bytes)
    stderr = _decode(stderr_bytes)
    if output_limited:
        logger.debug("sandbox command output exceeded %s characters", max_output_chars)
    if timed_out:
        return {
            "stdout": _truncate_head_tail(stdout, max_output_chars),
            "stderr": _truncate_head_tail(stderr, max_output_chars),
            "exit_code": 124,  # conventional "timed out" exit status
            "timed_out": True,
            "error": "",
        }

    return {
        "stdout": _truncate_head_tail(stdout, max_output_chars),
        "stderr": _truncate_head_tail(stderr, max_output_chars),
        "exit_code": returncode,
        "timed_out": False,
        "error": "",
    }


def _run_bounded_process(
    command: str | list[str],
    *,
    shell: bool,
    cwd: str | None,
    env: dict[str, str],
    timeout_s: int,
    max_output_chars: int,
    preexec_fn: Any,
) -> tuple[bytes, bytes, bool, bool, int]:
    """Run a child while bounding both pipe buffers and wall-clock time."""
    max_bytes = max(1, max_output_chars) * 4
    process = subprocess.Popen(  # nosec B602 — shell=True is the runner contract
        command,
        shell=shell,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=preexec_fn,
        # A dedicated session makes the command's PID its process-group ID.
        # Timeout/output enforcement can then stop the command and ordinary
        # descendants together instead of leaving background jobs running.
        start_new_session=_POSIX,
    )
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    buffers: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    timed_out = False
    output_limited = False
    deadline = time.monotonic() + max(1, timeout_s)

    def stop_child() -> None:
        if _POSIX:
            with contextlib.suppress(ProcessLookupError, OSError):
                os.killpg(process.pid, signal.SIGKILL)
                return
        with contextlib.suppress(ProcessLookupError):
            process.kill()

    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                stop_child()
                break
            for key, _ in selector.select(min(remaining, 0.25)):
                stream = cast(Any, key.fileobj)
                label = key.data
                chunk = os.read(stream.fileno(), min(64 * 1024, max_bytes + 1))
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                room = max_bytes - len(buffers[label])
                if len(chunk) > room:
                    buffers[label].extend(chunk[: max(0, room)])
                    output_limited = True
                    stop_child()
                    # Closing the parent read ends lets a child that ignores
                    # SIGTERM receive SIGPIPE instead of keeping this loop
                    # alive while unbounded output is produced.
                    for pending in list(selector.get_map().values()):
                        pending_stream = cast(Any, pending.fileobj)
                        selector.unregister(pending_stream)
                        pending_stream.close()
                    break
                buffers[label].extend(chunk)
            if output_limited or timed_out:
                break
    finally:
        if timed_out or output_limited:
            stop_child()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        selector.close()
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        _terminate_adopted_children()

    if timed_out:
        return bytes(buffers["stdout"]), bytes(buffers["stderr"]), True, False, 124
    if output_limited:
        # Preserve the historical command-level contract: an output cap is a
        # successful, truncated result rather than a provider/tool failure.
        return bytes(buffers["stdout"]), bytes(buffers["stderr"]), False, True, 0
    return bytes(buffers["stdout"]), bytes(buffers["stderr"]), False, False, process.returncode or 0


def _direct_child_pids() -> list[int]:
    """Return Linux processes currently parented to this subreaper."""
    if not sys.platform.startswith("linux"):
        return []
    children: list[int] = []
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            with open(f"/proc/{entry.name}/status", encoding="utf-8") as handle:
                parent_line = next(line for line in handle if line.startswith("PPid:"))
            if int(parent_line.split()[1]) == os.getpid():
                children.append(int(entry.name))
        except (FileNotFoundError, PermissionError, StopIteration, ValueError, OSError):
            continue
    return children


def _terminate_adopted_children() -> None:
    """Kill and reap descendants that escaped the command's process group."""
    if not sys.platform.startswith("linux"):
        return
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        children = _direct_child_pids()
        for pid in children:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)
        while True:
            try:
                waited, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if waited == 0:
                break
        if not _direct_child_pids():
            return
        time.sleep(0.01)
    raise OSError("runner could not terminate all adopted command descendants")


def _decode(value: Any) -> str:
    """Coerce captured stream output (str | bytes | None) to str."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _int(value: Any, default: int) -> int:
    """Best-effort int coercion with a fallback (never raises)."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default


def _bounded_int(value: Any, default: int, maximum: int) -> int:
    """Coerce a positive integer and clamp it to a server-side ceiling."""
    return min(_int(value, default), maximum)


def _error_result(message: str) -> dict[str, Any]:
    """Build a response where only the runner-level ``error`` field is set."""
    return {
        "stdout": "",
        "stderr": "",
        "exit_code": 0,
        "timed_out": False,
        "error": message,
    }


class _Handler(BaseHTTPRequestHandler):
    """Minimal request router for health, capabilities, and versioned exec."""

    # Quiet the default per-request stderr logging; keep it terse and on stdout
    # so container logs stay readable.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        sys.stdout.write("runner: " + (format % args) + "\n")

    def _send_json(
        self,
        status: int,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        if self.path.rstrip("/") == _RUNNER_CAPABILITIES_PATH:
            if not _authorization_valid(self.headers.get("Authorization", "")):
                self._send_json(
                    401,
                    _error_result("unauthorized"),
                    headers={"WWW-Authenticate": "Bearer"},
                )
                return
            self._send_json(
                200,
                {
                    "protocol_version": _RUNNER_PROTOCOL_VERSION,
                    "capabilities": list(_RUNNER_CAPABILITIES),
                },
                headers={"X-DeepTutor-Runner-Protocol": str(_RUNNER_PROTOCOL_VERSION)},
            )
            return
        if self.path.rstrip("/") == "/health" or self.path == "/":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send_json(404, _error_result("not found"))

    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        if self.path.rstrip("/") != _RUNNER_EXEC_PATH:
            self._send_json(404, _error_result("not found"))
            return
        if not _authorization_valid(self.headers.get("Authorization", "")):
            self._send_json(
                401,
                _error_result("unauthorized"),
                headers={"WWW-Authenticate": "Bearer"},
            )
            return
        if not _EXECUTION_SLOTS.acquire(blocking=False):
            self._send_json(429, _error_result("runner execution capacity exhausted"))
            return
        try:
            self._handle_exec()
        finally:
            _EXECUTION_SLOTS.release()

    def _handle_exec(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, _error_result("invalid Content-Length"))
            return
        if length < 0:
            self._send_json(400, _error_result("invalid Content-Length"))
            return
        if length > _MAX_REQUEST_BYTES:
            self._send_json(413, _error_result("request body too large"))
            return
        try:
            raw = self.rfile.read(length) if length > 0 else b""
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
        except (ValueError, UnicodeDecodeError) as exc:
            self._send_json(400, _error_result(f"invalid JSON: {exc}"))
            return
        except (TimeoutError, socket.timeout, OSError):
            self._send_json(408, _error_result("request body read timed out"))
            return

        try:
            result = execute(payload)
        except Exception as exc:  # noqa: BLE001 - last-resort guard
            # Any unexpected runner crash becomes a clean error response rather
            # than a dropped connection, so the client degrades gracefully.
            traceback.print_exc()
            result = _error_result(f"runner crashed: {type(exc).__name__}: {exc}")
        self._send_json(200, result)


class _RunnerHTTPServer(ThreadingHTTPServer):
    """Bounded threaded server with deadlines before handler allocation."""

    daemon_threads = True
    block_on_close = False
    request_queue_size = 64

    def get_request(self):  # noqa: ANN201
        request, address = super().get_request()
        request.settimeout(_REQUEST_IO_TIMEOUT_S)
        return request, address

    def process_request(self, request, client_address) -> None:  # noqa: ANN001
        if not _CONNECTION_SLOTS.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            _CONNECTION_SLOTS.release()
            raise

    def process_request_thread(self, request, client_address) -> None:  # noqa: ANN001
        try:
            super().process_request_thread(request, client_address)
        finally:
            _CONNECTION_SLOTS.release()


def main() -> None:
    """Start the threaded HTTP server, binding 0.0.0.0:$RUNNER_PORT."""
    try:
        port = int(os.environ.get("RUNNER_PORT", "") or DEFAULT_PORT)
    except ValueError:
        port = DEFAULT_PORT
    _configure_server_process()
    server = _RunnerHTTPServer(("0.0.0.0", port), _Handler)
    sys.stdout.write(f"runner: listening on 0.0.0.0:{port}\n")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
