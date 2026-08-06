"""Provider-free strict assertion contract checks."""

from __future__ import annotations

import base64
import json
import time

import pytest

pytest.importorskip("cryptography")
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from deeptutor.integrations.blueway import assertion


def _token(private: Ed25519PrivateKey, **overrides: object) -> str:
    now = int(time.time())
    claims = {
        "iss": "blueway-workspace-api", "aud": "teeechr-workspace-api",
        "scope": "teeechr.workspace.read.v1", "sub": "blueway-subject",
        "client_id": "blueway-client", "authorization_id": "auth-1",
        "external_course_id": "course-1", "external_term_id": "term-1",
        "iat": now, "nbf": now, "exp": now + 120, "jti": "jti-1",
    }
    claims.update(overrides)
    def encode(value: object) -> str:
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=").decode()
    header = encode({"alg": "EdDSA", "kid": "test-key", "typ": "JWT"})
    payload = encode(claims)
    signature = base64.urlsafe_b64encode(private.sign(f"{header}.{payload}".encode())).rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


@pytest.fixture
def keys():
    private = Ed25519PrivateKey.generate()
    assertion.set_test_keys({"test-key": private.public_key()})
    yield private
    assertion.set_test_keys(None)


def test_valid_assertion_is_strictly_verified(keys):
    claims = assertion.verify_assertion(_token(keys), now=time.time())
    assert claims["authorization_id"] == "auth-1"
    assert claims["subject_hash"]


@pytest.mark.parametrize("change", [
    {"iss": "wrong"}, {"aud": "wrong"}, {"scope": "teeechr.workspace.write.v1"},
    {"exp": 1}, {"nbf": time.time() + 10_000}, {"iat": time.time() - 10_000},
    {"jti": ""}, {"external_course_id": ""},
])
def test_assertion_claim_failures_are_fail_closed(keys, change):
    with pytest.raises(assertion.AssertionError):
        assertion.verify_assertion(_token(keys, **change))


def test_wrong_key_and_altered_signature_fail(keys):
    token = _token(keys)
    other = Ed25519PrivateKey.generate()
    with pytest.raises(assertion.AssertionError):
        assertion.verify_assertion(_token(other))
    parts = token.split(".")
    altered = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
    with pytest.raises(assertion.AssertionError):
        assertion.verify_assertion(".".join((parts[0], altered, parts[2])))


def test_unsigned_and_wrong_algorithm_fail(keys):
    token = _token(keys).split(".")
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "kid": "test-key"}).encode()).rstrip(b"=").decode()
    with pytest.raises(assertion.AssertionError):
        assertion.verify_assertion(f"{header}.{token[1]}.{token[2]}")
