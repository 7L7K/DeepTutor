"""Privacy-safe diagnostics for browser login attempts.

The public authentication response deliberately stays generic.  This module
emits only a bounded server-side event so an operator can distinguish a
misspelled identifier from a password mismatch without logging credentials or
other authentication material.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
import re
import secrets
from typing import Literal


logger = logging.getLogger("deeptutor.auth")

_ATTEMPT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PLAIN_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
_HMAC_DOMAIN = b"teeechr-auth-identifier-v1\x00"
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
    "validation_failure",
]


@dataclass(frozen=True)
class IdentifierDetails:
    """Safe, non-secret representation of a submitted login identifier."""

    kind: IdentifierKind
    normalized: str
    masked: str
    fingerprint: str | None


def resolve_attempt_id() -> str:
    """Create a fresh random identifier safe to return in an HTTP header."""
    return f"auth_{secrets.token_hex(16)}"


def attempt_id_is_valid(value: str) -> bool:
    """Expose the same narrow contract used for caller-supplied request ids."""
    return bool(_ATTEMPT_ID_RE.fullmatch(value))


def validated_request_id(value: str | None) -> str | None:
    """Keep only a bounded caller request id for server-side correlation."""
    return value if value and _ATTEMPT_ID_RE.fullmatch(value) else None


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


def identifier_details(value: str | None, *, auth_secret: str | bytes | None = None) -> IdentifierDetails:
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
    event: dict[str, object] = {
        "event": "auth_login_attempt",
        "attempt_id": attempt_id,
        "request_id": request_id or attempt_id,
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
