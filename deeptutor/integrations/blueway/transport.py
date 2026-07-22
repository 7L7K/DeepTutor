"""Pinned, bounded BlueWay HTTP boundary plus injectable deterministic protocol."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from .config import BlueWaySettings
from .snapshot import MAX_PAGE_BYTES


class BlueWayTransportError(RuntimeError):
    pass


class BlueWayAuthorityError(BlueWayTransportError):
    """The provider has permanently rejected the stored grant."""


class BlueWayAuthorizationPending(BlueWayTransportError):
    """A verified pairing request remains awaiting the user's approval."""


@dataclass(frozen=True)
class DeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    expires_at: float
    request_id: str


@dataclass(frozen=True)
class TokenExchange:
    grant_id: str
    external_subject: str
    access_token: str
    access_expires_at: str
    refresh_token: str


@dataclass(frozen=True)
class RefreshExchange:
    access_token: str
    access_expires_at: str
    refresh_token: str


class BlueWayTransport(Protocol):
    def begin_device_authorization(self, *, client_id: str, audience: str, device_code: str, user_code: str, pkce_challenge: str) -> DeviceAuthorization: ...
    def exchange(self, *, request_id: str, device_code: str, code_verifier: str) -> TokenExchange: ...
    def refresh(self, *, refresh_token: str, rotation_request_id: str) -> RefreshExchange: ...
    def fetch_snapshot(self, *, access_token: str, cursor: str | None) -> dict[str, Any]: ...
    def revoke(self, *, refresh_token: str) -> None: ...


