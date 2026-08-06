"""Strict Ed25519/JWS assertions for the BlueWay workspace read contract.

BlueWay sends a short-lived signed assertion, never a TEEECHR bearer or
refresh token.  The accepted compact JWS is fixed to EdDSA, a configured
``kid``, issuer, audience ``teeechr-workspace-api``, and the exact scope
``teeechr.workspace.read.v1``.  ``sub``, ``client_id``, ``authorization_id``,
and ``external_course_id`` are required; ``external_term_id`` is optional.
Production keys are configured with ``TEEECHR_BLUEWAY_WORKSPACE_KEYS`` as a
JSON object of kid -> base64url raw Ed25519 public key. Tests may inject a key
set with :func:`set_test_keys`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import time
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

AUDIENCE = "teeechr-workspace-api"
SCOPE = "teeechr.workspace.read.v1"
_test_keys: dict[str, Ed25519PublicKey] | None = None


class AssertionError(ValueError):
    """Raised for every malformed, unauthorized, or stale assertion."""


def set_test_keys(keys: dict[str, Ed25519PublicKey] | None) -> None:
    global _test_keys
    _test_keys = keys


def _b64(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise AssertionError("Invalid assertion encoding")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise AssertionError("Invalid assertion encoding") from exc


def _keys() -> dict[str, Ed25519PublicKey]:
    if _test_keys is not None:
        return _test_keys
    try:
        raw = json.loads(os.environ.get("TEEECHR_BLUEWAY_WORKSPACE_KEYS", "{}"))
        if not isinstance(raw, dict):
            raise ValueError
        return {str(k): Ed25519PublicKey.from_public_bytes(_b64(v)) for k, v in raw.items()}
    except (ValueError, TypeError, KeyError, binascii.Error) as exc:
        raise AssertionError("Workspace assertion keys are unavailable") from exc


def verify_assertion(token: str, *, now: float | None = None) -> dict[str, Any]:
    if not isinstance(token, str) or token.count(".") != 2:
        raise AssertionError("Malformed workspace assertion")
    encoded_header, encoded_payload, encoded_signature = token.split(".")
    try:
        header = json.loads(_b64(encoded_header))
        claims = json.loads(_b64(encoded_payload))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssertionError("Malformed workspace assertion") from exc
    if not isinstance(header, dict) or header.get("alg") != "EdDSA" or not isinstance(header.get("kid"), str):
        raise AssertionError("Unsupported workspace assertion algorithm")
    key = _keys().get(header["kid"])
    if key is None:
        raise AssertionError("Unknown workspace assertion key")
    try:
        key.verify(_b64(encoded_signature), f"{encoded_header}.{encoded_payload}".encode("ascii"))
    except Exception as exc:  # cryptography intentionally exposes several signature errors.
        raise AssertionError("Invalid workspace assertion signature") from exc
    if not isinstance(claims, dict):
        raise AssertionError("Invalid workspace assertion claims")
    issuer = str(os.environ.get("TEEECHR_BLUEWAY_WORKSPACE_ISSUER", "blueway-workspace-api"))
    if claims.get("iss") != issuer or claims.get("aud") != AUDIENCE or claims.get("scope") != SCOPE:
        raise AssertionError("Workspace assertion context is invalid")
    required = ("sub", "client_id", "authorization_id", "external_course_id", "iat", "nbf", "exp", "jti")
    if any(not isinstance(claims.get(name), str) or not claims[name] for name in required[:4] + ("jti",)):
        raise AssertionError("Workspace assertion identity is incomplete")
    if "external_term_id" in claims and claims["external_term_id"] is not None and not isinstance(claims["external_term_id"], str):
        raise AssertionError("Workspace assertion term is invalid")
    current = time.time() if now is None else now
    numeric = {name: claims.get(name) for name in ("iat", "nbf", "exp")}
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in numeric.values() if value is not None):
        raise AssertionError("Workspace assertion time claims are invalid")
    if claims["exp"] <= current or claims["iat"] > current + 30 or (claims.get("nbf") is not None and claims["nbf"] > current + 30):
        raise AssertionError("Workspace assertion is not currently valid")
    max_age = float(os.environ.get("TEEECHR_BLUEWAY_WORKSPACE_ASSERTION_MAX_AGE", "300"))
    if current - claims["iat"] > max_age:
        raise AssertionError("Workspace assertion is too old")
    claims["subject_hash"] = hashlib.sha256(claims["sub"].encode("utf-8")).hexdigest()
    return claims
