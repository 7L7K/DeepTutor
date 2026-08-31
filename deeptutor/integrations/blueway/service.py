"""Owner-bound connection and durable-sync orchestration primitives."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import secrets
import threading
import time
from typing import Any

from deeptutor.courses.ingestion import _current_personal_user
from deeptutor.courses.repository import CourseConflictError, CourseRepository
from deeptutor.courses.service import get_current_course_service
from deeptutor.multi_user.context import get_current_user_or_none
from deeptutor.multi_user.identity import identity_write_lock
from deeptutor.multi_user.paths import get_personal_path_service

from .bundles import (
    BundleMaterializationError,
    materialize_course_bundles,
    reconcile_ready_bundle_indexes,
)
from .config import BlueWaySettings, IntegrationConfigurationError
from .credentials import CredentialError, CredentialStore
from .observability import (
    emit_blueway_event,
    request_trace_id,
    safe_pairing_trace_id,
    safe_persisted_pairing_trace_id,
    safe_transport_reason,
)
from .pairing_store import PairingAttemptStore, PairingStoreError
from .repository import BlueWayNotFoundError, BlueWayRepository, Connection, SyncRun
from .snapshot import SnapshotValidationError, validate_snapshot
from .transport import (
    BlueWayAuthorityError,
    BlueWayAuthorizationPending,
    BlueWayTransport,
    BlueWayTransportError,
    HttpBlueWayTransport,
    TokenExchange,
)


class BlueWayUnavailableError(RuntimeError):
    pass


class BlueWayCredentialRecoveryRequired(RuntimeError):
    """The owner must approve a replacement grant before BlueWay can continue."""


@dataclass(frozen=True)
class PairingAttempt:
    id: str
    owner_user_id: str
    device_code: str
    verifier: str
    user_code: str
    verification_uri: str
    expires_at: float
    request_id: str
    trace_id: str
    mode: str = "connect"
    state: str = "pending"
    terminal_at: float | None = None
    error_code: str | None = None
    connection_id: str | None = None
    recovery_connection_id: str | None = None
    recovery_revision: int | None = None
    recovery_generation: int | None = None


class BlueWayService:
    """Owner-bound BlueWay coordinator for one process and at most 50 beta profiles.

    Pairing metadata and provider secrets are encrypted per owner so a process
    restart can resume a valid request without exposing PKCE material to the
    browser. Durable authority begins only after a credential is encrypted and
    the connection is committed to the owner's Course database.
    """

    PAIRING_RETENTION_SECONDS = 3600.0

    def __init__(self, settings: BlueWaySettings, transport: BlueWayTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport or HttpBlueWayTransport(settings)
        self._starting_owners: set[str] = set()
        self._exchanging_attempts: set[tuple[str, str]] = set()
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="blueway-sync")
        self._scheduled_connections: set[tuple[str, str]] = set()

    def _owner(self) -> str:
        user = get_current_user_or_none()
        if user is None:
            raise BlueWayUnavailableError("Authenticated user context is required")
        return user.id

    def _repository(self) -> BlueWayRepository:
        if not self.settings.enabled:
            raise BlueWayUnavailableError("BlueWay integration is disabled")
        return BlueWayRepository(get_current_course_service().repository)

    def _repository_for_owner(self, owner_user_id: str) -> BlueWayRepository:
        return BlueWayRepository(
            CourseRepository(get_personal_path_service(owner_user_id).get_courses_db(), owner_user_id)
        )

    def _credential_store(self, owner_user_id: str) -> CredentialStore:
        paths = get_personal_path_service(owner_user_id)
        return CredentialStore(
            paths.get_integration_credentials_dir(),
            self.settings.master_key,
        )

    def _pairing_store(self, owner_user_id: str) -> PairingAttemptStore:
        paths = get_personal_path_service(owner_user_id)
        return PairingAttemptStore(
            paths.get_integration_credentials_dir() / "pairing-attempts",
            self.settings.master_key,
        )

    @staticmethod
    def _attempt_record(attempt: PairingAttempt) -> dict[str, Any]:
        return {
            "owner_user_id": attempt.owner_user_id,
            "device_code": attempt.device_code,
            "verifier": attempt.verifier,
            "user_code": attempt.user_code,
            "verification_uri": attempt.verification_uri,
            "expires_at": attempt.expires_at,
            "request_id": attempt.request_id,
            "trace_id": attempt.trace_id,
            "mode": attempt.mode,
            "state": attempt.state,
            "terminal_at": attempt.terminal_at,
            "error_code": attempt.error_code,
            "connection_id": attempt.connection_id,
            "recovery_connection_id": attempt.recovery_connection_id,
            "recovery_revision": attempt.recovery_revision,
            "recovery_generation": attempt.recovery_generation,
        }

    @staticmethod
    def _attempt_from_record(attempt_id: str, record: dict[str, Any]) -> PairingAttempt:
        required = ("owner_user_id", "device_code", "verifier", "user_code", "verification_uri", "expires_at", "request_id")
        if any(key not in record for key in required):
            raise BlueWayUnavailableError("BlueWay pairing state is invalid")
        try:
            return PairingAttempt(
                id=attempt_id,
                owner_user_id=str(record["owner_user_id"]),
                device_code=str(record["device_code"]),
                verifier=str(record["verifier"]),
                user_code=str(record["user_code"]),
                verification_uri=str(record["verification_uri"]),
                expires_at=float(record["expires_at"]),
                request_id=str(record["request_id"]),
                trace_id=safe_persisted_pairing_trace_id(
                    record.get("trace_id"), str(record["request_id"])
                ),
                mode=str(record.get("mode", "connect")),
                state=str(record.get("state", "pending")),
                terminal_at=(float(record["terminal_at"]) if record.get("terminal_at") is not None else None),
                error_code=(str(record["error_code"]) if record.get("error_code") is not None else None),
                connection_id=(str(record["connection_id"]) if record.get("connection_id") is not None else None),
                recovery_connection_id=(str(record["recovery_connection_id"]) if record.get("recovery_connection_id") is not None else None),
                recovery_revision=(int(record["recovery_revision"]) if record.get("recovery_revision") is not None else None),
                recovery_generation=(int(record["recovery_generation"]) if record.get("recovery_generation") is not None else None),
            )
        except (TypeError, ValueError) as exc:
            raise BlueWayUnavailableError("BlueWay pairing state is invalid") from exc

    def _persist_attempt(self, attempt: PairingAttempt) -> None:
        self._pairing_store(attempt.owner_user_id).write(
            owner_user_id=attempt.owner_user_id,
            attempt_id=attempt.id,
            record=self._attempt_record(attempt),
        )

    def _transition_attempt(
        self,
        attempt: PairingAttempt,
        state: str,
        *,
        error_code: str | None = None,
        connection_id: str | None = None,
        clear_secrets: bool = True,
    ) -> PairingAttempt:
        if state not in {"pending", "approved", "expired", "cancelled", "failed"}:
            raise ValueError("Invalid BlueWay pairing state")
        next_attempt = PairingAttempt(
            **{
                **self._attempt_record(attempt),
                "id": attempt.id,
                "device_code": "" if clear_secrets else attempt.device_code,
                "verifier": "" if clear_secrets else attempt.verifier,
                "state": state,
                "terminal_at": time.time() if state != "pending" else None,
                "error_code": error_code,
                "connection_id": connection_id or attempt.connection_id,
            }
        )
        self._persist_attempt(next_attempt)
        return next_attempt

    def _purge_owner_attempts(self, owner_user_id: str, now: float) -> None:
        store = self._pairing_store(owner_user_id)
        for attempt_id, record in store.list(owner_user_id=owner_user_id):
            attempt = self._attempt_from_record(attempt_id, record)
            if attempt.state == "pending" and attempt.expires_at <= now:
                attempt = self._transition_attempt(attempt, "expired", error_code="expired")
                emit_blueway_event(
                    "blueway_pairing_expired",
                    trace_id=attempt.trace_id,
                    attempt_ref=attempt.id,
                    state_from="pending",
                    state_to="expired",
                    reason_code="request_expired",
                    outcome="terminal",
                )
            if attempt.terminal_at is not None and attempt.terminal_at + self.PAIRING_RETENTION_SECONDS <= now:
                store.remove(attempt.id)

    def current_attempt(self) -> PairingAttempt | None:
        owner = self._owner()
        try:
            self._purge_owner_attempts(owner, time.time())
            attempts = [
                self._attempt_from_record(attempt_id, record)
                for attempt_id, record in self._pairing_store(owner).list(owner_user_id=owner)
            ]
        except PairingStoreError as exc:
            raise BlueWayUnavailableError("BlueWay pairing state is unavailable") from exc
        if not attempts:
            return None
        attempts.sort(key=lambda item: (item.state == "pending", item.terminal_at or item.expires_at), reverse=True)
        return attempts[0]

    def _preflight_connection(
        self, repository: BlueWayRepository, connection: Connection,
    ) -> tuple[Connection, CredentialStore, str]:
        if connection.observability_trace_id is None:
            connection = repository.ensure_observability_trace(
                connection.id, trace_id=request_trace_id(),
            )
        if connection.credential_status != "healthy":
            raise BlueWayCredentialRecoveryRequired(
                "BlueWay credential recovery is required"
            )
        store = self._credential_store(connection.owner_user_id)
        try:
            refresh_token = store.read(
                owner_user_id=connection.owner_user_id,
                connection_id=connection.id,
                scope_version=connection.scope_version,
            )
        except CredentialError as exc:
            repository.require_credential_recovery(
                connection.id, expected_revision=connection.revision,
            )
            emit_blueway_event(
                "blueway_credential_recovery_required",
                trace_id=connection.observability_trace_id,
                connection_ref=connection.id,
                state_from="active",
                state_to="recovery_required",
                reason_code="credential_recovery_required",
                outcome="required",
            )
            raise BlueWayCredentialRecoveryRequired(
                "BlueWay credential recovery is required"
            ) from exc
        return connection, store, refresh_token

    @staticmethod
    def _assert_owner_current(owner_user_id: str) -> None:
        if _current_personal_user(owner_user_id) is None:
            raise BlueWayUnavailableError("BlueWay account is no longer active")

    @staticmethod
    def _verifier() -> str:
        return base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode("ascii")

    @staticmethod
    def _challenge(verifier: str) -> str:
        return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")

    @staticmethod
    def _device_code() -> str:
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")

    @staticmethod
    def _user_code() -> str:
        return base64.urlsafe_b64encode(secrets.token_bytes(12)).rstrip(b"=").decode("ascii")

    def start_connection(self) -> PairingAttempt:
        owner = self._owner()
        repository = self._repository()  # validates config/backend before making any provider request
        with identity_write_lock():
            self._assert_owner_current(owner)
            with self._lock:
                now = time.time()
                self._purge_owner_attempts(owner, now)
                self._assert_owner_current(owner)
                if repository.visible_connection() is not None:
                    raise CourseConflictError("Disconnect BlueWay before starting a replacement pairing")
                current = self.current_attempt()
                if current is not None and current.state == "pending" and current.mode == "connect":
                    return current
                if current is not None and current.state == "pending":
                    raise CourseConflictError("BlueWay pairing is already pending")
                if owner in self._starting_owners:
                    raise CourseConflictError("BlueWay pairing is already pending")
                self._starting_owners.add(owner)
        verifier = self._verifier()
        device_code, user_code = self._device_code(), self._user_code()
        try:
            authorization = self.transport.begin_device_authorization(
                client_id=self.settings.client_id, audience=self.settings.client_id, device_code=device_code,
                user_code=user_code, pkce_challenge=self._challenge(verifier),
            )
            with identity_write_lock():
                self._assert_owner_current(owner)
                with self._lock:
                    now = time.time()
                    self._assert_owner_current(owner)
                    if repository.visible_connection() is not None:
                        raise CourseConflictError("Disconnect BlueWay before starting a replacement pairing")
                    if authorization.expires_at <= now or not authorization.device_code or not authorization.user_code:
                        raise BlueWayUnavailableError("BlueWay returned an invalid device authorization")
                    attempt = PairingAttempt(
                        id=f"bwa_{secrets.token_hex(16)}", owner_user_id=owner,
                        device_code=device_code, verifier=verifier,
                        user_code=authorization.user_code, verification_uri=authorization.verification_uri,
                        expires_at=authorization.expires_at, request_id=authorization.request_id,
                        trace_id=safe_pairing_trace_id(authorization.request_id),
                        mode="connect",
                    )
                    try:
                        self._persist_attempt(attempt)
                    except Exception:
                        cancel = getattr(self.transport, "cancel", None)
                        if callable(cancel):
                            try:
                                cancel(request_id=attempt.request_id, device_code=attempt.device_code)
                            except Exception:
                                pass
                        raise
                    emit_blueway_event(
                        "blueway_pairing_started",
                        trace_id=attempt.trace_id,
                        attempt_ref=attempt.id,
                        state_to="pending",
                        outcome="pending",
                    )
        finally:
            with self._lock:
                self._starting_owners.discard(owner)
        return attempt

    def start_recovery(self) -> PairingAttempt:
        owner = self._owner()
        repository = self._repository()
        with identity_write_lock():
            self._assert_owner_current(owner)
            connection = repository.visible_connection()
            if (
                connection is None
                or connection.credential_status != "recovery_required"
            ):
                raise BlueWayNotFoundError("Integration resource not found")
            with self._lock:
                now = time.time()
                try:
                    self._purge_owner_attempts(owner, now)
                    current = self.current_attempt()
                except (BlueWayUnavailableError, PairingStoreError):
                    # A credential-recovery flow may intentionally use the
                    # replacement master key. Old pairing ciphertext cannot be
                    # resumed or cancelled, so remove only these short-lived
                    # artifacts before creating a fresh recovery attempt.
                    self._pairing_store(owner).clear()
                    current = None
                if current is not None and current.state == "pending" and current.mode == "recovery":
                    return current
                if current is not None and current.state == "pending":
                    raise CourseConflictError("BlueWay pairing is already pending")
                if owner in self._starting_owners:
                    raise CourseConflictError("BlueWay pairing is already pending")
                self._starting_owners.add(owner)
        verifier = self._verifier()
        device_code, user_code = self._device_code(), self._user_code()
        try:
            authorization = self.transport.begin_device_authorization(
                client_id=self.settings.client_id,
                audience=self.settings.client_id,
                device_code=device_code,
                user_code=user_code,
                pkce_challenge=self._challenge(verifier),
            )
            with identity_write_lock():
                self._assert_owner_current(owner)
                current = repository.get_connection(connection.id)
                if (
                    current.credential_status != "recovery_required"
                    or current.revision != connection.revision
                    or current.grant_generation != connection.grant_generation
                ):
                    raise CourseConflictError(
                        "BlueWay credential recovery is stale"
                    )
                if (
                    authorization.expires_at <= time.time()
                    or not authorization.device_code
                    or not authorization.user_code
                ):
                    raise BlueWayUnavailableError(
                        "BlueWay returned an invalid device authorization"
                    )
                attempt = PairingAttempt(
                    id=f"bwa_{secrets.token_hex(16)}",
                    owner_user_id=owner,
                    device_code=device_code,
                    verifier=verifier,
                    user_code=authorization.user_code,
                    verification_uri=authorization.verification_uri,
                    expires_at=authorization.expires_at,
                    request_id=authorization.request_id,
                    trace_id=safe_pairing_trace_id(authorization.request_id),
                    mode="recovery",
                    recovery_connection_id=current.id,
                    recovery_revision=current.revision,
                    recovery_generation=current.grant_generation,
                )
                try:
                    self._persist_attempt(attempt)
                except Exception:
                    cancel = getattr(self.transport, "cancel", None)
                    if callable(cancel):
                        try:
                            cancel(
                                request_id=attempt.request_id,
                                device_code=attempt.device_code,
                            )
                        except Exception:
                            pass
                    raise
                emit_blueway_event(
                    "blueway_pairing_started",
                    trace_id=attempt.trace_id,
                    attempt_ref=attempt.id,
                    state_to="pending",
                    outcome="pending",
                )
        finally:
            with self._lock:
                self._starting_owners.discard(owner)
        return attempt

    def get_attempt(
        self, attempt_id: str, *, purge_expired: bool = True,
    ) -> PairingAttempt:
        owner = self._owner()
        with self._lock:
            if purge_expired:
                try:
                    self._purge_owner_attempts(owner, time.time())
                except PairingStoreError as exc:
                    raise BlueWayNotFoundError("Integration resource not found") from exc
            store = self._pairing_store(owner)
            try:
                record = store.read(owner_user_id=owner, attempt_id=attempt_id)
                resolved_attempt_id = attempt_id
            except PairingStoreError:
                # Completion links may carry the provider request id. Resolve it
                # only inside the authenticated owner's encrypted records.
                try:
                    matches = [
                        (candidate_id, candidate_record)
                        for candidate_id, candidate_record in store.list(owner_user_id=owner)
                        if candidate_record.get("request_id") == attempt_id
                    ]
                except PairingStoreError as exc:
                    raise BlueWayNotFoundError("Integration resource not found") from exc
                if len(matches) != 1:
                    raise BlueWayNotFoundError("Integration resource not found")
                resolved_attempt_id, record = matches[0]
            attempt = self._attempt_from_record(resolved_attempt_id, record)
        if attempt.owner_user_id != owner:
            raise BlueWayNotFoundError("Integration resource not found")
        return attempt

    def complete_connection_for_transport(
        self, *, attempt_id: str, exchange: TokenExchange, scope_version: str = "academic.read.v1"
    ) -> Connection:
        """Persist an approved transport result; callable only by future transport code/tests.

        No HTTP route accepts subjects or refresh credentials from a browser.
        """
        with identity_write_lock():
            attempt = self.get_attempt(attempt_id)
            if attempt.mode != "connect" or attempt.state != "pending":
                raise BlueWayNotFoundError("Integration resource not found")
            self._assert_owner_current(attempt.owner_user_id)
            repository = self._repository()
            if repository.visible_connection() is not None:
                raise CourseConflictError("Disconnect BlueWay before completing a replacement pairing")
            paths = get_personal_path_service(attempt.owner_user_id)
            provisional_id = f"bwc_{secrets.token_hex(16)}"
            store = CredentialStore(paths.get_integration_credentials_dir(), self.settings.master_key)
            store.write(owner_user_id=attempt.owner_user_id, connection_id=provisional_id,
                        scope_version=scope_version, refresh_token=exchange.refresh_token)
            try:
                # The generated connection id is also the AES-GCM AAD-bound filename.
                # Keep it identical across file and database records.
                connection = repository.create_active_connection(
                    external_subject=exchange.external_subject, scope_version=scope_version,
                    connection_id=provisional_id,
                    observability_trace_id=attempt.trace_id,
                )
            except Exception:
                store.remove(provisional_id)
                raise
        self._transition_attempt(attempt, "approved", connection_id=connection.id)
        return connection

    def complete_recovery_for_transport(
        self, *, attempt_id: str, exchange: TokenExchange,
    ) -> Connection:
        """Commit only an owner-approved replacement for the exact same subject."""
        attempt = self.get_attempt(attempt_id)
        if (
            attempt.mode != "recovery"
            or attempt.state != "pending"
            or attempt.recovery_connection_id is None
            or attempt.recovery_revision is None
            or attempt.recovery_generation is None
        ):
            raise BlueWayNotFoundError("Integration resource not found")
        repository = self._repository()
        connection = repository.get_connection(
            attempt.recovery_connection_id
        )
        if exchange.external_subject != connection.external_subject:
            try:
                self.transport.revoke(refresh_token=exchange.refresh_token)
            finally:
                failed_attempt = self._transition_attempt(
                    attempt, "failed", error_code="wrong_account",
                )
                emit_blueway_event(
                    "blueway_pairing_wrong_account",
                    trace_id=failed_attempt.trace_id,
                    attempt_ref=failed_attempt.id,
                    connection_ref=connection.id,
                    state_from="pending",
                    state_to="failed",
                    reason_code="wrong_account",
                    outcome="rejected",
                )
                raise BlueWayCredentialRecoveryRequired(
                    "Recovery must use the same BlueWay account"
                )
        store = self._credential_store(connection.owner_user_id)
        try:
            with identity_write_lock():
                self._assert_owner_current(attempt.owner_user_id)
                current = repository.get_connection(connection.id)
                if (
                    current.credential_status != "recovery_required"
                    or current.revision != attempt.recovery_revision
                    or current.grant_generation != attempt.recovery_generation
                ):
                    raise CourseConflictError(
                        "BlueWay credential recovery is stale"
                    )
                store.stage_recovery(
                    owner_user_id=current.owner_user_id,
                    connection_id=current.id,
                    scope_version=current.scope_version,
                    refresh_token=exchange.refresh_token,
                )
                store.promote_staged_recovery(
                    owner_user_id=current.owner_user_id,
                    connection_id=current.id,
                    scope_version=current.scope_version,
                )
                completed = repository.complete_credential_recovery(
                    current.id,
                    expected_revision=current.revision,
                    expected_generation=current.grant_generation,
                    observability_trace_id=attempt.trace_id,
                )
        except Exception:
            store.clear_staged_recovery(connection.id)
            try:
                self.transport.revoke(refresh_token=exchange.refresh_token)
            except Exception:
                pass
            failed_attempt = self._transition_attempt(
                attempt, "failed", error_code="recovery_failed",
            )
            emit_blueway_event(
                "blueway_pairing_approval_rejected",
                trace_id=failed_attempt.trace_id,
                attempt_ref=failed_attempt.id,
                connection_ref=connection.id,
                state_from="pending",
                state_to="failed",
                reason_code="recovery_failed",
                outcome="rejected",
            )
            raise
        approved_attempt = self._transition_attempt(
            attempt, "approved", connection_id=completed.id,
        )
        emit_blueway_event(
            "blueway_pairing_approval_received",
            trace_id=approved_attempt.trace_id,
            attempt_ref=approved_attempt.id,
            connection_ref=completed.id,
            state_from="pending",
            state_to="approved",
            outcome="success",
        )
        emit_blueway_event(
            "blueway_pairing_exchanged",
            trace_id=approved_attempt.trace_id,
            attempt_ref=approved_attempt.id,
            connection_ref=completed.id,
            state_from="approved",
            state_to="exchanged",
            outcome="success",
        )
        return completed

    def _approved_connection(self, attempt: PairingAttempt) -> Connection | None:
        """Resolve only the active connection created by this approved attempt.

        New attempts carry an explicit connection id. Older encrypted records
        may be accepted only when their trace already matches the active
        connection; an unbound legacy attempt must never attach to a later
        replacement connection.
        """

        connection = self._repository().active_connection()
        if connection is None:
            return None
        bound_connection_id = attempt.connection_id or attempt.recovery_connection_id
        if bound_connection_id is not None:
            return connection if connection.id == bound_connection_id else None
        if (
            connection.observability_trace_id is not None
            and connection.observability_trace_id == attempt.trace_id
        ):
            return connection
        return None

    def exchange_connection_for_transport(self, *, attempt_id: str) -> Connection | None:
        owner = self._owner()
        key = (owner, attempt_id)
        attempt = self.get_attempt(attempt_id)
        if attempt.mode != "connect":
            raise BlueWayNotFoundError("Integration resource not found")
        if attempt.state == "approved":
            connection = self._approved_connection(attempt)
            if connection is None:
                raise BlueWayNotFoundError("Integration resource not found")
            return connection
        if attempt.state != "pending":
            return None
        with self._lock:
            if key in self._exchanging_attempts:
                raise CourseConflictError("BlueWay pairing is already being completed")
            if self._repository().visible_connection() is not None:
                raise CourseConflictError("Disconnect BlueWay before exchanging a replacement pairing")
            self._exchanging_attempts.add(key)
        try:
            attempt = self.get_attempt(attempt_id)
            if attempt.state != "pending":
                if attempt.state == "approved":
                    connection = self._approved_connection(attempt)
                    if connection is None:
                        raise BlueWayNotFoundError("Integration resource not found")
                    return connection
                return None
            with identity_write_lock():
                self._assert_owner_current(owner)
                if self._repository().visible_connection() is not None:
                    raise CourseConflictError("Disconnect BlueWay before exchanging a replacement pairing")
            try:
                exchange = self.transport.exchange(
                    request_id=attempt.request_id, device_code=attempt.device_code, code_verifier=attempt.verifier
                )
            except BlueWayAuthorizationPending:
                raise
            except Exception as exc:
                expired = time.time() >= attempt.expires_at
                terminal_state = "expired" if expired else "failed"
                self._transition_attempt(
                    attempt,
                    terminal_state,
                    error_code="expired" if expired else type(exc).__name__,
                )
                emit_blueway_event(
                    (
                        "blueway_pairing_expired"
                        if expired
                        else "blueway_pairing_approval_rejected"
                    ),
                    trace_id=attempt.trace_id,
                    attempt_ref=attempt.id,
                    state_from="pending",
                    state_to=terminal_state,
                    reason_code=(
                        "request_expired" if expired else safe_transport_reason(exc)
                    ),
                    outcome="terminal" if expired else "rejected",
                )
                raise
            try:
                connection = self.complete_connection_for_transport(attempt_id=attempt_id, exchange=exchange)
            except Exception:
                # The owner can be disabled while the provider is responding.
                # Do not retain the new remote grant if its local authority can
                # no longer be committed under the current account record.
                try:
                    self.transport.revoke(refresh_token=exchange.refresh_token)
                except Exception:
                    pass
                raise
            emit_blueway_event(
                "blueway_pairing_approval_received",
                trace_id=attempt.trace_id,
                attempt_ref=attempt.id,
                connection_ref=connection.id,
                state_from="pending",
                state_to="approved",
                outcome="success",
            )
            emit_blueway_event(
                "blueway_pairing_exchanged",
                trace_id=attempt.trace_id,
                attempt_ref=attempt.id,
                connection_ref=connection.id,
                state_from="approved",
                state_to="exchanged",
                outcome="success",
            )
            emit_blueway_event(
                "blueway_connection_created",
                trace_id=attempt.trace_id,
                attempt_ref=attempt.id,
                connection_ref=connection.id,
                state_to="active",
                outcome="success",
            )
            return connection
        finally:
            with self._lock:
                self._exchanging_attempts.discard(key)

    def poll_connection(self, *, attempt_id: str) -> tuple[Connection | None, SyncRun | None]:
        """POST-only approval poll.  Browser clients never receive token material."""
        attempt = self.get_attempt(attempt_id)
        if attempt.mode != "connect":
            raise BlueWayNotFoundError("Integration resource not found")
        if attempt.state == "approved":
            connection = self._approved_connection(attempt)
            if connection is None:
                return None, None
            emit_blueway_event(
                "blueway_pairing_replayed",
                trace_id=connection.observability_trace_id,
                attempt_ref=attempt.id,
                connection_ref=connection.id,
                state_from="exchanged",
                state_to="exchanged",
                outcome="success",
            )
            return connection, self._recover_replayed_initial_sync(connection)
        if attempt.state != "pending":
            return None, None
        try:
            connection = self.exchange_connection_for_transport(attempt_id=attempt_id)
        except BlueWayAuthorizationPending:
            return None, None
        if connection is None:
            return None, None
        run = self.queue_sync(trace_id=attempt.trace_id)
        self.schedule_sync(run)
        return connection, run

    def _recover_replayed_initial_sync(self, connection: Connection) -> SyncRun | None:
        """Retry only a missing, failed, or unscheduled initial synchronization."""

        repository = self._repository()
        existing = repository.active_run(connection.id)
        if existing is None or existing.state in {"failed", "cancelled"}:
            run = self.queue_sync(trace_id=connection.observability_trace_id)
            self.schedule_sync(run)
            return run
        if existing.state in {"queued", "fetching", "validating", "staging", "indexing"}:
            key = (connection.owner_user_id, connection.id)
            with self._lock:
                scheduled = key in self._scheduled_connections
            if not scheduled:
                self.schedule_sync(existing)
        return None

    def poll_recovery(
        self, *, attempt_id: str,
    ) -> tuple[Connection | None, SyncRun | None]:
        owner = self._owner()
        key = (owner, attempt_id)
        attempt = self.get_attempt(attempt_id)
        if attempt.mode != "recovery":
            raise BlueWayNotFoundError("Integration resource not found")
        if attempt.state == "approved":
            return self._approved_connection(attempt), None
        if attempt.state != "pending":
            return None, None
        with self._lock:
            if key in self._exchanging_attempts:
                raise CourseConflictError(
                    "BlueWay recovery is already being completed"
                )
            self._exchanging_attempts.add(key)
        try:
            attempt = self.get_attempt(attempt_id)
            if attempt.mode != "recovery":
                raise BlueWayNotFoundError("Integration resource not found")
            if attempt.state != "pending":
                return None, None
            try:
                exchange = self.transport.exchange(
                    request_id=attempt.request_id,
                    device_code=attempt.device_code,
                    code_verifier=attempt.verifier,
                )
            except BlueWayAuthorizationPending:
                return None, None
            except Exception as exc:
                current = self.get_attempt(attempt_id)
                if current.state == "pending":
                    expired = time.time() >= current.expires_at
                    terminal_state = "expired" if expired else "failed"
                    self._transition_attempt(
                        current,
                        terminal_state,
                        error_code="expired" if expired else type(exc).__name__,
                    )
                    emit_blueway_event(
                        (
                            "blueway_pairing_expired"
                            if expired
                            else "blueway_pairing_approval_rejected"
                        ),
                        trace_id=current.trace_id,
                        attempt_ref=current.id,
                        connection_ref=current.recovery_connection_id,
                        state_from="pending",
                        state_to=terminal_state,
                        reason_code=(
                            "request_expired"
                            if expired
                            else safe_transport_reason(exc)
                        ),
                        outcome="terminal" if expired else "rejected",
                    )
                raise
            connection = self.complete_recovery_for_transport(
                attempt_id=attempt_id, exchange=exchange,
            )
            return connection, None
        finally:
            with self._lock:
                self._exchanging_attempts.discard(key)

    def cancel_attempt(self, *, attempt_id: str) -> PairingAttempt:
        """Invalidate one pending provider request before hiding its browser state."""
        attempt = self.get_attempt(attempt_id, purge_expired=False)
        if attempt.state != "pending":
            return attempt
        key = (attempt.owner_user_id, attempt.id)
        with self._lock:
            if key in self._exchanging_attempts:
                raise CourseConflictError("BlueWay pairing is already being completed")
        cancel = getattr(self.transport, "cancel", None)
        if not callable(cancel):
            raise BlueWayUnavailableError("BlueWay pairing cancellation is unavailable")
        try:
            provider_state = cancel(
                request_id=attempt.request_id, device_code=attempt.device_code,
            )
        except Exception as exc:
            raise BlueWayTransportError("BlueWay pairing cancellation failed") from exc
        terminal_state = "expired" if provider_state == "expired" else "cancelled"
        terminal = self._transition_attempt(
            attempt, terminal_state, error_code=terminal_state,
        )
        emit_blueway_event(
            (
                "blueway_pairing_expired"
                if terminal_state == "expired"
                else "blueway_pairing_cancelled"
            ),
            trace_id=terminal.trace_id,
            attempt_ref=terminal.id,
            state_from="pending",
            state_to=terminal_state,
            reason_code=(
                "request_expired" if terminal_state == "expired" else "cancelled"
            ),
            outcome="terminal",
        )
        return terminal

    def status(self) -> tuple[Connection | None, SyncRun | None]:
        if not self.settings.enabled:
            return None, None
        repository = self._repository()
        connection = repository.visible_connection()
        if (
            connection is not None
            and connection.credential_status == "healthy"
        ):
            try:
                connection, _store, _token = self._preflight_connection(
                    repository, connection,
                )
            except BlueWayCredentialRecoveryRequired:
                connection = repository.get_connection(connection.id)
        return connection, repository.active_run(connection.id) if connection else None

    def queue_sync(self, *, trace_id: str | None = None) -> SyncRun:
        repository = self._repository()
        connection = repository.active_connection()
        if connection is None:
            visible = repository.visible_connection()
            if visible is not None and visible.credential_status != "healthy":
                raise BlueWayCredentialRecoveryRequired(
                    "BlueWay credential recovery is required"
                )
            raise BlueWayNotFoundError("Integration resource not found")
        connection, _store, _refresh_token = self._preflight_connection(
            repository, connection,
        )
        run, created = repository.queue_sync_result(connection.id)
        event_trace = trace_id or connection.observability_trace_id
        if event_trace:
            if not created and run.state in {
                "queued", "fetching", "validating", "staging", "indexing",
            }:
                emit_blueway_event(
                    "blueway_sync_duplicate_suppressed",
                    trace_id=event_trace,
                    connection_ref=connection.id,
                    sync_ref=run.id,
                    state_to=run.state,
                    reason_code="active_run_exists",
                    outcome="suppressed",
                )
            else:
                emit_blueway_event(
                    "blueway_sync_requested",
                    trace_id=event_trace,
                    connection_ref=connection.id,
                    sync_ref=run.id,
                    state_to=run.state,
                    outcome="accepted",
                )
        return run

    def schedule_sync(self, run: SyncRun) -> None:
        """At most three process workers and one worker per owner connection."""
        connection = self._repository().get_connection(run.connection_id, active_only=True)
        key = (connection.owner_user_id, connection.id)
        with self._lock:
            if key in self._scheduled_connections:
                return
            self._scheduled_connections.add(key)

        def worker() -> None:
            try:
                self._run_queued_sync_for_owner(owner_user_id=connection.owner_user_id, run_id=run.id)
            finally:
                with self._lock:
                    self._scheduled_connections.discard(key)

        try:
            self._executor.submit(worker)
        except Exception:
            with self._lock:
                self._scheduled_connections.discard(key)
            raise

    def run_queued_sync(self, *, run_id: str) -> SyncRun:
        """Deterministic single-process worker; callers inject a transport in tests.

        Each persistence step rechecks the current owner-bound connection and
        generation through repository methods. No browser input supplies IDs or
        tokens, and no transcript/provider indexing is invoked here.
        """
        return self._run_queued_sync_with_repository(repository=self._repository(), run_id=run_id)

    def _run_queued_sync_for_owner(self, *, owner_user_id: str, run_id: str) -> SyncRun:
        return self._run_queued_sync_with_repository(
            repository=self._repository_for_owner(owner_user_id), run_id=run_id
        )

    def _run_queued_sync_with_repository(self, *, repository: BlueWayRepository, run_id: str) -> SyncRun:
        run = repository.get_run(run_id)
        connection: Connection | None = None

        def transition(next_state: str) -> SyncRun:
            nonlocal run
            previous_state = run.state
            run = repository.transition_run(run.id, state=next_state)
            if connection is not None and connection.observability_trace_id:
                emit_blueway_event(
                    "blueway_sync_state_changed",
                    trace_id=connection.observability_trace_id,
                    connection_ref=connection.id,
                    sync_ref=run.id,
                    state_from=previous_state,
                    state_to=run.state,
                    outcome="in_progress",
                )
            return run

        try:
            connection = repository.get_connection(run.connection_id, active_only=True)
            if connection.grant_generation != run.expected_generation:
                raise CourseConflictError("BlueWay sync run is stale or no longer writable")
            self._assert_owner_current(connection.owner_user_id)
            connection, store, primary_refresh_token = (
                self._preflight_connection(repository, connection)
            )
            rotation_id = repository.prepare_rotation(connection.id, expected_generation=run.expected_generation)
            try:
                refresh_token = store.read_rotation_envelope(
                    owner_user_id=connection.owner_user_id, connection_id=connection.id,
                    scope_version=connection.scope_version, expected_rotation_request_id=rotation_id,
                )
            except CredentialError as exc:
                repository.require_credential_recovery(
                    connection.id, expected_revision=connection.revision,
                )
                raise BlueWayCredentialRecoveryRequired(
                    "BlueWay credential recovery is required"
                ) from exc
            if refresh_token is None:
                refresh_token = primary_refresh_token
                store.write_rotation_envelope(
                    owner_user_id=connection.owner_user_id, connection_id=connection.id,
                    scope_version=connection.scope_version, refresh_token=refresh_token,
                    rotation_request_id=rotation_id,
                )
            tokens = self.transport.refresh(refresh_token=refresh_token, rotation_request_id=rotation_id)
            # The replacement is atomically encrypted before forgetting the old
            # receipt; a lost response reuses the durable request id for <=60s.
            store.write(owner_user_id=connection.owner_user_id, connection_id=connection.id, scope_version=connection.scope_version, refresh_token=tokens.refresh_token)
            repository.clear_rotation(connection.id, expected_generation=run.expected_generation, request_id=rotation_id)
            store.clear_rotation_envelope(connection.id)
            transition("fetching")
            snapshot = self.transport.fetch_snapshot(access_token=tokens.access_token, cursor=None)
            validate_snapshot(snapshot)
            if not bool(snapshot.get("complete")) or snapshot.get("next_cursor") is not None:
                raise SnapshotValidationError("BlueWay beta requires one complete stable snapshot")
            self._assert_owner_current(connection.owner_user_id)
            transition("validating")
            transition("staging")
            previous_state = run.state
            completed = repository.apply_verified_snapshot(run.id, snapshot)
            run = completed
            if connection.observability_trace_id and completed.state != previous_state:
                emit_blueway_event(
                    "blueway_sync_state_changed",
                    trace_id=connection.observability_trace_id,
                    connection_ref=connection.id,
                    sync_ref=run.id,
                    state_from=previous_state,
                    state_to=completed.state,
                    outcome="in_progress" if completed.state != "completed" else "completed",
                )
            if completed.state == "completed":
                if connection.observability_trace_id:
                    emit_blueway_event(
                        "blueway_sync_completed",
                        trace_id=connection.observability_trace_id,
                        connection_ref=connection.id,
                        sync_ref=completed.id,
                        state_from=previous_state,
                        state_to="completed",
                        outcome="success",
                    )
                return completed
            self._assert_owner_current(connection.owner_user_id)
            materialize_course_bundles(
                repository, connection=connection, snapshot_id=str(snapshot["snapshot_id"]),
                assert_owner_current=lambda: self._assert_owner_current(connection.owner_user_id),
            )
            # ``materialize_course_bundles`` checks the owner while holding the
            # identity lock around the final ready transition.  Once that
            # transition wins, finish its matching run bookkeeping without a
            # second owner check: an account disable is allowed to win next,
            # but must not turn an already-visible bundle into a failed run.
            finished = repository.complete_materialization(completed.id)
            if connection.observability_trace_id:
                emit_blueway_event(
                    "blueway_sync_state_changed",
                    trace_id=connection.observability_trace_id,
                    connection_ref=connection.id,
                    sync_ref=finished.id,
                    state_from="indexing",
                    state_to="completed",
                    outcome="completed",
                )
                emit_blueway_event(
                    "blueway_sync_completed",
                    trace_id=connection.observability_trace_id,
                    connection_ref=connection.id,
                    sync_ref=finished.id,
                    state_from="indexing",
                    state_to="completed",
                    outcome="success",
                )
            return finished
        except BlueWayAuthorityError:
            previous_state = run.state
            repository.require_repair(
                connection.id, expected_generation=run.expected_generation,
            )
            terminal = repository.get_run(run.id)
            if connection is not None and connection.observability_trace_id:
                emit_blueway_event(
                    "blueway_sync_failed",
                    trace_id=connection.observability_trace_id,
                    connection_ref=connection.id,
                    sync_ref=terminal.id,
                    state_from=previous_state,
                    state_to=terminal.state,
                    reason_code="provider_authority_lost",
                    outcome="terminal",
                )
            store.remove(connection.id)
            raise
        except BlueWayCredentialRecoveryRequired:
            terminal = repository.get_run(run.id)
            if connection is not None and connection.observability_trace_id:
                emit_blueway_event(
                    "blueway_sync_failed",
                    trace_id=connection.observability_trace_id,
                    connection_ref=connection.id,
                    sync_ref=terminal.id,
                    state_from=run.state,
                    state_to=terminal.state,
                    reason_code="credential_recovery_required",
                    outcome="terminal",
                )
            raise
        except (
            BlueWayTransportError, SnapshotValidationError, ValueError, CourseConflictError,
            BundleMaterializationError, BlueWayUnavailableError,
        ) as exc:
            failed = repository.fail_run(run.id, error_code=type(exc).__name__)
            if connection is not None and connection.observability_trace_id:
                emit_blueway_event(
                    "blueway_sync_failed",
                    trace_id=connection.observability_trace_id,
                    connection_ref=connection.id,
                    sync_ref=failed.id,
                    state_from=run.state,
                    state_to=failed.state,
                    reason_code=safe_transport_reason(exc),
                    outcome=("failed" if failed.state == "failed" else "terminal"),
                )
            raise

    def get_run(self, run_id: str) -> SyncRun:
        return self._repository().get_run(run_id)

    def unlinked_records(self) -> list[dict[str, Any]]:
        repository = self._repository()
        connection = repository.active_connection()
        if connection is None:
            return []
        return repository.list_unlinked(connection.id)

    def disconnect(self, *, expected_revision: int) -> Connection:
        repository = self._repository()
        connection = repository.visible_connection()
        if connection is None:
            raise BlueWayNotFoundError("Integration resource not found")
        connection, store, refresh_token = self._preflight_connection(
            repository, connection,
        )
        if connection.state == "active":
            connection = repository.begin_disconnect(connection.id, expected_revision=expected_revision)
        elif connection.state != "revocation_pending" or connection.revision != expected_revision:
            raise CourseConflictError("BlueWay connection revision is stale")
        # The local generation is already fenced. On remote failure the pending
        # row and encrypted credential are retained solely for this retry.
        try:
            self.transport.revoke(refresh_token=refresh_token)
        except Exception as exc:
            emit_blueway_event(
                "blueway_connection_revoke_failed",
                trace_id=connection.observability_trace_id,
                connection_ref=connection.id,
                state_from="revocation_pending",
                state_to="revocation_pending",
                reason_code=safe_transport_reason(exc),
                outcome="failed",
            )
            raise
        disconnected = repository.complete_disconnect(connection.id, expected_revision=connection.revision)
        store.remove(connection.id)
        return disconnected

    def reconcile_owner(self, owner_user_id: str) -> dict[str, int]:
        """Startup-only repair: retry fenced revocations and remove safe orphans."""
        repository = self._repository_for_owner(owner_user_id)
        # Legacy Phase 3 bundles may predate the Course-source fingerprint in
        # their derived deterministic index. Rebuild only from an immutable raw
        # bundle whose bytes and embedded Course identity match the owned source
        # receipt. This does not require or refresh BlueWay authority.
        reconcile_ready_bundle_indexes(repository)
        if not self.settings.enabled:
            return {"revoked": 0, "orphans": 0, "interrupted": 0}
        store = self._credential_store(owner_user_id)
        visible = repository.visible_connection()
        if visible is not None:
            if visible.credential_status != "healthy":
                return {"revoked": 0, "orphans": 0, "interrupted": 0}
            try:
                self._preflight_connection(repository, visible)
            except BlueWayCredentialRecoveryRequired:
                return {"revoked": 0, "orphans": 0, "interrupted": 0}
        revoked = 0
        for connection in repository.pending_connections():
            try:
                token = store.read(owner_user_id=owner_user_id, connection_id=connection.id, scope_version=connection.scope_version)
                self.transport.revoke(refresh_token=token)
                disconnected = repository.complete_disconnect(
                    connection.id, expected_revision=connection.revision,
                )
                store.remove(connection.id)
                emit_blueway_event(
                    "blueway_connection_revoked",
                    trace_id=disconnected.observability_trace_id,
                    connection_ref=disconnected.id,
                    state_from="revocation_pending",
                    state_to="disconnected",
                    outcome="success",
                )
                revoked += 1
            except (CredentialError, BlueWayTransportError, OSError) as exc:
                # Pending remains a hard local fence; startup never reactivates it.
                emit_blueway_event(
                    "blueway_connection_revoke_failed",
                    trace_id=connection.observability_trace_id,
                    connection_ref=connection.id,
                    state_from="revocation_pending",
                    state_to="revocation_pending",
                    reason_code=safe_transport_reason(exc),
                    outcome="failed",
                )
                continue
        known = repository.credential_connection_ids()
        orphans = 0
        for connection_id in store.connection_ids() - known:
            store.remove(connection_id)
            orphans += 1
        return {"revoked": revoked, "orphans": orphans, "interrupted": repository.reconcile_interrupted_runs()}

    def reconcile_startup(self) -> dict[str, int]:
        """Enumerate only local private workspaces; pending rows remain fenced on failure."""
        if not self.settings.enabled:
            return {"revoked": 0, "orphans": 0, "interrupted": 0}
        from deeptutor.multi_user.models import LOCAL_ADMIN_ID
        from deeptutor.multi_user.paths import USERS_ROOT

        owners = {LOCAL_ADMIN_ID}
        try:
            owners.update(path.name for path in USERS_ROOT.iterdir() if path.is_dir() and not path.is_symlink())
        except OSError:
            pass
        totals = {"revoked": 0, "orphans": 0, "interrupted": 0}
        for owner in owners:
            try:
                result = self.reconcile_owner(owner)
            except (OSError, CredentialError):
                continue
            for key, value in result.items():
                totals[key] += value
        return totals

_runtime_service: BlueWayService | None = None
_runtime_service_lock = threading.Lock()


def build_blueway_service() -> BlueWayService:
    """One process-owned attempt registry; routers must not recreate it per call."""
    global _runtime_service
    with _runtime_service_lock:
        if _runtime_service is not None:
            return _runtime_service
        try:
            _runtime_service = BlueWayService(BlueWaySettings.from_environment())
        except IntegrationConfigurationError as exc:
            raise BlueWayUnavailableError(str(exc)) from exc
        return _runtime_service