class HttpBlueWayTransport:
    """Synchronous server-only client: HTTPS, exact host, no redirects, bounded bytes."""

    def __init__(self, settings: BlueWaySettings, *, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client or httpx.Client(timeout=httpx.Timeout(10.0), follow_redirects=False, trust_env=False)

    @staticmethod
    def _content_length(response: httpx.Response) -> int:
        raw = response.headers.get("content-length")
        if raw is None:
            return 0
        try:
            value = int(raw)
        except ValueError as exc:
            raise BlueWayTransportError("BlueWay response content length is invalid") from exc
        if value < 0:
            raise BlueWayTransportError("BlueWay response content length is invalid")
        return value

    def _pairing(self, body: dict[str, str]) -> dict[str, Any]:
        try:
            with self._client.stream("POST", f"{self.settings.base_url}/functions/v1/teeechr-pairing", headers={"apikey": self.settings.api_secret}, json=body) as response:
                return self._json_stream(response)
        except httpx.HTTPError as exc:
            raise BlueWayTransportError("BlueWay pairing transport failed") from exc

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 401:
            raise BlueWayAuthorityError("BlueWay grant is no longer authorized")
        if response.is_redirect or response.status_code < 200 or response.status_code >= 300:
            raise BlueWayTransportError("BlueWay rejected the integration request")
        if HttpBlueWayTransport._content_length(response) > MAX_PAGE_BYTES:
            raise BlueWayTransportError("BlueWay response exceeds the byte limit")
        raw = response.content
        if len(raw) > MAX_PAGE_BYTES:
            raise BlueWayTransportError("BlueWay response exceeds the byte limit")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BlueWayTransportError("BlueWay response is not JSON") from exc
        if not isinstance(value, dict):
            raise BlueWayTransportError("BlueWay response shape is invalid")
        return value

    @staticmethod
    def _json_stream(response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 401:
            raise BlueWayAuthorityError("BlueWay grant is no longer authorized")
        if response.is_redirect or response.status_code < 200 or response.status_code >= 300:
            raise BlueWayTransportError("BlueWay rejected the integration request")
        if HttpBlueWayTransport._content_length(response) > MAX_PAGE_BYTES:
            raise BlueWayTransportError("BlueWay response exceeds the byte limit")
        chunks, total = [], 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > MAX_PAGE_BYTES:
                raise BlueWayTransportError("BlueWay response exceeds the byte limit")
            chunks.append(chunk)
        try:
            value = json.loads(b"".join(chunks))
        except json.JSONDecodeError as exc:
            raise BlueWayTransportError("BlueWay response is not JSON") from exc
        if not isinstance(value, dict):
            raise BlueWayTransportError("BlueWay response shape is invalid")
        return value

    def begin_device_authorization(self, *, client_id: str, audience: str, device_code: str, user_code: str, pkce_challenge: str) -> DeviceAuthorization:
        payload = self._pairing({"action": "start", "client_id": client_id, "audience": audience, "device_code": device_code, "user_code": user_code, "code_challenge": pkce_challenge})
        request_id, expires_at = payload.get("request_id"), payload.get("expires_at")
        if not isinstance(request_id, str) or not isinstance(expires_at, str):
            raise BlueWayTransportError("BlueWay pairing response is invalid")
        try:
            timestamp = __import__("datetime").datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
        except ValueError as exc:
            raise BlueWayTransportError("BlueWay pairing expiry is invalid") from exc
        uri = f"{self.settings.approval_url}?{urlencode({'request_id': request_id, 'user_code': user_code})}"
        return DeviceAuthorization(device_code, user_code, uri, timestamp, request_id)

    def _exchange(self, payload: dict[str, Any]) -> TokenExchange:
        grant_id, subject = payload.get("grant_id"), payload.get("external_subject")
        tokens = [payload.get(key) for key in ("access_token", "access_expires_at", "refresh_token")]
        if not isinstance(grant_id, str) or not isinstance(subject, str) or not all(isinstance(token, str) and token for token in tokens):
            raise BlueWayTransportError("BlueWay token exchange response is invalid")
        return TokenExchange(grant_id, subject, tokens[0], tokens[1], tokens[2])

    def exchange(self, *, request_id: str, device_code: str, code_verifier: str) -> TokenExchange:
        payload = self._pairing({"action": "exchange", "request_id": request_id, "device_code": device_code, "code_verifier": code_verifier})
        if payload == {"error": "authorization_pending"}:
            raise BlueWayAuthorizationPending("BlueWay approval is still pending")
        return self._exchange(payload)

    def refresh(self, *, refresh_token: str, rotation_request_id: str) -> RefreshExchange:
        payload = self._pairing({"action": "refresh", "refresh_token": refresh_token, "rotation_request_id": rotation_request_id})
        tokens = [payload.get(key) for key in ("access_token", "access_expires_at", "refresh_token")]
        if not all(isinstance(token, str) and token for token in tokens):
            raise BlueWayTransportError("BlueWay refresh response is invalid")
        return RefreshExchange(tokens[0], tokens[1], tokens[2])

    def fetch_snapshot(self, *, access_token: str, cursor: str | None) -> dict[str, Any]:
        params = {"cursor": cursor} if cursor else None
        try:
            with self._client.stream("GET", f"{self.settings.base_url}/functions/v1/teeechr-export", headers={"Authorization": f"Bearer {access_token}"}, params=params) as response:
                if response.is_redirect or response.status_code != 200:
                    if response.status_code == 401:
                        raise BlueWayAuthorityError("BlueWay grant is no longer authorized")
                    raise BlueWayTransportError("BlueWay export was rejected")
                if self._content_length(response) > MAX_PAGE_BYTES:
                    raise BlueWayTransportError("BlueWay response exceeds the byte limit")
                chunks, total = [], 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_PAGE_BYTES:
                        raise BlueWayTransportError("BlueWay response exceeds the byte limit")
                    chunks.append(chunk)
            value = json.loads(b"".join(chunks))
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise BlueWayTransportError("BlueWay export transport failed") from exc
        if not isinstance(value, dict):
            raise BlueWayTransportError("BlueWay export response shape is invalid")
        return value

    def revoke(self, *, refresh_token: str) -> None:
        self._pairing({"action": "revoke_refresh", "refresh_token": refresh_token})
