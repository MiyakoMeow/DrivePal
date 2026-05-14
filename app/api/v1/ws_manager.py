"""WebSocket 连接管理器."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket


class WSManager:
    """管理 WebSocket 连接，支持按用户广播."""

    def __init__(self) -> None:
        self._conns: dict[str, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket, user_id: str) -> None:
        """接受连接并注册到用户连接列表."""
        await ws.accept()
        self._conns.setdefault(user_id, []).append(ws)

    def disconnect(self, ws: WebSocket, user_id: str) -> None:
        """从用户连接列表移除指定连接."""
        conns = self._conns.get(user_id, [])
        self._conns[user_id] = [c for c in conns if c is not ws]

    async def broadcast(self, user_id: str, message: dict) -> None:
        """向指定用户的所有活跃连接广播消息。发送失败时移除断连。"""
        alive = []
        for ws in self._conns.get(user_id, []):
            try:
                await ws.send_json(message)
                alive.append(ws)
            except Exception:
                pass  # 斪连，不回收
        if alive:
            self._conns[user_id] = alive
        else:
            self._conns.pop(user_id, None)

    async def send_to(self, ws: WebSocket, message: dict) -> None:
        """向单个连接发送消息."""
        await ws.send_json(message)


ws_manager = WSManager()
