"""Privacy-safe diagnostics for browser login attempts.

The public authentication response deliberately stays generic.  This module
emits only a bounded server-side event so an operator can distinguish a
misspelled identifier from a password mismatch without logging credentials or
other authentication material.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
import math
import re
import secrets
import time
from typing import Callable, Literal

logger = logging.getLogger("deeptutor.auth")

_ATTEMPT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SAFE_REQUEST_ID_RE = re.compile(r"^req_[a-f0-9]{32}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PLAIN_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
_HMAC_DOMAIN = b"teeechr-auth-identifier-v1\x00"
_REQUEST_ID_HMAC_DOMAIN = b"teeechr-auth-request-id-v1\x00"
_PROCESS_DIAGNOSTIC_KEY = secrets.token_bytes(32)

IdentifierKind = Literal["email", "plain_username", "invalid"]
LookupResult = Literal["exact", "casefold", "none"]
AccountState = Literal["active", "disabled", "unknown"]
PasswordResult = Literal["match", "mismatch", "not_checked"]
AuthMode = Literal["standard", "pocketbase"]
AuthOutcome = Literal[
    "success",
    "invalid_credentials",
    "disabled",
    "provider_failure",
    "rate_limited",
    "validation_failure",
]


@dataclass(frozen=True)
class IdentifierDetails:
    """Safe, non-secret representation of a submitted login identifier."""

    kind: IdentifierKind
    normalized: str
    masked: str
    fingerprint: str | None


class LoginFailureLimiter:
    """Small, process-local guard against repeated credential guesses.

    The limiter deliberately stores only the existing HMAC identifier
    fingerprint, never a submitted username, password, or client address.
    It is intentionally process-local: the beta runs as one application
    process, and a distributed limiter would add operational state to the
    authentication boundary.  The bounded key count prevents arbitrary
    identifier submissions from growing memory without limit.
    """

    def __init__(
        self,
        *,
        max_failures: int = 5,
        window_seconds: float = 300.0,
        max_keys: int = 4096,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._max_failures = max_failures
        self._window_seconds = window_seconds
        self._max_keys = max_keys
        self._clock = clock or time.monotonic
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()

    def retry_after_seconds(self, identifier_hmac: str | None) -> int | None:
        """Return a bounded retry delay when another login should be rejected."""
        if not identifier_hmac:
            return None
        attempts = self._failures.get(identifier_hmac)
        if attempts is None:
            return None
        now = self._clock()
        self._discard_expired(attempts, now)
        if not attempts:
            self._failures.pop(identifier_hmac, None)
            return None
        self._failures.move_to_end(identifier_hmac)
        if len(attempts) < self._max_failures:
            return None
        return max(1, math.ceil(attempts[0] + self._window_seconds - now))

    def reserve_attempt(self, identifier_hmac: str | None) -> None:
        """Reserve a login-work slot before a credential check begins.

        A successful login clears its reservation. Reserving before the async
        worker is started prevents a simultaneous burst from passing the
        limiter check and consuming unbounded bcrypt work.
        """
        if not identifier_hmac:
            return
        now = self._clock()
        attempts = self._failures.get(identifier_hmac)
        if attempts is None:
            if len(self._failures) >= self._max_keys:
                self._failures.popitem(last=False)
            attempts = deque()
            self._failures[identifier_hmac] = attempts
        self._discard_expired(attempts, now)
        attempts.append(now)
        self._failures.move_to_end(identifier_hmac)

    def clear(self, identifier_hmac: str | None) -> None:
        """Clear a successful identifier's local failure history."""
        if identifier_hmac:
            self._failures.pop(identifier_hmac, None)

    def _discard_expired(self, attempts: deque[float], now: float) -> None:
        while attempts and now - attempts[0] >= self._window_seconds:
            attempts.popleft()


def resolve_attempt_id() -> str:
    """Create a fresh random identifier safe to return in an HTTP header."""
    return f"auth_{secrets.token_hex(16)}"


def attempt_id_is_valid(value: str) -> bool:
    """Expose the same narrow contract used for caller-supplied request ids."""
    return bool(_ATTEMPT_ID_RE.fullmatch(value))


