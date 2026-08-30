"""
Progress Broadcaster - Manages WebSocket broadcasting of knowledge base progress
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


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
            if subscription_key not in self._connections:
                return

            # Create list of connections to remove (closed connections)
            to_remove = []

            for websocket in self._connections[subscription_key]:
                try:
                    await websocket.send_json({"type": "progress", "data": progress})
                except Exception as e:
                    # Connection closed or error, mark for removal
                    logger.debug(f"Error sending to WebSocket for KB '{kb_name}': {e}")
                    to_remove.append(websocket)

            # Remove closed connections
            for ws in to_remove:
                self._connections[subscription_key].discard(ws)

            if not self._connections[subscription_key]:
                del self._connections[subscription_key]

    def get_connection_count(self, subscription_key: str) -> int:
        """Get connection count for one resolved knowledge-base resource."""
        return len(self._connections.get(subscription_key, set()))
