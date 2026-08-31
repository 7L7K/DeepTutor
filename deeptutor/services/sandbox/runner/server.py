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

  ``GET  /health`` -> 200, any body, means alive.
  ``POST /exec``   -> request/response JSON described by the dataclasses in
                      :mod:`deeptutor.services.sandbox.spec`. Request::

      {
        "command": "str",                 # shell string; used when argv is absent
        "argv": ["str", ...],             # optional; when present, run WITHOUT a shell
        "workdir": "str | null",          # path inside the container
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
  shell metacharacters cannot matter. A runner image predating this field simply
  ignores it and runs the shell string, which is why both are sent — during a
  rolling deploy either image may be the one serving the request.

Mounts note:
  This server does **not** perform any mounting. The runner container shares
  the task-workspace subtrees with the main app at the *same* paths
  (``/app/data/user/workspace`` for the admin scope, ``/app/data/users`` for
  per-user scopes — via docker-compose). So when ``host_path == sandbox_path``
  the directory is already visible here and no action is needed. We only
  read/record the ``mounts`` field; what is visible is decided by the compose
  volume layout, and ``workdir`` is validated against the same roots
  (``DEEPTUTOR_RUNNER_ALLOWED_WORKDIRS``) as defence in depth.
"""

from __future__ import annotations

import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import resource
import selectors
import signal
import subprocess
import sys
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

    return _apply


# Workdirs must stay inside the shared workspace volumes (defence in depth:
# the app only ever sends task-workspace paths; a request outside them means
# a bug or a forged request). Colon-separated, overridable per deployment.
_ALLOWED_WORKDIR_ROOTS = [
    root
    for root in os.environ.get(
        "DEEPTUTOR_RUNNER_ALLOWED_WORKDIRS",
        "/app/data/user/workspace:/app/data/users",
    ).split(":")
    if root
]


def _workdir_violation(workdir: str) -> str:
    """Return a rejection reason, or '' when *workdir* is acceptable."""
    resolved = os.path.realpath(workdir)
    for root in _ALLOWED_WORKDIR_ROOTS:
        root_real = os.path.realpath(root)
        if resolved == root_real or resolved.startswith(root_real + os.sep):
            return ""
    return (
        f"workdir {workdir!r} is outside the shared workspace roots "
        f"({':'.join(_ALLOWED_WORKDIR_ROOTS)}); refusing to execute"
    )


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one command described by *payload* and return the response dict.

    Never raises for command-level failures (those land in ``exit_code`` /
    ``stderr``); only the runner's own failures populate ``error``.
    """
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
    if workdir is not None and not isinstance(workdir, str):
        return _error_result("'workdir' must be a string or null")
    if workdir is not None:
        reason = _workdir_violation(workdir)
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
    except (OSError, ValueError) as exc:
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

    if timed_out:
        return bytes(buffers["stdout"]), bytes(buffers["stderr"]), True, False, 124
    if output_limited:
        # Preserve the historical command-level contract: an output cap is a
        # successful, truncated result rather than a provider/tool failure.
        return bytes(buffers["stdout"]), bytes(buffers["stderr"]), False, True, 0
    return bytes(buffers["stdout"]), bytes(buffers["stderr"]), False, False, process.returncode or 0


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
    """Minimal request router for ``GET /health`` and ``POST /exec``."""

    # Quiet the default per-request stderr logging; keep it terse and on stdout
    # so container logs stay readable.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        sys.stdout.write("runner: " + (format % args) + "\n")

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
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
        if self.path.rstrip("/") != "/exec":
            self._send_json(404, _error_result("not found"))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
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

        try:
            result = execute(payload)
        except Exception as exc:  # noqa: BLE001 - last-resort guard
            # Any unexpected runner crash becomes a clean error response rather
            # than a dropped connection, so the client degrades gracefully.
            traceback.print_exc()
            result = _error_result(f"runner crashed: {type(exc).__name__}: {exc}")
        self._send_json(200, result)


def main() -> None:
    """Start the threaded HTTP server, binding 0.0.0.0:$RUNNER_PORT."""
    try:
        port = int(os.environ.get("RUNNER_PORT", "") or DEFAULT_PORT)
    except ValueError:
        port = DEFAULT_PORT
    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
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
