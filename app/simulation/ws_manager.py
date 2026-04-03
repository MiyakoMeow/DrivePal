"""WebSocket 连接管理器."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """管理活跃 WebSocket 连接的集合."""

    def __init__(self) -> None:
        """初始化连接管理器."""
        self.active_connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        """接受并注册 WebSocket 连接."""
        await ws.accept()
        self.active_connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        """移除 WebSocket 连接."""
        if ws in self.active_connections:
            self.active_connections.remove(ws)

    async def broadcast(self, message: dict) -> None:
        """向所有连接广播 JSON 消息，自动移除失败连接."""
        payload = json.dumps(message, ensure_ascii=False)
        dead: list[WebSocket] = []
        for ws in list(self.active_connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)