def validated_request_id(
    value: str | None,
    *,
    auth_secret: str | bytes | None = None,
) -> str | None:
    """Return a non-reversible server reference for a bounded request id.

    The caller may provide a correlation id, but its raw value must never be
    copied into an authentication log. HMAC keeps valid references stable for
    hosted log correlation while preventing token-like or password-like input
    from crossing the logging boundary.
    """
    if not value or not _ATTEMPT_ID_RE.fullmatch(value):
        return None
    digest = hmac.new(
        _diagnostic_key(auth_secret),
        _REQUEST_ID_HMAC_DOMAIN + value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"req_{digest[:32]}"


def classify_client(user_agent: str | None) -> str:
    """Reduce a browser user-agent to a coarse diagnostic class."""
    value = (user_agent or "").lower()
    if "iphone" in value and "safari" in value and "crios" not in value:
        return "iphone-safari"
    if "ipad" in value and "safari" in value and "crios" not in value:
        return "ipad-safari"
    if "android" in value:
        return "android-browser"
    if "macintosh" in value and "safari" in value and "chrome" not in value:
        return "desktop-safari"
    if "windows" in value and "chrome" in value:
        return "desktop-chrome"
    return "other"


def _mask_identifier(value: str, kind: IdentifierKind) -> str:
    if kind == "email":
        local, domain = value.split("@", 1)
        return f"{local[:1]}***@{domain.casefold()}"
    if kind == "plain_username":
        return f"{value[:1]}***"
    return "<invalid>"


def _diagnostic_key(auth_secret: str | bytes | None) -> bytes:
    """Use the deployment auth secret; keep a process fallback for provider mode."""
    if isinstance(auth_secret, bytes) and auth_secret:
        return auth_secret
    if isinstance(auth_secret, str) and auth_secret:
        return auth_secret.encode("utf-8")
    return _PROCESS_DIAGNOSTIC_KEY


def identifier_details(
    value: str | None, *, auth_secret: str | bytes | None = None
) -> IdentifierDetails:
    """Classify an identifier and derive only safe diagnostic representations."""
    submitted = value.strip() if isinstance(value, str) else ""
    if _EMAIL_RE.fullmatch(submitted):
        kind: IdentifierKind = "email"
        normalized = submitted.casefold()
    elif _PLAIN_USERNAME_RE.fullmatch(submitted):
        kind = "plain_username"
        normalized = submitted
    else:
        kind = "invalid"
        normalized = ""

    fingerprint = None
    if normalized:
        fingerprint = hmac.new(
            _diagnostic_key(auth_secret),
            _HMAC_DOMAIN + kind.encode("ascii") + b":" + normalized.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    return IdentifierDetails(
        kind=kind,
        normalized=normalized,
        masked=_mask_identifier(submitted, kind),
        fingerprint=fingerprint,
    )


def emit_auth_attempt(
    *,
    attempt_id: str,
    request_id: str | None = None,
    username: str | None,
    user_agent: str | None,
    auth_secret: str | bytes | None,
    lookup: LookupResult,
    account_state: AccountState,
    password_result: PasswordResult,
    auth_mode: AuthMode,
    outcome: AuthOutcome,
) -> dict[str, object]:
    """Emit one bounded JSON event and return the exact safe event for tests."""
    details = identifier_details(username, auth_secret=auth_secret)
    safe_request_id = (
        request_id
        if request_id and _SAFE_REQUEST_ID_RE.fullmatch(request_id)
        else validated_request_id(request_id, auth_secret=auth_secret)
    )
    event: dict[str, object] = {
        "event": "auth_login_attempt",
        "attempt_id": attempt_id,
        "request_id": safe_request_id or attempt_id,
        "client": classify_client(user_agent),
        "identifier_kind": details.kind,
        "identifier_masked": details.masked,
        "identifier_hmac": details.fingerprint,
        "lookup": lookup,
        "account_state": account_state,
        "password_result": password_result,
        "auth_mode": auth_mode,
        "outcome": outcome,
    }
    # Authentication diagnostics are mandatory audit events.  The hosted
    # runtime intentionally runs the root logger at WARNING, so INFO would
    # silently suppress the event while leaving the public response unchanged.
    logger.warning(
        "auth_login_attempt %s",
        json.dumps(event, sort_keys=True, separators=(",", ":")),
    )
    return event


def auth_attempt_headers(attempt_id: str) -> dict[str, str]:
    """Return the only diagnostic value allowed across the HTTP boundary."""
    return {"X-Auth-Attempt-ID": attempt_id}
