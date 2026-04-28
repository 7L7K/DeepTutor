"""Private tester access-code identity helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

from deeptutor.services.session import SQLiteSessionStore, get_sqlite_session_store


ACCESS_COOKIE_NAME = os.getenv("DEEPTUTOR_ACCESS_COOKIE_NAME", "deeptutor_tester")
ACCESS_COOKIE_MAX_AGE_SECONDS = int(
    os.getenv("DEEPTUTOR_ACCESS_COOKIE_MAX_AGE_SECONDS", str(60 * 60 * 24 * 60))
)
ACCESS_HASH_ITERATIONS = int(os.getenv("DEEPTUTOR_ACCESS_HASH_ITERATIONS", "210000"))


class AccessError(Exception):
    """Base access error."""


class InvalidAccessCode(AccessError):
    """The submitted access code did not match any enabled tester."""


class InvalidAccessToken(AccessError):
    """The signed tester cookie is absent, invalid, expired, or disabled."""


def _secret() -> bytes:
    value = os.getenv("DEEPTUTOR_ACCESS_SECRET", "").strip()
    if not value:
        value = "local-dev-access-secret-change-before-deploy"
    return value.encode("utf-8")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def normalize_access_code(code: str) -> str:
    return str(code or "").strip()


def hash_access_code(code: str, salt: str | None = None) -> str:
    normalized = normalize_access_code(code)
    if not normalized:
        raise ValueError("access code is required")
    resolved_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        normalized.encode("utf-8"),
        resolved_salt.encode("utf-8"),
        ACCESS_HASH_ITERATIONS,
    )
    return f"pbkdf2_sha256${ACCESS_HASH_ITERATIONS}${resolved_salt}${digest.hex()}"


def verify_access_code(code: str, stored_hash: str) -> bool:
    normalized = normalize_access_code(code)
    parts = str(stored_hash or "").split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        iterations = int(parts[1])
    except ValueError:
        return False
    salt = parts[2]
    expected = parts[3]
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        normalized.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(digest, expected)


def sign_access_token(tester_id: str, max_age_seconds: int = ACCESS_COOKIE_MAX_AGE_SECONDS) -> str:
    now = int(time.time())
    payload = {
        "tester_id": tester_id,
        "iat": now,
        "exp": now + int(max_age_seconds),
    }
    encoded_payload = _b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(_secret(), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{_b64encode(signature)}"


def parse_access_token(token: str) -> dict[str, Any]:
    if not token or "." not in token:
        raise InvalidAccessToken("Missing access token")
    encoded_payload, encoded_signature = token.split(".", 1)
    expected_signature = _b64encode(
        hmac.new(_secret(), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(encoded_signature, expected_signature):
        raise InvalidAccessToken("Invalid access token signature")
    try:
        payload = json.loads(_b64decode(encoded_payload).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidAccessToken("Invalid access token payload") from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise InvalidAccessToken("Access token expired")
    tester_id = str(payload.get("tester_id") or "").strip()
    if not tester_id:
        raise InvalidAccessToken("Access token missing tester id")
    return payload


@dataclass
class AccessManager:
    store: SQLiteSessionStore

    async def claim_code(self, code: str) -> dict[str, Any]:
        normalized = normalize_access_code(code)
        if not normalized:
            raise InvalidAccessCode("Access code is required")
        for tester in await self.store.list_testers_for_access():
            if tester.get("disabled"):
                continue
            if verify_access_code(normalized, str(tester.get("code_hash") or "")):
                touched = await self.store.touch_tester_seen(str(tester["id"]))
                if not touched or touched.get("disabled"):
                    raise InvalidAccessToken("Tester is disabled")
                return touched
        raise InvalidAccessCode("Invalid access code")

    async def get_tester_from_token(self, token: str) -> dict[str, Any]:
        payload = parse_access_token(token)
        tester = await self.store.get_tester(str(payload["tester_id"]))
        if not tester or tester.get("disabled"):
            raise InvalidAccessToken("Tester is unavailable")
        return tester


def get_access_manager() -> AccessManager:
    return AccessManager(get_sqlite_session_store())
