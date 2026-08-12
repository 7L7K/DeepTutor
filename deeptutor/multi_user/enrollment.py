"""Shared-code enrollment authority for the single-host TEEECHR beta.

The module intentionally keeps provisional state out of the identity store.
An enrollment journal authorizes one exact grant-first write for one reserved
immutable user id; the active identity is published only after that grant is
durable and fingerprint-bound.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import secrets
import threading
import time
from typing import Any
from uuid import uuid4

from deeptutor.services.file_io import atomic_write_json


LUNA_PROVIDER_MODEL = "gpt-5.6-luna"
LUNA_PROFILE_ID = "llm-openai-global"
LUNA_LOGICAL_MODEL_ID = "llm-gpt-5-6-luna"
_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CROCKFORD_ALLOWED = frozenset(_CROCKFORD_ALPHABET)
_ASCII_WHITESPACE = " \t\r\n\f\v"

_ENROLLMENT_POLICY_LOCK = threading.RLock()


class InviteCodeError(ValueError):
    pass


class EnrollmentConflict(RuntimeError):
    pass


class EnrollmentUnavailable(RuntimeError):
    pass


class EnrollmentValidationError(ValueError):
    pass


class EnrollmentThrottled(EnrollmentUnavailable):
    def __init__(self, retry_after: int):
        super().__init__("Too many invalid invite-code attempts")
        self.retry_after = retry_after


@dataclass(frozen=True)
class LunaTarget:
    profile_id: str
    model_id: str


@dataclass(frozen=True)
class ReconciliationResult:
    recovery_required: bool
    cleared: int = 0
    orphan_grants_removed: int = 0


def enrollment_policy_lock() -> threading.RLock:
    return _ENROLLMENT_POLICY_LOCK


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enrollment_dir() -> Path:
    # Resolve lazily so isolated tests and runtime-home overrides remain exact.
    from . import paths

    return paths.SYSTEM_ROOT / "auth" / "enrollment"


def _journal_path(enrollment_id: str) -> Path:
    if not enrollment_id.startswith("enr_") or not enrollment_id[4:].isalnum():
        raise EnrollmentUnavailable("Invalid enrollment journal id")
    return _enrollment_dir() / f"{enrollment_id}.json"


def generate_invite_code() -> str:
    """Generate an exactly 80-bit, unbiased Crockford/Base32 invite code."""
    value = int.from_bytes(secrets.token_bytes(10), "big")
    symbols = [""] * 16
    for index in range(15, -1, -1):
        symbols[index] = _CROCKFORD_ALPHABET[value & 31]
        value >>= 5
    body = "".join(symbols)
    return "TEEECHR-" + "-".join(body[index : index + 4] for index in range(0, 16, 4))


def canonicalize_invite_code(value: object) -> str:
    if not isinstance(value, str):
        raise InviteCodeError("Invite code is required")
    trimmed = value.strip(_ASCII_WHITESPACE)
    # Reject non-ASCII leading/trailing whitespace rather than making visually
    # distinct values equivalent.
    if trimmed and (trimmed[0].isspace() or trimmed[-1].isspace()):
        raise InviteCodeError("Invite code contains unsupported whitespace")
    compact = trimmed.upper().replace("-", "").replace(" ", "")
    if not compact.startswith("TEEECHR"):
        raise InviteCodeError("Invite code is invalid")
    body = compact[len("TEEECHR") :]
    if len(body) != 16 or any(symbol not in _CROCKFORD_ALLOWED for symbol in body):
        raise InviteCodeError("Invite code is invalid")
    return "TEEECHR-" + "-".join(body[index : index + 4] for index in range(0, 16, 4))


def hash_invite_code(canonical_code: str) -> str:
    import bcrypt

    canonical = canonicalize_invite_code(canonical_code)
    return bcrypt.hashpw(canonical.encode("ascii"), bcrypt.gensalt()).decode("ascii")


def verify_invite_code(value: object, hashed: str) -> bool:
    import bcrypt

    try:
        canonical = canonicalize_invite_code(value)
        return bcrypt.checkpw(canonical.encode("ascii"), hashed.encode("ascii"))
    except (InviteCodeError, ValueError, TypeError):
        return False


def validate_enrollment_credentials(
    username: object, password: object
) -> tuple[str, str]:
    """Validate identity fields only after invited callers prove the code."""
    import re

    if not isinstance(username, str):
        raise EnrollmentValidationError("Enter a valid email address or username")
    normalized_username = username.strip()
    email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    plain_re = re.compile(r"^[A-Za-z0-9_\-.]{3,64}$")
    if not normalized_username or (
        not email_re.match(normalized_username) and not plain_re.match(normalized_username)
    ):
        raise EnrollmentValidationError("Enter a valid email address or username")
    if not isinstance(password, str) or len(password) < 8:
        raise EnrollmentValidationError("Password must be at least 8 characters")
    return normalized_username, password


def _qualified_pricing_version(catalog: dict[str, Any]) -> str | None:
    try:
        from deeptutor.services.config.text_generation_registry import (
            TEXT_GENERATION_FEATURES,
            TextGenerationRegistry,
        )

        registry = TextGenerationRegistry.from_catalog(catalog)
        resolved = [registry.resolve(feature) for feature in TEXT_GENERATION_FEATURES]
        if not all(
            item.mode == "qualified" and item.model.api_model == LUNA_PROVIDER_MODEL
            for item in resolved
        ):
            return None
        versions = {item.model.pricing.version for item in resolved}
        return versions.pop() if len(versions) == 1 else None
    except Exception:
        return None


def resolve_luna_target(
    catalog: dict[str, Any],
    *,
    usage_policy_enabled: bool,
    usage_pricing_version: str | None = None,
) -> LunaTarget | None:
    """Return the sole eligible global Luna target, or fail closed."""
    pricing_version = _qualified_pricing_version(catalog)
    if (
        not usage_policy_enabled
        or pricing_version is None
        or (usage_pricing_version is not None and usage_pricing_version != pricing_version)
    ):
        return None
    candidates: list[LunaTarget] = []
    llm = (catalog.get("services") or {}).get("llm") or {}
    active_profile_id = str(llm.get("active_profile_id") or "")
    active_model_id = str(llm.get("active_model_id") or "")
    for profile in llm.get("profiles") or []:
        if not isinstance(profile, dict):
            continue
        profile_id = str(profile.get("id") or "")
        if (
            (active_profile_id and profile_id != active_profile_id)
            or profile.get("active", True) is False
            or bool(profile.get("owner_bound"))
            or profile.get("ordinary_user_assignable", True) is False
            or not str(profile.get("api_key") or "").strip()
        ):
            continue
        for model in profile.get("models") or []:
            if not isinstance(model, dict):
                continue
            model_id = str(model.get("id") or "")
            if (
                (active_model_id and model_id != active_model_id)
                or model.get("active", True) is False
                or model.get("model") != LUNA_PROVIDER_MODEL
            ):
                continue
            if profile_id and model_id:
                candidates.append(LunaTarget(profile_id=profile_id, model_id=model_id))
    return candidates[0] if len(candidates) == 1 else None


def canonical_grant_json(grant: dict[str, Any]) -> str:
    return json.dumps(grant, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def grant_fingerprint(grant: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_grant_json(grant).encode("utf-8")).hexdigest()


def create_journal(
    *,
    user_id: str,
    policy_revision: int,
    profile_id: str,
    model_ids: list[str],
) -> dict[str, Any]:
    enrollment_id = f"enr_{uuid4().hex}"
    now = _utc_now()
    journal = {
        "version": 1,
        "enrollment_id": enrollment_id,
        "reserved_user_id": user_id,
        "policy_revision": int(policy_revision),
        "profile_id": profile_id,
        "model_ids": list(model_ids),
        "grant_fingerprint": None,
        "state": "reserved",
        "created_at": now,
        "updated_at": now,
    }
    path = _journal_path(enrollment_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    atomic_write_json(path, journal)
    path.chmod(0o600)
    return journal


def load_journal(enrollment_id: str) -> dict[str, Any] | None:
    path = _journal_path(enrollment_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def authorize_grant_write(
    enrollment_id: str, user_id: str, grant: dict[str, Any]
) -> bool:
    journal = load_journal(enrollment_id)
    if not journal or journal.get("state") != "reserved":
        return False
    expected = [
        {
            "profile_id": str(journal.get("profile_id") or ""),
            "model_ids": [str(item) for item in journal.get("model_ids") or []],
        }
    ]
    return (
        journal.get("version") == 1
        and journal.get("enrollment_id") == enrollment_id
        and journal.get("reserved_user_id") == user_id
        and grant.get("user_id") == user_id
        and (grant.get("models") or {}).get("llm") == expected
    )


def record_grant_fingerprint(enrollment_id: str, grant: dict[str, Any]) -> dict[str, Any]:
    path = _journal_path(enrollment_id)
    journal = load_journal(enrollment_id)
    if not journal or journal.get("state") != "reserved":
        raise EnrollmentUnavailable("Enrollment journal is not active")
    journal["grant_fingerprint"] = grant_fingerprint(grant)
    journal["state"] = "grant_written"
    journal["updated_at"] = _utc_now()
    atomic_write_json(path, journal)
    path.chmod(0o600)
    verified = load_journal(enrollment_id)
    if verified != journal:
        raise EnrollmentUnavailable("Enrollment journal verification failed")
    return journal


def remove_journal(enrollment_id: str) -> None:
    _journal_path(enrollment_id).unlink(missing_ok=True)


def _reconcile_enrollment_journals_locked() -> ReconciliationResult:
    from .grants import grant_path, load_grant
    from .identity import get_user_by_id

    directory = _enrollment_dir()
    if not directory.exists():
        return ReconciliationResult(recovery_required=False)
    cleared = 0
    removed = 0
    recovery_required = False
    for path in sorted(directory.glob("enr_*.json")):
        enrollment_id = path.stem
        journal = load_journal(enrollment_id)
        if (
            not journal
            or journal.get("version") != 1
            or journal.get("enrollment_id") != enrollment_id
            or journal.get("state") != "grant_written"
            or not isinstance(journal.get("grant_fingerprint"), str)
        ):
            recovery_required = True
            continue
        user_id = str(journal.get("reserved_user_id") or "")
        target = grant_path(user_id)
        if not target.exists():
            recovery_required = True
            continue
        grant = load_grant(user_id)
        if grant_fingerprint(grant) != journal["grant_fingerprint"]:
            recovery_required = True
            continue
        identity = get_user_by_id(user_id)
        if identity is None:
            target.unlink()
            path.unlink()
            removed += 1
        else:
            _username, record = identity
            if str(record.get("role") or "") != "user":
                recovery_required = True
                continue
            path.unlink()
            cleared += 1
    return ReconciliationResult(
        recovery_required=recovery_required,
        cleared=cleared,
        orphan_grants_removed=removed,
    )


def reconcile_enrollment_journals() -> ReconciliationResult:
    from .identity import identity_write_lock

    with _ENROLLMENT_POLICY_LOCK, identity_write_lock():
        return _reconcile_enrollment_journals_locked()


class InvalidCodeThrottle:
    """Bounded, process-local invalid invite-code throttle."""

    def __init__(self, *, limit: int = 5, window_seconds: int = 600, max_sources: int = 2048):
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_sources = max_sources
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, source: str, *, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        with self._lock:
            values = [
                item
                for item in self._failures.get(source, [])
                if current - item < self.window_seconds
            ]
            self._failures[source] = values
            if len(values) < self.limit:
                return 0
            return max(1, int(self.window_seconds - (current - values[0])))

    def fail(self, source: str, *, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        with self._lock:
            if source not in self._failures and len(self._failures) >= self.max_sources:
                oldest = min(
                    self._failures,
                    key=lambda key: self._failures[key][-1] if self._failures[key] else 0,
                )
                self._failures.pop(oldest, None)
            values = [
                item
                for item in self._failures.get(source, [])
                if current - item < self.window_seconds
            ]
            values.append(current)
            self._failures[source] = values
            return max(0, self.limit - len(values))

    def clear(self, source: str) -> None:
        with self._lock:
            self._failures.pop(source, None)


_THROTTLE = InvalidCodeThrottle()


def resolve_client_source(
    *, direct_peer: str, canonical_forwarded: str | None, trusted_proxy_cidrs: list[str]
) -> str:
    """Use a forwarded address only when the immediate peer is trusted."""
    try:
        peer = ipaddress.ip_address(direct_peer)
    except ValueError:
        return direct_peer
    trusted = False
    for value in trusted_proxy_cidrs:
        try:
            if peer in ipaddress.ip_network(value, strict=False):
                trusted = True
                break
        except ValueError:
            continue
    if not trusted or not canonical_forwarded:
        return direct_peer
    candidate = canonical_forwarded.strip()
    # Caddy's canonical address must be one address, never an attacker-chosen
    # comma-separated chain.
    if "," in candidate:
        return direct_peer
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return direct_peer


def _load_policy_settings() -> tuple[dict[str, Any], Any]:
    """Load/migrate auth authority and permanently latch an existing install."""
    from deeptutor.services.config.runtime_settings import get_runtime_settings_service
    from .identity import load_users

    service = get_runtime_settings_service()
    settings = service.load_auth(include_process_overrides=False)
    finalized_identity_exists = bool(load_users()) or bool(
        str(settings.get("password_hash") or "").strip()
    )
    if (
        settings.get("version") == 2
        and settings.get("registration_valid", True)
        and settings.get("bootstrap_completed_at") is None
        and finalized_identity_exists
    ):
        settings["bootstrap_completed_at"] = _utc_now()
        settings = service.save_auth(settings)
    return settings, service


def current_luna_target() -> LunaTarget | None:
    try:
        from deeptutor.courses.provider_usage import get_provider_usage_ledger
        from deeptutor.services.config.model_catalog import get_model_catalog_service

        catalog = get_model_catalog_service().load()
        policy = get_provider_usage_ledger().load_policy()
        return resolve_luna_target(
            catalog,
            usage_policy_enabled=bool(policy.enabled),
            usage_pricing_version=str(policy.pricing_version),
        )
    except Exception:
        return None


def registration_mode(*, recovery_required: bool | None = None) -> str:
    from .identity import load_users

    settings, _service = _load_policy_settings()
    if settings.get("version") != 2 or not settings.get("registration_valid", True):
        return "closed"
    if recovery_required is None:
        try:
            recovery_required = reconcile_enrollment_journals().recovery_required
        except Exception:
            recovery_required = True
    if recovery_required:
        return "closed"
    users = load_users()
    if (
        settings.get("bootstrap_completed_at") is None
        and not users
        and not str(settings.get("password_hash") or "").strip()
    ):
        return "bootstrap"
    registration = settings.get("registration") or {}
    if (
        settings.get("bootstrap_completed_at")
        and registration.get("invite_enabled") is True
        and isinstance(registration.get("invite_code_hash"), str)
        and current_luna_target() is not None
    ):
        return "invite"
    return "closed"


def enrollment_status() -> dict[str, Any]:
    with _ENROLLMENT_POLICY_LOCK:
        try:
            journal_recovery = reconcile_enrollment_journals().recovery_required
        except Exception:
            journal_recovery = True
        settings, _service = _load_policy_settings()
        recovery = journal_recovery or settings.get("version") != 2 or not settings.get(
            "registration_valid", True
        )
        registration = settings.get("registration") or {}
        target = current_luna_target()
        configured = isinstance(registration.get("invite_code_hash"), str)
        enabled = bool(registration.get("invite_enabled"))
        if recovery:
            state = "recovery_required"
        elif not configured:
            state = "not_configured"
        elif enabled:
            state = "active"
        else:
            state = "disabled"
        return {
            "state": state,
            "enabled": enabled,
            "configured": configured,
            "revision": int(registration.get("revision") or 0),
            "rotated_at": registration.get("rotated_at"),
            "assigned_model": "Luna",
            "model_available": target is not None,
            "recovery_required": recovery,
        }


def rotate_invite_code(*, expected_revision: int) -> tuple[str, dict[str, Any]]:
    with _ENROLLMENT_POLICY_LOCK:
        if reconcile_enrollment_journals().recovery_required:
            raise EnrollmentUnavailable("Enrollment recovery required")
        target = current_luna_target()
        if target is None:
            raise EnrollmentUnavailable("Luna enrollment target is unavailable")
        settings, service = _load_policy_settings()
        if settings.get("version") != 2 or not settings.get("registration_valid", True):
            raise EnrollmentUnavailable("Enrollment settings are unavailable")
        registration = dict(settings.get("registration") or {})
        revision = int(registration.get("revision") or 0)
        if revision != expected_revision:
            raise EnrollmentConflict("Enrollment settings changed")
        code = generate_invite_code()
        registration.update(
            {
                "revision": revision + 1,
                "invite_enabled": True,
                "invite_code_hash": hash_invite_code(code),
                "rotated_at": _utc_now(),
            }
        )
        settings["registration"] = registration
        service.save_auth(settings)
        return code, enrollment_status()


def set_invite_enabled(*, enabled: bool, expected_revision: int) -> dict[str, Any]:
    with _ENROLLMENT_POLICY_LOCK:
        if reconcile_enrollment_journals().recovery_required:
            raise EnrollmentUnavailable("Enrollment recovery required")
        settings, service = _load_policy_settings()
        if settings.get("version") != 2 or not settings.get("registration_valid", True):
            raise EnrollmentUnavailable("Enrollment settings are unavailable")
        registration = dict(settings.get("registration") or {})
        revision = int(registration.get("revision") or 0)
        if revision != expected_revision:
            raise EnrollmentConflict("Enrollment settings changed")
        if enabled and (
            not isinstance(registration.get("invite_code_hash"), str)
            or current_luna_target() is None
        ):
            raise EnrollmentUnavailable("Enrollment cannot be enabled until Luna is available")
        registration["invite_enabled"] = bool(enabled)
        registration["revision"] = revision + 1
        settings["registration"] = registration
        service.save_auth(settings)
        return enrollment_status()


def complete_bootstrap(*, username: str, password_hash: str) -> dict[str, Any]:
    """Atomically publish the one first administrator and latch bootstrap."""
    from .identity import create_user_only, identity_write_lock, load_users, new_user_id

    with _ENROLLMENT_POLICY_LOCK, identity_write_lock():
        settings, service = _load_policy_settings()
        if (
            settings.get("version") != 2
            or not settings.get("registration_valid", True)
            or settings.get("bootstrap_completed_at") is not None
            or load_users()
        ):
            raise EnrollmentUnavailable("Bootstrap registration is closed")
        record = create_user_only(
            username,
            password_hash,
            user_id=new_user_id(),
            role="admin",
        )
        # Identity publication can survive a process interruption; the next
        # policy load detects that finalized administrator and seals the latch.
        settings["bootstrap_completed_at"] = _utc_now()
        service.save_auth(settings)
        return record


def invited_signup(
    *,
    username: str,
    password: str,
    invite_code: object,
    source: str,
) -> dict[str, Any]:
    """Complete grant-first, identity-last learner enrollment."""
    from .grants import load_grant, save_grant
    from .identity import (
        create_user_only,
        identity_write_lock,
        load_users,
        new_user_id,
    )

    with _ENROLLMENT_POLICY_LOCK:
        if registration_mode() != "invite":
            raise EnrollmentUnavailable("Invite registration is closed")
        retry_after = _THROTTLE.retry_after(source)
        if retry_after:
            raise EnrollmentThrottled(retry_after)
        settings, _service = _load_policy_settings()
        registration = settings.get("registration") or {}
        hashed = registration.get("invite_code_hash")
        if not isinstance(hashed, str) or not verify_invite_code(invite_code, hashed):
            remaining = _THROTTLE.fail(source)
            if remaining == 0:
                raise EnrollmentThrottled(_THROTTLE.retry_after(source))
            raise InviteCodeError("Invite code is invalid")
        _THROTTLE.clear(source)
        username, password = validate_enrollment_credentials(username, password)

        with identity_write_lock():
            # Revalidate every authority while both locks are held.
            settings, _service = _load_policy_settings()
            registration = settings.get("registration") or {}
            if (
                registration.get("invite_enabled") is not True
                or not isinstance(registration.get("invite_code_hash"), str)
                or not verify_invite_code(invite_code, registration["invite_code_hash"])
            ):
                raise EnrollmentUnavailable("Invite registration changed")
            if username in load_users():
                raise EnrollmentConflict("Username already taken")
            target = current_luna_target()
            if target is None:
                raise EnrollmentUnavailable("Luna enrollment target is unavailable")
            from deeptutor.services.auth import hash_password

            password_hash = hash_password(password)
            user_id = new_user_id()
            journal = create_journal(
                user_id=user_id,
                policy_revision=int(registration.get("revision") or 0),
                profile_id=target.profile_id,
                model_ids=[target.model_id],
            )
            grant = save_grant(
                user_id,
                {
                    "version": 2,
                    "user_id": user_id,
                    "models": {
                        "llm": [
                            {
                                "profile_id": target.profile_id,
                                "model_ids": [target.model_id],
                            }
                        ]
                    },
                },
                enrollment_id=journal["enrollment_id"],
            )
            persisted = load_grant(user_id)
            record_grant_fingerprint(journal["enrollment_id"], persisted)
            verified = load_journal(journal["enrollment_id"])
            if not verified or verified.get("grant_fingerprint") != grant_fingerprint(grant):
                raise EnrollmentUnavailable("Enrollment grant verification failed")
            record = create_user_only(
                username,
                password_hash,
                user_id=user_id,
                role="user",
            )
            remove_journal(journal["enrollment_id"])
            return record


__all__ = [
    "EnrollmentConflict",
    "EnrollmentThrottled",
    "EnrollmentUnavailable",
    "EnrollmentValidationError",
    "InvalidCodeThrottle",
    "InviteCodeError",
    "LunaTarget",
    "ReconciliationResult",
    "authorize_grant_write",
    "canonical_grant_json",
    "canonicalize_invite_code",
    "complete_bootstrap",
    "create_journal",
    "enrollment_policy_lock",
    "enrollment_status",
    "generate_invite_code",
    "grant_fingerprint",
    "hash_invite_code",
    "invited_signup",
    "record_grant_fingerprint",
    "reconcile_enrollment_journals",
    "remove_journal",
    "resolve_client_source",
    "resolve_luna_target",
    "registration_mode",
    "rotate_invite_code",
    "set_invite_enabled",
    "verify_invite_code",
    "validate_enrollment_credentials",
]
