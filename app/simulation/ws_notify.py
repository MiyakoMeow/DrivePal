"""WebSocket /ws/notify 主动提醒端点."""

from __future__ import annotations

import json
import logging

from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

_active_ws: list[WebSocket] = []


async def notify_ws(websocket: WebSocket) -> None:
    """处理 /ws/notify WebSocket 连接."""
    await websocket.accept()
    _active_ws.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _active_ws:
            _active_ws.remove(websocket)


async def broadcast_reminder(reminder: dict) -> None:
    """向所有 /ws/notify 连接广播提醒消息."""
    payload = json.dumps({"type": "proactive_reminder", **reminder}, ensure_ascii=False)
    dead: list[WebSocket] = []
    for ws in _active_ws:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _active_ws:
            _active_ws.remove(ws)
