"""WebSocket 连接管理器."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSManager:
    """管理 WebSocket 连接，支持按用户广播."""

    def __init__(self) -> None:
        self._conns: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, user_id: str) -> None:
        """接受连接并注册到用户连接列表."""
        await ws.accept()
        async with self._lock:
            self._conns.setdefault(user_id, []).append(ws)

    async def disconnect(self, ws: WebSocket, user_id: str) -> None:
        """从用户连接列表移除指定连接，清理空列表."""
        async with self._lock:
            conns = self._conns.get(user_id, [])
            remaining = [c for c in conns if c is not ws]
            if remaining:
                self._conns[user_id] = remaining
            else:
                self._conns.pop(user_id, None)

    async def broadcast(self, user_id: str, message: dict) -> None:
        """向指定用户的所有活跃连接广播消息.

        快照连接列表防止与 disconnect 并发竞态：迭代期间
        disconnect 可能修改列表，快照保证遍历安全。
        """
        async with self._lock:
            snapshot = list(self._conns.get(user_id, []))

        alive = []
        for ws in snapshot:
            try:
                await ws.send_json(message)
                alive.append(ws)
            except Exception:
                logger.debug("WS broadcast: dropped dead conn for %s", user_id)

        async with self._lock:
            current = self._conns.get(user_id)
            if current is None:
                if alive:
                    self._conns[user_id] = alive
            else:
                dead_ids = {id(ws) for ws in snapshot if ws not in alive}
                merged = [ws for ws in current if id(ws) not in dead_ids]
                if merged:
                    self._conns[user_id] = merged
                else:
                    self._conns.pop(user_id, None)

    async def send_to(self, ws: WebSocket, message: dict) -> None:
        """向单个连接发送消息."""
        await ws.send_json(message)


ws_manager = WSManager()
