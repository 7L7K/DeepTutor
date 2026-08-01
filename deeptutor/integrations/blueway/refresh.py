"""Rotation-safe refresh receipt logic, kept independent from HTTP plumbing."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets
import time
from typing import Protocol


class RefreshReuseError(RuntimeError):
    pass


@dataclass(frozen=True)
class RefreshResult:
    access_token: str
    refresh_token: str


class RefreshTransport(Protocol):
    def refresh(self, *, refresh_token: str, rotation_request_id: str) -> RefreshResult: ...

    def revoke_family(self, *, refresh_token: str) -> None: ...


@dataclass(frozen=True)
class _Receipt:
    request_id: str
    expires_at: float


class RefreshReceiptCoordinator:
    """Reuse exactly one rotation request id for a short retry receipt window."""

    def __init__(self, *, now=time.time) -> None:
        self._now = now
        self._receipts: dict[tuple[str, str], _Receipt] = {}

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def refresh(self, *, connection_id: str, refresh_token: str, transport: RefreshTransport) -> RefreshResult:
        now = self._now()
        key = (connection_id, self._token_hash(refresh_token))
        receipt = self._receipts.get(key)
        if receipt is not None and receipt.expires_at < now:
            # A second attempt with an old rotating token outside the receipt
            # window signals possible reuse; revoke the family before failing.
            transport.revoke_family(refresh_token=refresh_token)
            raise RefreshReuseError("BlueWay refresh token reuse detected")
        if receipt is None:
            receipt = _Receipt(request_id=f"bwrq_{secrets.token_hex(16)}", expires_at=now + 60.0)
            self._receipts[key] = receipt
        return transport.refresh(refresh_token=refresh_token, rotation_request_id=receipt.request_id)
