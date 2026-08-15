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
from .observability import emit_blueway_event, safe_pairing_trace_id, safe_transport_reason
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
    recovery_connection_id: str | None = None
    recovery_revision: int | None = None
    recovery_generation: int | None = None


class BlueWayService:
    """Thin stateful coordinator for one process and at most 50 beta profiles.

    Attempts are intentionally process-local and expire in ten minutes. Durable
    authority begins only after a credential is encrypted and the connection is
    committed to the owner's Course database.
    """

    def __init__(self, settings: BlueWaySettings, transport: BlueWayTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport or HttpBlueWayTransport(settings)
        self._attempts: dict[str, PairingAttempt] = {}
        self._starting_owners: set[str] = set()
        self._completed_attempts: dict[tuple[str, str], tuple[str, float]] = {}
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

    def _preflight_connection(
        self, repository: BlueWayRepository, connection: Connection,
    ) -> tuple[Connection, CredentialStore, str]:
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
                self._purge_expired_attempts(now)
                self._assert_owner_current(owner)
                if repository.visible_connection() is not None:
                    raise CourseConflictError("Disconnect BlueWay before starting a replacement pairing")
                if owner in self._starting_owners or any(attempt.owner_user_id == owner for attempt in self._attempts.values()):
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
                    self._attempts[attempt.id] = attempt
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
                self._purge_expired_attempts(now)
                if owner in self._starting_owners or any(
                    attempt.owner_user_id == owner
                    for attempt in self._attempts.values()
                ):
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
                with self._lock:
                    self._attempts[attempt.id] = attempt
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

    def get_attempt(self, attempt_id: str) -> PairingAttempt:
        owner = self._owner()
        with self._lock:
            self._purge_expired_attempts(time.time())
            attempt = self._attempts.get(attempt_id)
        if attempt is None or attempt.owner_user_id != owner:
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
            if attempt.mode != "connect":
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
        with self._lock:
            self._attempts.pop(attempt.id, None)
        return connection

    def complete_recovery_for_transport(
        self, *, attempt_id: str, exchange: TokenExchange,
    ) -> Connection:
        """Commit only an owner-approved replacement for the exact same subject."""
        attempt = self.get_attempt(attempt_id)
        if (
            attempt.mode != "recovery"
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
                with self._lock:
                    self._attempts.pop(attempt.id, None)
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
            with self._lock:
                self._attempts.pop(attempt.id, None)
            raise
        with self._lock:
            self._attempts.pop(attempt.id, None)
        return completed

    def exchange_connection_for_transport(self, *, attempt_id: str) -> Connection:
        connection, _replayed = self._exchange_connection_for_transport(attempt_id=attempt_id)
        return connection

    def _exchange_connection_for_transport(
        self, *, attempt_id: str,
    ) -> tuple[Connection, bool]:
        """Exchange one normal pairing, atomically reporting a replay."""
        owner = self._owner()
        key = (owner, attempt_id)
        with self._lock:
            self._purge_expired_attempts(time.time())
            completed = self._completed_attempts.get(key)
            if completed:
                return self._repository().get_connection(completed[0]), True
            if key in self._exchanging_attempts:
                raise CourseConflictError("BlueWay pairing is already being completed")
            if self._repository().visible_connection() is not None:
                raise CourseConflictError("Disconnect BlueWay before exchanging a replacement pairing")
            self._exchanging_attempts.add(key)
        try:
            attempt = self.get_attempt(attempt_id)
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
            except BlueWayTransportError as exc:
                emit_blueway_event(
                    "blueway_pairing_approval_rejected",
                    trace_id=attempt.trace_id,
                    attempt_ref=attempt.id,
                    state_to="failed",
                    reason_code=safe_transport_reason(exc),
                    outcome="rejected",
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
            with self._lock:
                self._completed_attempts[key] = (connection.id, attempt.expires_at)
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
            return connection, False
        finally:
            with self._lock:
                self._exchanging_attempts.discard(key)

    def poll_connection(self, *, attempt_id: str) -> tuple[Connection | None, SyncRun | None]:
        """POST-only approval poll.  Browser clients never receive token material."""
        try:
            connection, replayed = self._exchange_connection_for_transport(attempt_id=attempt_id)
        except BlueWayAuthorizationPending:
            return None, None
        if replayed:
            emit_blueway_event(
                "blueway_pairing_replayed",
                trace_id=connection.observability_trace_id,
                attempt_ref=attempt_id,
                connection_ref=connection.id,
                state_from="exchanged",
                state_to="exchanged",
                outcome="success",
            )
            return connection, None
        run = self.queue_sync(trace_id=connection.observability_trace_id)
        self.schedule_sync(run)
        return connection, run

    def poll_recovery(
        self, *, attempt_id: str,
    ) -> tuple[Connection | None, SyncRun | None]:
        owner = self._owner()
        key = (owner, attempt_id)
        with self._lock:
            self._purge_expired_attempts(time.time())
            completed = self._completed_attempts.get(key)
            if completed:
                return self._repository().get_connection(completed[0]), None
            if key in self._exchanging_attempts:
                raise CourseConflictError(
                    "BlueWay recovery is already being completed"
                )
            self._exchanging_attempts.add(key)
        try:
            attempt = self.get_attempt(attempt_id)
            if attempt.mode != "recovery":
                raise BlueWayNotFoundError("Integration resource not found")
            try:
                exchange = self.transport.exchange(
                    request_id=attempt.request_id,
                    device_code=attempt.device_code,
                    code_verifier=attempt.verifier,
                )
            except BlueWayAuthorizationPending:
                return None, None
            connection = self.complete_recovery_for_transport(
                attempt_id=attempt_id, exchange=exchange,
            )
            with self._lock:
                self._completed_attempts[key] = (
                    connection.id, attempt.expires_at,
                )
            return connection, None
        finally:
            with self._lock:
                self._exchanging_attempts.discard(key)

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
        self._preflight_connection(repository, connection)
        existing = repository.active_run(connection.id)
        run = repository.queue_sync(connection.id)
        event_trace = trace_id or connection.observability_trace_id
        if event_trace:
            if existing is not None and existing.id == run.id and run.state in {
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

        self._executor.submit(worker)

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
            self._assert_owner_current(connection.owner_user_id)
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
            if connection is not None and connection.observability_trace_id:
                emit_blueway_event(
                    "blueway_sync_failed",
                    trace_id=connection.observability_trace_id,
                    connection_ref=connection.id,
                    sync_ref=run.id,
                    state_from=run.state,
                    state_to="failed",
                    reason_code="provider_authority_lost",
                    outcome="failed",
                )
            repository.require_repair(connection.id, expected_generation=run.expected_generation)
            store.remove(connection.id)
            raise
        except BlueWayCredentialRecoveryRequired:
            if connection is not None and connection.observability_trace_id:
                emit_blueway_event(
                    "blueway_sync_failed",
                    trace_id=connection.observability_trace_id,
                    connection_ref=connection.id,
                    sync_ref=run.id,
                    state_from=run.state,
                    state_to="failed",
                    reason_code="credential_recovery_required",
                    outcome="failed",
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
                    state_to="failed",
                    reason_code=safe_transport_reason(exc),
                    outcome="failed",
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
        self.transport.revoke(refresh_token=refresh_token)
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
                repository.complete_disconnect(connection.id, expected_revision=connection.revision)
                store.remove(connection.id)
                revoked += 1
            except (CredentialError, BlueWayTransportError, OSError):
                # Pending remains a hard local fence; startup never reactivates it.
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

    def _purge_expired_attempts(self, now: float) -> None:
        for key, attempt in list(self._attempts.items()):
            if attempt.expires_at <= now:
                self._attempts.pop(key, None)
                emit_blueway_event(
                    "blueway_pairing_expired",
                    trace_id=attempt.trace_id,
                    attempt_ref=attempt.id,
                    state_from="pending",
                    state_to="expired",
                    reason_code="request_expired",
                    outcome="terminal",
                )
        for key, (_connection_id, expires_at) in list(self._completed_attempts.items()):
            if expires_at <= now:
                self._completed_attempts.pop(key, None)


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
