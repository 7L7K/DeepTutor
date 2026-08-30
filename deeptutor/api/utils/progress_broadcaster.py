"""
Progress Broadcaster - Manages WebSocket broadcasting of knowledge base progress
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# A progress notification must never hold the shared subscription registry
# hostage to a browser that has stopped reading from its socket.
_SEND_TIMEOUT_SECONDS = 5.0


def progress_subscription_key(kb_name: str, base_dir: str | Path) -> str:
    """Return the stable broadcaster key for one resolved KB resource.

    A KB display name is only unique inside its workspace.  Broadcasting on a
    raw name allowed separate users' ``shared`` KBs to join one global socket
    room.  The resolved workspace path is the resource boundary used by the
    knowledge-access layer, so include it in the in-memory subscription key.
    """
    return f"{Path(base_dir).resolve()}::{kb_name}"


class ProgressBroadcaster:
    """Manages WebSocket broadcasting of knowledge base progress"""

    _instance: Optional["ProgressBroadcaster"] = None
    _connections: dict[str, set[WebSocket]] = {}  # resolved KB key -> Set[WebSocket]
    _lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "ProgressBroadcaster":
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def connect(self, subscription_key: str, websocket: WebSocket):
        """Connect a WebSocket to one resolved knowledge-base resource."""
        async with self._lock:
            if subscription_key not in self._connections:
                self._connections[subscription_key] = set()
            self._connections[subscription_key].add(websocket)
            logger.debug(
                "Connected WebSocket for resolved KB (total: %s)",
                len(self._connections[subscription_key]),
            )

    async def disconnect(self, subscription_key: str, websocket: WebSocket):
        """Disconnect a WebSocket from one resolved knowledge-base resource."""
        async with self._lock:
            if subscription_key in self._connections:
                self._connections[subscription_key].discard(websocket)
                if not self._connections[subscription_key]:
                    del self._connections[subscription_key]
                logger.debug("Disconnected WebSocket for resolved KB")

    async def broadcast(self, subscription_key: str, progress: dict):
        """Broadcast progress to subscribers of one resolved KB resource."""
        async with self._lock:
            # Take the registry snapshot while protected, but never await a
            # client write under this lock: another tenant's update must be
            # able to connect, disconnect, or broadcast while one browser is
            # stalled.
            connections = tuple(self._connections.get(subscription_key, ()))

        if not connections:
            return

        async def send_progress(websocket: WebSocket) -> bool:
            try:
                await asyncio.wait_for(
                    websocket.send_json({"type": "progress", "data": progress}),
                    timeout=_SEND_TIMEOUT_SECONDS,
                )
                return True
            except Exception as exc:
                # Connection closed, serialization failed, or the client did
                # not drain its send buffer before the bounded deadline.
                logger.debug("Error sending to WebSocket for resolved KB: %s", exc)
                return False

        sent = await asyncio.gather(*(send_progress(websocket) for websocket in connections))
        failed_connections = {
            websocket
            for websocket, delivered in zip(connections, sent, strict=True)
            if not delivered
        }
        if not failed_connections:
            return

        # A socket may have disconnected while writes were in flight. Re-read
        # the room under the lock and remove only failed snapshot members.
        async with self._lock:
            current_connections = self._connections.get(subscription_key)
            if current_connections is None:
                return
            current_connections.difference_update(failed_connections)
            if not current_connections:
                del self._connections[subscription_key]

    def get_connection_count(self, subscription_key: str) -> int:
        """Get connection count for one resolved knowledge-base resource."""
        return len(self._connections.get(subscription_key, set()))
