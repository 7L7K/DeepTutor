#!/usr/bin/env python3
"""Fail-closed validator for the hermetic Day 3 school-loop evidence pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from typing import Any
from urllib.parse import urlsplit

ACTORS = ("learner_a", "learner_b")
RESOURCE_KEYS = ("course", "source", "practice", "attempt", "flashcards", "card", "review")
ISOLATION_FAMILIES = (
    "course",
    "source",
    "chat",
    "practice",
    "attempt",
    "result",
    "flashcards",
    "card",
    "review-operation",
)
PRIVILEGED_PREFIXES = (
    "/api/v1/auth/users",
    "/api/v1/multi-user",
    "/api/v1/subagents/settings",
    "/api/v1/admin",
)
LEARNER_SAFE_SETTINGS = {
    "/api/v1/settings",
    "/api/v1/settings/llm-options",
    "/api/v1/settings/chat-attachments",
}
LEARNER_SAFE_STATIC = {
    ("GET", "/api/v1/auth/status"),
    ("GET", "/api/v1/auth/is_first_user"),
    ("POST", "/api/v1/auth/login"),
    ("GET", "/api/v1/system/status"),
    ("GET", "/api/v1/space/mcp/servers"),
    ("GET", "/api/v1/knowledge/list"),
    ("GET", "/api/v1/tools"),
    ("GET", "/api/v1/subagents/consult-settings"),
    ("GET", "/api/v1/subagents/partners"),
    ("GET", "/api/v1/subagents/connections"),
}
LEARNER_COURSE_PATTERNS = tuple(
    (method, re.compile(pattern))
    for method, pattern in (
        ("GET", r"^/api/v1/courses$"),
        ("POST", r"^/api/v1/courses$"),
        ("GET", r"^/api/v1/courses/[^/]+$"),
        ("GET", r"^/api/v1/courses/[^/]+/(?:chat-readiness|learning)$"),
        ("GET", r"^/api/v1/courses/[^/]+/sources$"),
        ("POST", r"^/api/v1/courses/[^/]+/sources$"),
        ("GET", r"^/api/v1/courses/[^/]+/sources/[^/]+$"),
        ("GET", r"^/api/v1/courses/[^/]+/practice$"),
        ("POST", r"^/api/v1/courses/[^/]+/practice$"),
        ("GET", r"^/api/v1/courses/[^/]+/practice/[^/]+$"),
        ("POST", r"^/api/v1/courses/[^/]+/practice/[^/]+/revisions$"),
        ("GET", r"^/api/v1/courses/[^/]+/practice/[^/]+/revisions/[^/]+$"),
        ("GET", r"^/api/v1/courses/[^/]+/practice/[^/]+/revisions/[^/]+/questions$"),
        ("POST", r"^/api/v1/courses/[^/]+/practice/[^/]+/revisions/[^/]+/questions$"),
        ("POST", r"^/api/v1/courses/[^/]+/practice/[^/]+/revisions/[^/]+/ready$"),
        ("GET", r"^/api/v1/courses/[^/]+/practice/[^/]+/attempts$"),
        ("POST", r"^/api/v1/courses/[^/]+/practice/[^/]+/attempts$"),
        ("GET", r"^/api/v1/courses/[^/]+/practice/[^/]+/attempts/[^/]+$"),
        ("PATCH", r"^/api/v1/courses/[^/]+/practice/[^/]+/attempts/[^/]+$"),
        ("POST", r"^/api/v1/courses/[^/]+/practice/[^/]+/attempts/[^/]+/(?:submit|grade)$"),
        ("GET", r"^/api/v1/courses/[^/]+/practice/[^/]+/attempts/[^/]+/results$"),
        ("GET", r"^/api/v1/courses/[^/]+/practice-generation$"),
        ("GET", r"^/api/v1/courses/[^/]+/flashcards$"),
        ("POST", r"^/api/v1/courses/[^/]+/flashcards$"),
        ("GET", r"^/api/v1/courses/[^/]+/flashcards/[^/]+$"),
        ("POST", r"^/api/v1/courses/[^/]+/flashcards/[^/]+/cards$"),
        ("PATCH", r"^/api/v1/courses/[^/]+/flashcards/[^/]+/cards/[^/]+$"),
        ("POST", r"^/api/v1/courses/[^/]+/flashcards/[^/]+/ready$"),
        ("GET", r"^/api/v1/courses/[^/]+/flashcards/[^/]+/reviews$"),
        ("POST", r"^/api/v1/courses/[^/]+/flashcards/[^/]+/reviews$"),
        ("GET", r"^/api/v1/courses/[^/]+/flashcard-generation$"),
        ("GET", r"^/api/v1/sessions$"),
        ("GET", r"^/api/v1/sessions/[^/]+$"),
    )
)
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SECRET_PATTERNS = (
    re.compile(rb"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(rb"\bBearer\s+[A-Za-z0-9._~+/-]{16,}\b", re.IGNORECASE),
    re.compile(
        rb"(?:api[_-]?key|authorization)\s*[=:]\s*[\"']?[A-Za-z0-9._~+/-]{16,}", re.IGNORECASE
    ),
)
EXPECTED_HTTP_ORIGINS = ["http://localhost:3823", "http://127.0.0.1:8043"]
EXPECTED_WEBSOCKET_ORIGINS = ["ws://localhost:3823", "ws://127.0.0.1:8043"]


class ValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def safe_regular(path: Path, *, mode: int = 0o600) -> None:
    require(path.exists(), f"missing evidence file: {path.name}")
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode), f"evidence is not a regular file: {path.name}")
    require(not path.is_symlink(), f"evidence is a symlink: {path.name}")
    require(stat.S_IMODE(info.st_mode) == mode, f"unsafe mode on {path.name}")
    require(info.st_nlink == 1, f"hard-linked evidence is forbidden: {path.name}")


def load_json(root: Path, name: str) -> dict[str, Any]:
    path = root / name
    safe_regular(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"invalid JSON evidence: {name}") from exc
    require(isinstance(value, dict), f"JSON evidence must be an object: {name}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def assert_header(value: dict[str, Any], *, phase: str, run_id: str) -> None:
    require(value.get("schemaVersion") == 1, f"{phase} schema mismatch")
    require(value.get("phase") == phase, f"{phase} phase mismatch")
    require(value.get("runId") == run_id, f"{phase} run binding mismatch")


def actor_map(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(value) == set(ACTORS), f"{label} must contain exactly two learners")
    return value


def auth_map(value: Any, usernames: dict[str, str], label: str) -> dict[str, dict[str, Any]]:
    require(isinstance(value, list) and len(value) == 2, f"{label} auth must contain two receipts")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        require(isinstance(item, dict), f"{label} auth receipt malformed")
        actor = item.get("actor")
        require(actor in ACTORS and actor not in result, f"{label} auth actor mismatch")
        require(item.get("username") == usernames[actor], f"{label} username mismatch")
        require(isinstance(item.get("userId"), str) and item["userId"], f"{label} user id empty")
        require(
            item.get("role") == "user" and item.get("isAdmin") is False, f"{label} elevated learner"
        )
        result[actor] = item
    require(
        result[ACTORS[0]]["userId"] != result[ACTORS[1]]["userId"],
        f"{label} learners collapse to one identity",
    )
    return result


def network_origin(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    require(parsed.scheme in {"ws", "wss"} and bool(parsed.netloc), "malformed WebSocket URL")
    return f"{parsed.scheme}://{parsed.netloc}"


def validate_network(document: dict[str, Any], phase: str) -> None:
    require(
        document.get("networkPolicy")
        == {
            "httpOrigins": EXPECTED_HTTP_ORIGINS,
            "websocketOrigins": EXPECTED_WEBSOCKET_ORIGINS,
        },
        f"{phase} network policy drifted",
    )
    for field in (
        "networkViolations",
        "blockedNetworkRequests",
        "networkFailures",
        "websocketViolations",
        "websocketErrors",
    ):
        require(document.get(field) == [], f"{phase} {field} is non-empty")

    cancellations = document.get("teardownCancellations")
    require(isinstance(cancellations, list), f"{phase} teardown cancellation evidence malformed")
    for cancellation in cancellations:
        require(isinstance(cancellation, dict), f"{phase} teardown cancellation malformed")
        require(cancellation.get("actor") in ACTORS, f"{phase} teardown cancellation actor invalid")
        require(
            isinstance(cancellation.get("method"), str),
            f"{phase} teardown cancellation method missing",
        )
        raw_url = cancellation.get("url")
        parsed = urlsplit(raw_url) if isinstance(raw_url, str) else None
        require(
            parsed is not None
            and parsed.scheme in {"http", "https"}
            and f"{parsed.scheme}://{parsed.netloc}" in EXPECTED_HTTP_ORIGINS,
            f"{phase} teardown cancellation escaped local HTTP origins",
        )
        require(
            cancellation.get("failure") == "net::ERR_ABORTED",
            f"{phase} unexpected teardown cancellation failure",
        )

    sockets = document.get("websockets")
    closures = document.get("websocketClosures")
    require(isinstance(sockets, list), f"{phase} WebSocket evidence malformed")
    require(isinstance(closures, list), f"{phase} WebSocket closure evidence malformed")
    for socket in sockets:
        require(isinstance(socket, dict), f"{phase} WebSocket receipt malformed")
        actor = socket.get("actor")
        raw_url = socket.get("url")
        require(actor in ACTORS, f"{phase} WebSocket actor invalid")
        require(isinstance(raw_url, str), f"{phase} WebSocket URL missing")
        require(
            network_origin(raw_url) in EXPECTED_WEBSOCKET_ORIGINS,
            f"{phase} WebSocket escaped local origins",
        )
        require(socket.get("path") == urlsplit(raw_url).path, f"{phase} WebSocket path mismatch")
    for closure in closures:
        require(isinstance(closure, dict), f"{phase} WebSocket closure malformed")
        raw_url = closure.get("url")
        require(closure.get("actor") in ACTORS, f"{phase} WebSocket closure actor invalid")
        require(isinstance(raw_url, str), f"{phase} WebSocket closure URL missing")
        require(
            network_origin(raw_url) in EXPECTED_WEBSOCKET_ORIGINS,
            f"{phase} WebSocket closure escaped local origins",
        )
        require(isinstance(closure.get("code"), int), f"{phase} WebSocket close code missing")
        require(isinstance(closure.get("reason"), str), f"{phase} WebSocket close reason missing")
        require(isinstance(closure.get("wasClean"), bool), f"{phase} WebSocket clean flag missing")
        require(
            closure.get("intentionalShutdown") is True
            or closure.get("wasClean") is True
            or closure.get("code") in (1000, 1001),
            f"{phase} abnormal WebSocket closure",
        )
    if phase == "pre":
        for actor in ACTORS:
            require(
                any(
                    socket.get("actor") == actor and socket.get("path") == "/api/v1/ws"
                    for socket in sockets
                ),
                f"pre {actor} did not observe the expected /api/v1/ws socket",
            )


def validate_requests(
    document: dict[str, Any], phase: str, allowed_404: set[str] | None = None
) -> None:
    requests = document.get("requests")
    require(isinstance(requests, list) and requests, f"{phase} request evidence is empty")
    allowed_404 = allowed_404 or set()
    for item in requests:
        require(isinstance(item, dict), f"{phase} request evidence malformed")
        require(item.get("phase") == phase, f"{phase} request has wrong phase")
        require(item.get("actor") in ACTORS, f"{phase} request actor invalid")
        path = item.get("path")
        require(
            isinstance(path, str) and path.startswith("/api/v1/"), f"{phase} request path invalid"
        )
        require(not item.get("failure"), f"{phase} request failed: {path}")
        status_code = item.get("status")
        require(isinstance(status_code, int), f"{phase} response status missing: {path}")
        method = item.get("method")
        require(isinstance(method, str), f"{phase} request method missing: {path}")
        learner_domain = (
            (method, path) in LEARNER_SAFE_STATIC
            or (method == "GET" and path in LEARNER_SAFE_SETTINGS)
            or any(
                method == allowed_method and pattern.fullmatch(path)
                for allowed_method, pattern in LEARNER_COURSE_PATTERNS
            )
        )
        require(
            learner_domain, f"{phase} API request is outside the learner allowlist: {method} {path}"
        )
        if status_code == 404:
            require(path in allowed_404, f"{phase} unexplained 404: {path}")
        else:
            require(
                status_code in (200, 201, 202, 204),
                f"{phase} unexpected non-success status {status_code}: {path}",
            )
        require(
            not any(path.startswith(prefix) for prefix in PRIVILEGED_PREFIXES),
            f"{phase} privileged API request: {path}",
        )
        if path.startswith("/api/v1/settings"):
            require(
                method == "GET" and path in LEARNER_SAFE_SETTINGS,
                f"{phase} non-learner settings request: {path}",
            )
    require(document.get("consoleErrors") == [], f"{phase} browser console errors")
    require(document.get("pageErrors") == [], f"{phase} browser page errors")
    expected_logins = 2 if phase == "pre" else 1
    for actor in ACTORS:
        login_count = sum(
            item.get("actor") == actor
            and item.get("method") == "POST"
            and item.get("path") == "/api/v1/auth/login"
            and item.get("status") == 200
            for item in requests
        )
        require(
            login_count == expected_logins,
            f"{phase} {actor} observed login count is not {expected_logins}",
        )
    validate_network(document, phase)


def validate_provider(document: dict[str, Any], expected: bool, label: str) -> None:
    require(document.get("schemaVersion") == 1, f"{label} schema mismatch")
    require(
        document.get("deterministicProvider") is expected, f"{label} deterministic mode mismatch"
    )
    require(document.get("paidProviderEnabled") is False, f"{label} paid provider enabled")
    require(
        document.get("paidCredentialConfigured") is False, f"{label} paid credential configured"
    )
    require(document.get("pocketbaseEnabled") is False, f"{label} PocketBase enabled")
    require(
        document.get("llmBoundaryProfile") == "llm-profile-day3-local",
        f"{label} LLM boundary profile drifted",
    )
    require(
        document.get("llmBoundaryModel") == "llm-model-day3-local",
        f"{label} LLM boundary model drifted",
    )
    require(
        document.get("llmBoundaryBaseUrl") == "http://127.0.0.1:1/v1",
        f"{label} LLM fallback is not closed loopback",
    )
    require(
        document.get("llmBoundaryProvider") == "ollama",
        f"{label} LLM fallback provider is not local",
    )
    require(
        document.get("llmBoundaryCredentialConfigured") is False,
        f"{label} LLM fallback has a credential",
    )
    require(document.get("reservationRows") == 0, f"{label} provider ledger is non-empty")
    usage = document.get("usage")
    require(isinstance(usage, dict), f"{label} usage receipt missing")
    for key in (
        "settled_cost_microusd",
        "reserved_or_uncertain_cost_microusd",
        "admitted_cost_microusd",
    ):
        require(usage.get(key) == 0, f"{label} provider cost is non-zero")
    if expected:
        require(
            document.get("practiceProvider") == "DeterministicPracticeGenerationProvider",
            "practice provider is not deterministic",
        )
        require(
            document.get("flashcardProvider") == "DeterministicFlashcardGenerationProvider",
            "flashcard provider is not deterministic",
        )


def validate_runtime_provider_db(runtime_root: Path, evidence_dir: Path) -> None:
    root = runtime_root.resolve(strict=True)
    require(
        root.name.startswith("teeechr-d3-runtime."), "runtime root is not a Day 3 disposable root"
    )
    require(not runtime_root.is_symlink(), "runtime root is a symlink")
    databases = list(root.rglob("provider_usage.db"))
    require(len(databases) == 1, "provider usage ledger path is ambiguous")
    database = databases[0]
    require(
        database.resolve(strict=True).is_relative_to(root), "provider ledger escaped runtime root"
    )
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        policy = connection.execute(
            "SELECT enabled FROM provider_usage_policy WHERE singleton=1"
        ).fetchone()
        reservation = connection.execute(
            """SELECT COUNT(*),
                      COALESCE(SUM(reserved_cost_microusd),0),
                      COALESCE(SUM(estimated_cost_microusd),0)
                 FROM provider_usage_reservations"""
        ).fetchone()
    require(policy == (0,), "paid provider ledger policy is enabled")
    require(reservation == (0, 0, 0), "provider reservation or cost ledger is non-zero")
    atomic_json(
        evidence_dir / "provider.final.json",
        {
            "schemaVersion": 1,
            "paidProviderEnabled": False,
            "reservationRows": 0,
            "reservedCostMicrousd": 0,
            "estimatedCostMicrousd": 0,
        },
    )


def secret_scan(evidence_dir: Path, run_id: str) -> None:
    exact = [
        os.environ.get("D3_EXPECTED_SECRET_ADMIN", ""),
        os.environ.get("D3_EXPECTED_SECRET_A", ""),
        os.environ.get("D3_EXPECTED_SECRET_B", ""),
    ]
    require(all(exact), "expected secret probes were not supplied")
    exact_bytes = [value.encode("utf-8") for value in exact]
    private_markers = [f"private-{actor}-{run_id}".encode("utf-8") for actor in ACTORS]
    for path in evidence_dir.rglob("*"):
        if path.is_dir():
            continue
        require(path.is_file() and not path.is_symlink(), f"unsafe evidence entry: {path.name}")
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValidationError(f"evidence file too large to scan: {path.name}")
        content = path.read_bytes()
        require(
            not any(secret in content for secret in exact_bytes),
            f"credential leaked into {path.name}",
        )
        require(
            not any(marker in content for marker in private_markers),
            f"private learner marker leaked into {path.name}",
        )
        require(
            not any(pattern.search(content) for pattern in SECRET_PATTERNS),
            f"provider secret pattern in {path.name}",
        )


def validate_pre_cleanup(arguments: argparse.Namespace) -> None:
    evidence_dir = Path(arguments.evidence_dir)
    runtime_root = Path(arguments.runtime_root)
    require(evidence_dir.is_dir() and not evidence_dir.is_symlink(), "evidence directory is unsafe")
    require(
        stat.S_IMODE(evidence_dir.stat().st_mode) == 0o700, "evidence directory mode is not 700"
    )
    require(
        not (evidence_dir / "day3-school-loop.complete").exists(),
        "completion sentinel exists before cleanup",
    )
    usernames = {"learner_a": arguments.learner_a, "learner_b": arguments.learner_b}

    provider_off = load_json(evidence_dir, "provider.off.json")
    provider_pre = load_json(evidence_dir, "provider.pre.json")
    repair = load_json(evidence_dir, "day3-school-loop.repair.json")
    pre = load_json(evidence_dir, "day3-school-loop.pre.json")
    interrupted = load_json(evidence_dir, "day3-school-loop.interrupt.json")
    post = load_json(evidence_dir, "day3-school-loop.post.json")
    validate_provider(provider_off, False, "provider-off")
    validate_provider(provider_pre, True, "provider-pre")
    for document, phase in (
        (repair, "repair"),
        (pre, "pre"),
        (interrupted, "interrupt"),
        (post, "post"),
    ):
        assert_header(document, phase=phase, run_id=arguments.run_id)
        require(
            document.get("concurrentContexts") is True, f"{phase} did not use concurrent contexts"
        )

    repair_auth = auth_map(repair.get("auth"), usernames, "repair")
    pre_auth = auth_map(pre.get("auth"), usernames, "pre")
    post_auth = auth_map(post.get("auth"), usernames, "post")
    interrupt_auth = auth_map(interrupted.get("auth"), usernames, "interrupt")
    for actor in ACTORS:
        require(
            repair_auth[actor]["userId"]
            == pre_auth[actor]["userId"]
            == interrupt_auth[actor]["userId"]
            == post_auth[actor]["userId"],
            f"{actor} identity changed across phases",
        )

    courses = actor_map(repair.get("courses"), "repair courses")
    require(
        courses["learner_a"].get("id") != courses["learner_b"].get("id"),
        "repair Courses are not isolated",
    )
    require(
        isinstance(courses["learner_a"].get("manualPracticeSetId"), str)
        and courses["learner_a"]["manualPracticeSetId"],
        "manual Practice UI did not create a resource",
    )
    for actor in ACTORS:
        study = courses[actor].get("study")
        require(isinstance(study, dict), f"{actor} provider-off manual study receipt missing")
        require(
            study.get("generationCounts") == {"practice": 0, "flashcards": 0},
            f"{actor} provider-off study allocated generation",
        )
        require(
            study.get("generationCapabilities")
            == {
                "practice_generation": False,
                "flashcard_generation": False,
                "grounded_generation": False,
            },
            f"{actor} provider-off generation capability was available",
        )
        practice = study.get("practice")
        flashcards = study.get("flashcards")
        require(
            isinstance(practice, dict) and isinstance(flashcards, dict),
            f"{actor} manual study malformed",
        )
        require(
            practice.get("state") == "graded"
            and practice.get("autosaveStatus") == 200
            and practice.get("reloadPersisted") is True
            and practice.get("submitStatus") == 200
            and practice.get("gradeStatus") == 200
            and practice.get("resultsStatus") == 200
            and practice.get("browserResults") is True,
            f"{actor} provider-off Practice lifecycle incomplete",
        )
        require(
            flashcards.get("state") == "ready"
            and flashcards.get("reviewCount") == 1
            and flashcards.get("reviewId") == flashcards.get("lastReviewId")
            and flashcards.get("reviewedPreRestart") is True
            and flashcards.get("browserReview") is True,
            f"{actor} provider-off Flashcard review incomplete",
        )
    require(
        repair.get("uiProofs")
        == {
            "manualPracticeDraftEditor": True,
            "nonReadyChatBanner": {"learner_a": True, "learner_b": True},
            "chatShellPresent": {"learner_a": True, "learner_b": True},
            "learnerSafeNavigation": {"learner_a": True, "learner_b": True},
        },
        "UI repair proof flags are incomplete",
    )
    require(
        repair.get("authoringBoundary")
        == {
            "courseCreation": "browser-ui",
            "practiceDraftEntry": "browser-ui",
            "practiceQuestionAuthoring": "authenticated-course-api",
            "flashcardDeckCardAuthoring": "authenticated-course-api",
            "practiceAttemptLifecycle": "browser-ui",
            "flashcardReview": "browser-ui",
        },
        "manual authoring proof boundary is missing or overstated",
    )

    resources = actor_map(pre.get("resources"), "pre resources")
    identifiers: dict[str, list[str]] = {key: [] for key in RESOURCE_KEYS}
    for actor in ACTORS:
        item = resources[actor]
        require(isinstance(item, dict), f"{actor} resources malformed")
        require(
            item.get("actor") == actor and item.get("username") == usernames[actor],
            f"{actor} resource owner mismatch",
        )
        require(
            item.get("userId") == pre_auth[actor]["userId"], f"{actor} resource identity mismatch"
        )
        course = item.get("course")
        source = item.get("source")
        chat = item.get("chat")
        practice = item.get("practice")
        flashcards = item.get("flashcards")
        for value, label in (
            (course, "course"),
            (source, "source"),
            (chat, "chat"),
            (practice, "practice"),
            (flashcards, "flashcards"),
        ):
            require(isinstance(value, dict), f"{actor} {label} receipt malformed")
        require(course.get("id") == courses[actor].get("id"), f"{actor} Course binding changed")
        require(
            course.get("writeEpoch") == courses[actor]["study"].get("courseWriteEpoch"),
            f"{actor} Course epoch was not provider-off bound",
        )
        require(
            practice == courses[actor]["study"]["practice"],
            f"{actor} Practice resource was not the provider-off receipt",
        )
        require(
            flashcards == courses[actor]["study"]["flashcards"],
            f"{actor} Flashcard resource was not the provider-off receipt",
        )
        require(
            course.get("title") == "Day 3 Shared Biology"
            and isinstance(course.get("writeEpoch"), int),
            f"{actor} Course projection invalid",
        )
        require(
            source.get("state") == "ready" and source.get("displayName") == "shared-day3-notes.txt",
            f"{actor} source not ready",
        )
        source_id = source.get("id")
        require(isinstance(source_id, str) and source_id, f"{actor} source ID is empty")
        require(
            source.get("contentSha256") == source.get("manifestFingerprint"),
            f"{actor} source digest mismatch",
        )
        require(
            all(
                HASH_RE.fullmatch(str(source.get(key, "")))
                for key in ("contentSha256", "fileSha256", "manifestFingerprint")
            ),
            f"{actor} source hashes malformed",
        )
        require(
            isinstance(chat.get("sessionId"), str) and chat.get("sessionId"),
            f"{actor} chat session is empty",
        )
        require(
            chat.get("groundedCitationSourceId") == source.get("id"),
            f"{actor} chat citation is not source-bound",
        )
        require(
            chat.get("terminalProvider") == "deterministic-local",
            f"{actor} chat did not terminate through deterministic provider",
        )
        expected_marker_hash = hashlib.sha256(
            f"private-{actor}-{arguments.run_id}".encode("utf-8")
        ).hexdigest()
        expected_source_bytes = (
            f"Synthetic Day 3 material for private-{actor}-{arguments.run_id}.\n"
        ).encode("utf-8")
        expected_file_hash = hashlib.sha256(expected_source_bytes).hexdigest()
        expected_manifest = json.dumps(
            [
                {
                    "path": f"{source_id}/shared-day3-notes.txt",
                    "sha256": expected_file_hash,
                    "size": len(expected_source_bytes),
                }
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected_content_hash = hashlib.sha256(expected_manifest).hexdigest()
        require(
            source.get("fileSha256") == expected_file_hash,
            f"{actor} source file hash is not marker-bound",
        )
        require(
            source.get("contentSha256") == expected_content_hash,
            f"{actor} source manifest hash is not marker-bound",
        )
        require(practice.get("state") == "graded", f"{actor} Practice attempt state invalid")
        require(
            practice.get("answerSha256") == expected_marker_hash,
            f"{actor} Practice answer binding invalid",
        )
        require(
            flashcards.get("state") == "ready" and flashcards.get("reviewedPreRestart") is True,
            f"{actor} Flashcards state invalid",
        )
        require(
            flashcards.get("reviewId") == flashcards.get("lastReviewId"),
            f"{actor} review schedule binding invalid",
        )
        require(
            chat.get("foreignMarkerAbsent") is True
            and chat.get("foreignSourceAbsent") is True
            and chat.get("foreignCitationAbsent") is True,
            f"{actor} Chat foreign-content rejection missing",
        )
        require(
            item.get("privateMarkerSha256") == expected_marker_hash, f"{actor} marker hash invalid"
        )
        identifiers["course"].append(str(course.get("id", "")))
        identifiers["source"].append(str(source.get("id", "")))
        identifiers["practice"].append(str(practice.get("setId", "")))
        identifiers["attempt"].append(str(practice.get("attemptId", "")))
        identifiers["flashcards"].append(str(flashcards.get("deckId", "")))
        identifiers["card"].append(str(flashcards.get("cardId", "")))
        identifiers["review"].append(str(flashcards.get("reviewId", "")))
        require(all(identifiers[key][-1] for key in RESOURCE_KEYS), f"{actor} resource ID is empty")
    for key, values in identifiers.items():
        require(len(set(values)) == 2, f"{key} resources are not isolated")
    require(
        resources["learner_a"]["privateMarkerSha256"]
        != resources["learner_b"]["privateMarkerSha256"],
        "private markers collapse",
    )
    require(
        resources["learner_a"]["chat"]["sessionId"] != resources["learner_b"]["chat"]["sessionId"],
        "chat sessions are not isolated",
    )
    require(
        resources["learner_a"]["source"]["fileSha256"]
        != resources["learner_b"]["source"]["fileSha256"],
        "source files are not byte-distinct",
    )
    require(
        resources["learner_a"]["source"]["contentSha256"]
        != resources["learner_b"]["source"]["contentSha256"],
        "source content digests are not distinct",
    )

    interrupted_sources = actor_map(interrupted.get("sources"), "interrupted sources")
    for actor in ACTORS:
        receipt = interrupted_sources[actor]
        expected_interrupted_hash = hashlib.sha256(
            f"Interrupted synthetic material for {actor} {arguments.run_id}.\n".encode("utf-8")
        ).hexdigest()
        require(
            isinstance(receipt, dict)
            and receipt.get("courseId") == resources[actor]["course"]["id"]
            and receipt.get("state") == "processing"
            and isinstance(receipt.get("id"), str)
            and HASH_RE.fullmatch(str(receipt.get("fileSha256", ""))) is not None,
            f"{actor} interrupted source receipt invalid",
        )
        require(
            receipt.get("fileSha256") == expected_interrupted_hash,
            f"{actor} interrupted source hash drifted",
        )
    require(
        interrupted_sources["learner_a"]["id"] != interrupted_sources["learner_b"]["id"],
        "interrupted source IDs collapse",
    )
    require(
        interrupted_sources["learner_a"]["fileSha256"]
        != interrupted_sources["learner_b"]["fileSha256"],
        "interrupted source bytes collapse",
    )

    for document, label in ((pre, "pre"), (post, "post")):
        counts = actor_map(document.get("generationOperationCounts"), f"{label} operation counts")
        require(
            all(counts[actor] == {"practice": 0, "flashcards": 0} for actor in ACTORS),
            f"{label} used generated study resources",
        )

    require(post.get("coldRestartProjection") is True, "post proof is not bound to cold restart")
    persistence = actor_map(post.get("persistence"), "post persistence")
    expected_persistence = {
        "course": True,
        "source": True,
        "chat": True,
        "chatForeignContentAbsent": True,
        "practice": True,
        "attempt": True,
        "flashcards": True,
        "review": True,
        "interruptedSourceFailed": True,
        "browserMaterials": True,
        "browserOverview": True,
        "browserPractice": True,
        "browserResults": True,
        "browserFlashcards": True,
        "browserReviewReload": True,
    }
    require(
        all(persistence[actor] == expected_persistence for actor in ACTORS),
        "post-restart projection is incomplete",
    )
    reviews = actor_map(post.get("reviewPersistence"), "review persistence")
    require(
        all(
            reviews[actor].get("reviewId") == resources[actor]["flashcards"]["reviewId"]
            and reviews[actor].get("reviewCount") == 1
            and reviews[actor].get("scheduleLastReviewId") == reviews[actor].get("reviewId")
            and reviews[actor].get("ownerScoped") is True
            for actor in ACTORS
        ),
        "post-restart review persistence failed",
    )
    require(
        reviews["learner_a"]["reviewId"] != reviews["learner_b"]["reviewId"],
        "review IDs are not isolated",
    )
    require(
        post.get("reviewIdLookupBoundary") == "not-externally-addressable",
        "review-ID lookup boundary omitted",
    )
    failed_sources = actor_map(post.get("interruptedSources"), "post interrupted sources")
    for actor in ACTORS:
        require(
            failed_sources[actor]
            == {
                "id": interrupted_sources[actor]["id"],
                "stateBeforeRestart": "processing",
                "stateAfterRestart": "failed",
                "browserFailed": True,
            },
            f"{actor} interrupted source did not fail closed",
        )

    isolation = actor_map(post.get("isolation"), "post isolation")
    allowed_404: set[str] = set()
    for actor in ACTORS:
        rows = isolation[actor]
        require(
            isinstance(rows, list) and len(rows) == len(ISOLATION_FAMILIES),
            f"{actor} isolation matrix incomplete",
        )
        require(
            {row.get("family") for row in rows if isinstance(row, dict)} == set(ISOLATION_FAMILIES),
            f"{actor} isolation families incomplete",
        )
        for row in rows:
            require(isinstance(row, dict), f"{actor} isolation row malformed")
            require(
                row.get("foreignStatus") == 404
                and row.get("missingStatus") == 404
                and row.get("bodiesEqual") is True,
                f"{actor} foreign/missing oracle mismatch",
            )
            require(
                row.get("body")
                in (
                    {"detail": "Course resource not found"},
                    {"detail": "Practice resource not found"},
                    {"detail": "Session not found"},
                ),
                f"{actor} not-found body drifted",
            )
            allowed_404.add(str(row.get("foreignPath")))
            allowed_404.add(str(row.get("missingPath")))

    validate_requests(repair, "repair")
    validate_requests(pre, "pre")
    validate_requests(interrupted, "interrupt")
    validate_requests(post, "post", allowed_404)
    validate_runtime_provider_db(runtime_root, evidence_dir)
    secret_scan(evidence_dir, arguments.run_id)
    atomic_json(
        evidence_dir / "precleanup.validation.json",
        {
            "schemaVersion": 1,
            "runId": arguments.run_id,
            "status": "accepted",
            "twoLearners": True,
            "uiRepairs": True,
            "providerLedgerZero": True,
            "coldRestartPersistence": True,
            "foreignMissingNonOracle": True,
            "practiceLifecycle": True,
            "flashcardReviewPersistence": True,
            "interruptedSourceFailClosed": True,
            "reviewIdLookupBoundary": "not-externally-addressable",
        },
    )


def parse_runtime(path: Path) -> dict[str, str]:
    safe_regular(path)
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        require("=" in line, "runtime evidence contains an unstructured line")
        key, value = line.split("=", 1)
        require(key and key not in values, f"runtime evidence key repeated: {key}")
        values[key] = value
    return values


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_final(arguments: argparse.Namespace) -> None:
    evidence_dir = Path(arguments.evidence_dir)
    require(evidence_dir.is_dir() and not evidence_dir.is_symlink(), "evidence directory is unsafe")
    require(
        stat.S_IMODE(evidence_dir.stat().st_mode) == 0o700, "evidence directory mode is not 700"
    )
    sentinel = evidence_dir / "day3-school-loop.complete"
    require(not sentinel.exists(), "wrapper sentinel exists before final validation")
    prevalidation = load_json(evidence_dir, "precleanup.validation.json")
    require(
        prevalidation
        == {
            "schemaVersion": 1,
            "runId": arguments.run_id,
            "status": "accepted",
            "twoLearners": True,
            "uiRepairs": True,
            "providerLedgerZero": True,
            "coldRestartPersistence": True,
            "foreignMissingNonOracle": True,
            "practiceLifecycle": True,
            "flashcardReviewPersistence": True,
            "interruptedSourceFailClosed": True,
            "reviewIdLookupBoundary": "not-externally-addressable",
        },
        "pre-cleanup validation receipt mismatch",
    )
    runtime = parse_runtime(evidence_dir / "runtime.txt")
    require(runtime.get("run_id") == arguments.run_id, "runtime run binding mismatch")
    require(runtime.get("source_worktree") == "clean", "source worktree was not clean at start")
    require(runtime.get("source_end_worktree") == "clean", "source worktree was not clean at end")
    require(
        runtime.get("source_cleanup_worktree") == "clean",
        "source worktree was not clean after cleanup",
    )
    require(runtime.get("source_head") == runtime.get("source_end_head"), "source HEAD changed")
    require(
        runtime.get("source_branch") == runtime.get("source_end_branch"), "source branch changed"
    )
    require(
        runtime.get("source_worktree") == runtime.get("source_end_worktree"),
        "source worktree state changed",
    )
    require(
        runtime.get("source_tree_digest") == runtime.get("source_end_tree_digest"),
        "source tree digest changed",
    )
    require(
        runtime.get("source_head") == runtime.get("source_cleanup_head"),
        "source HEAD changed during cleanup",
    )
    require(
        runtime.get("source_branch") == runtime.get("source_cleanup_branch"),
        "source branch changed during cleanup",
    )
    require(
        runtime.get("source_worktree") == runtime.get("source_cleanup_worktree"),
        "source worktree state changed during cleanup",
    )
    require(
        runtime.get("source_tree_digest") == runtime.get("source_cleanup_tree_digest"),
        "source tree digest changed during cleanup",
    )
    require(
        HASH_RE.fullmatch(runtime.get("source_tree_digest", "")) is not None,
        "source tree digest malformed",
    )
    expected_runtime = {
        "process_environment": "allowlisted",
        "process_overrides": "ignored",
        "pocketbase": "disabled",
        "paid_provider": "disabled",
        "playwright_output": "runtime-owned",
        "playwright_repo_output_start": "absent",
        "playwright_repo_output_end": "absent",
        "ui_repair_provider_mode": "off",
        "ui_repair_transition_groups": "closed",
        "school_loop_provider_mode": "deterministic-local",
        "cold_restart_pre_frontend_group": "closed",
        "cold_restart_pre_backend_group": "closed",
        "cold_restart_interrupt_frontend_group": "closed",
        "cold_restart_interrupt_backend_group": "closed",
        "cleanup_process_groups": "closed",
        "cleanup_frontend_port": "closed",
        "cleanup_backend_port": "closed",
        "cleanup_runtime_root": "removed",
        "cleanup_status": "closed",
    }
    for key, value in expected_runtime.items():
        require(runtime.get(key) == value, f"runtime proof missing: {key}={value}")
    secret_scan(evidence_dir, arguments.run_id)

    core_names = (
        "provider.off.json",
        "provider.pre.json",
        "provider.final.json",
        "day3-school-loop.repair.json",
        "day3-school-loop.pre.json",
        "day3-school-loop.interrupt.json",
        "day3-school-loop.post.json",
        "precleanup.validation.json",
        "runtime.txt",
    )
    log_names = (
        "backend.repair.log",
        "frontend.repair.log",
        "playwright-repair.log",
        "backend.pre.log",
        "frontend.pre.log",
        "playwright-pre.log",
        "backend.interrupt.log",
        "frontend.interrupt.log",
        "playwright-interrupt.log",
        "backend.post.log",
        "frontend.post.log",
        "playwright-post.log",
        "playwright.post.log",
    )
    require(
        {path.name for path in evidence_dir.glob("*.log")} == set(log_names),
        "retained log set is incomplete or contains an unbound log",
    )
    files: dict[str, dict[str, Any]] = {}
    for name in (*core_names, *log_names):
        path = evidence_dir / name
        safe_regular(path)
        files[name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    atomic_json(
        evidence_dir / "manifest.json",
        {
            "schemaVersion": 1,
            "proof": "day3-school-loop",
            "runId": arguments.run_id,
            "sourceHead": runtime["source_head"],
            "sourceTreeDigest": runtime["source_tree_digest"],
            "cleanupStatus": "closed",
            "providerLedger": "zero",
            "twoLearnerIsolation": "accepted",
            "practiceLifecycle": "accepted",
            "flashcardReviewPersistence": "accepted",
            "interruptedSourceFailClosed": "accepted",
            "reviewIdLookupBoundary": "not-externally-addressable",
            "retainedLogs": list(log_names),
            "files": files,
        },
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("phase", choices=("pre-cleanup", "final"))
    result.add_argument("--evidence-dir", required=True)
    result.add_argument("--runtime-root")
    result.add_argument("--run-id", required=True)
    result.add_argument("--learner-a", required=True)
    result.add_argument("--learner-b", required=True)
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        if arguments.phase == "pre-cleanup":
            require(bool(arguments.runtime_root), "--runtime-root is required before cleanup")
            validate_pre_cleanup(arguments)
        else:
            require(
                arguments.runtime_root is None,
                "final validation must not receive the deleted runtime root",
            )
            validate_final(arguments)
    except (ValidationError, OSError, sqlite3.Error) as exc:
        print(f"Day 3 evidence rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
