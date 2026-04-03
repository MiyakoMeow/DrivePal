"""WebSocket ConnectionManager 单元测试."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.simulation.ws_manager import ConnectionManager


@pytest.mark.asyncio
async def test_connect_and_disconnect() -> None:
    mgr = ConnectionManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    await mgr.connect(ws1)
    await mgr.connect(ws2)
    assert len(mgr.active_connections) == 2

    mgr.disconnect(ws1)
    assert len(mgr.active_connections) == 1
    assert mgr.active_connections[0] is ws2


def test_disconnect_nonexistent_is_noop() -> None:
    mgr = ConnectionManager()
    ws = AsyncMock()
    mgr.disconnect(ws)
    assert len(mgr.active_connections) == 0


@pytest.mark.asyncio
async def test_broadcast_sends_to_all() -> None:
    mgr = ConnectionManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    await mgr.connect(ws1)
    await mgr.connect(ws2)

    msg = {"type": "test", "value": 42}
    await mgr.broadcast(msg)

    expected = json.dumps(msg, ensure_ascii=False)
    ws1.send_text.assert_awaited_once_with(expected)
    ws2.send_text.assert_awaited_once_with(expected)


@pytest.mark.asyncio
async def test_broadcast_removes_dead_connections() -> None:
    mgr = ConnectionManager()
    ws_ok = AsyncMock()
    ws_dead = AsyncMock()
    ws_dead.send_text.side_effect = RuntimeError("broken")
    await mgr.connect(ws_ok)
    await mgr.connect(ws_dead)

    await mgr.broadcast({"type": "ping"})
    assert len(mgr.active_connections) == 1
    assert mgr.active_connections[0] is ws_ok
