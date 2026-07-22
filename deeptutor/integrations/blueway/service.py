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

from .bundles import BundleMaterializationError, materialize_course_bundles
from .config import BlueWaySettings, IntegrationConfigurationError
from .credentials import CredentialError, CredentialStore
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
        # Identity -> service registry is the required lock order. Exchange
        # completion follows it while acquiring the same locks reentrantly.
        with identity_write_lock():
            self._assert_owner_current(owner)
            with self._lock:
                now = time.time()
                self._purge_expired_attempts(now)
                self._assert_owner_current(owner)
                if repository.visible_connection() is not None:
                    raise CourseConflictError("Disconnect BlueWay before starting a replacement pairing")
                if any(attempt.owner_user_id == owner for attempt in self._attempts.values()):
                    raise CourseConflictError("BlueWay pairing is already pending")
                # Keep the process lock through the provider start.  This is a
                # deliberate small critical section: it prevents a second device
                # grant from being created before the first one has local state.
                verifier = self._verifier()
                device_code, user_code = self._device_code(), self._user_code()
                authorization = self.transport.begin_device_authorization(
                    client_id=self.settings.client_id, audience=self.settings.client_id, device_code=device_code,
                    user_code=user_code, pkce_challenge=self._challenge(verifier),
                )
                if authorization.expires_at <= now or not authorization.device_code or not authorization.user_code:
                    raise BlueWayUnavailableError("BlueWay returned an invalid device authorization")
                attempt = PairingAttempt(
                    id=f"bwa_{secrets.token_hex(16)}", owner_user_id=owner,
                    device_code=device_code, verifier=verifier,
                    user_code=authorization.user_code, verification_uri=authorization.verification_uri,
                    expires_at=authorization.expires_at, request_id=authorization.request_id,
                )
                self._attempts[attempt.id] = attempt
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
                )
            except Exception:
                store.remove(provisional_id)
                raise
        with self._lock:
            self._attempts.pop(attempt.id, None)
        return connection

    def exchange_connection_for_transport(self, *, attempt_id: str) -> Connection:
        owner = self._owner()
        key = (owner, attempt_id)
        with self._lock:
            self._purge_expired_attempts(time.time())
            completed = self._completed_attempts.get(key)
            if completed:
                return self._repository().get_connection(completed[0])
            if key in self._exchanging_attempts:
                raise CourseConflictError("BlueWay pairing is already being completed")
            if self._repository().visible_connection() is not None:
                raise CourseConflictError("Disconnect BlueWay before exchanging a replacement pairing")
            self._exchanging_attempts.add(key)
        try:
            attempt = self.get_attempt(attempt_id)
            # Identity -> provider -> credential/SQLite is one local authority
            # interval.  A disable/delete mutation uses the same identity lock.
            with identity_write_lock():
                self._assert_owner_current(owner)
                if self._repository().visible_connection() is not None:
                    raise CourseConflictError("Disconnect BlueWay before exchanging a replacement pairing")
                exchange = self.transport.exchange(
                    request_id=attempt.request_id, device_code=attempt.device_code, code_verifier=attempt.verifier
                )
                connection = self.complete_connection_for_transport(attempt_id=attempt_id, exchange=exchange)
            with self._lock:
                self._completed_attempts[key] = (connection.id, attempt.expires_at)
            return connection
        finally:
            with self._lock:
                self._exchanging_attempts.discard(key)

    def poll_connection(self, *, attempt_id: str) -> tuple[Connection | None, SyncRun | None]:
        """POST-only approval poll.  Browser clients never receive token material."""
        try:
            connection = self.exchange_connection_for_transport(attempt_id=attempt_id)
        except BlueWayAuthorizationPending:
            return None, None
        run = self.queue_sync()
        self.schedule_sync(run)
        return connection, run

    def status(self) -> tuple[Connection | None, SyncRun | None]:
        if not self.settings.enabled:
            return None, None
        repository = self._repository()
        connection = repository.visible_connection()
        return connection, repository.active_run(connection.id) if connection else None

    def queue_sync(self) -> SyncRun:
        repository = self._repository()
        connection = repository.active_connection()
        if connection is None:
            raise BlueWayNotFoundError("Integration resource not found")
        return repository.queue_sync(connection.id)

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
        try:
            connection = repository.get_connection(run.connection_id, active_only=True)
            if connection.grant_generation != run.expected_generation:
                raise CourseConflictError("BlueWay sync run is stale or no longer writable")
            self._assert_owner_current(connection.owner_user_id)
            paths = get_personal_path_service(connection.owner_user_id)
            store = CredentialStore(paths.get_integration_credentials_dir(), self.settings.master_key)
            rotation_id = repository.prepare_rotation(connection.id, expected_generation=run.expected_generation)
            try:
                refresh_token = store.read_rotation_envelope(
                    owner_user_id=connection.owner_user_id, connection_id=connection.id,
                    scope_version=connection.scope_version, expected_rotation_request_id=rotation_id,
                )
            except CredentialError:
                raise
            if refresh_token is None:
                refresh_token = store.read(owner_user_id=connection.owner_user_id, connection_id=connection.id, scope_version=connection.scope_version)
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
            repository.transition_run(run.id, state="fetching")
            snapshot = self.transport.fetch_snapshot(access_token=tokens.access_token, cursor=None)
            validate_snapshot(snapshot)
            if not bool(snapshot.get("complete")) or snapshot.get("next_cursor") is not None:
                raise SnapshotValidationError("BlueWay beta requires one complete stable snapshot")
            self._assert_owner_current(connection.owner_user_id)
            repository.transition_run(run.id, state="validating")
            repository.transition_run(run.id, state="staging")
            completed = repository.apply_verified_snapshot(run.id, snapshot)
            if completed.state == "completed":
                return completed
            self._assert_owner_current(connection.owner_user_id)
            materialize_course_bundles(
                repository, connection=connection, snapshot_id=str(snapshot["snapshot_id"]),
                assert_owner_current=lambda: self._assert_owner_current(connection.owner_user_id),
            )
            self._assert_owner_current(connection.owner_user_id)
            return repository.complete_materialization(completed.id)
        except BlueWayAuthorityError:
            repository.require_repair(connection.id, expected_generation=run.expected_generation)
            store.remove(connection.id)
            raise
        except (
            BlueWayTransportError, SnapshotValidationError, ValueError, CourseConflictError,
            CredentialError, BundleMaterializationError, BlueWayUnavailableError,
        ) as exc:
            repository.fail_run(run.id, error_code=type(exc).__name__)
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
        paths = get_personal_path_service(connection.owner_user_id)
        store = CredentialStore(paths.get_integration_credentials_dir(), self.settings.master_key)
        if connection.state == "active":
            connection = repository.begin_disconnect(connection.id, expected_revision=expected_revision)
        elif connection.state != "revocation_pending" or connection.revision != expected_revision:
            raise CourseConflictError("BlueWay connection revision is stale")
        # The local generation is already fenced. On remote failure the pending
        # row and encrypted credential are retained solely for this retry.
        refresh_token = store.read(owner_user_id=connection.owner_user_id, connection_id=connection.id,
                                   scope_version=connection.scope_version)
        self.transport.revoke(refresh_token=refresh_token)
        disconnected = repository.complete_disconnect(connection.id, expected_revision=connection.revision)
        store.remove(connection.id)
        return disconnected

    def reconcile_owner(self, owner_user_id: str) -> dict[str, int]:
        """Startup-only repair: retry fenced revocations and remove safe orphans."""
        if not self.settings.enabled:
            return {"revoked": 0, "orphans": 0, "interrupted": 0}
        repository = self._repository_for_owner(owner_user_id)
        paths = get_personal_path_service(owner_user_id)
        store = CredentialStore(paths.get_integration_credentials_dir(), self.settings.master_key)
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
