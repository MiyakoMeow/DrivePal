"""WSManager 连接管理测试."""

from unittest.mock import AsyncMock, MagicMock

from app.api.v1.ws_manager import WSManager


async def test_connect_and_disconnect() -> None:
    """connect 后列表含该 ws，disconnect 后不含。"""
    manager = WSManager()
    ws = MagicMock()
    ws.accept = AsyncMock()
    await manager.connect(ws, "alice")
    assert ws in manager._conns["alice"]

    manager.disconnect(ws, "alice")
    assert ws not in manager._conns.get("alice", [])


async def test_broadcast_sends_to_all() -> None:
    """broadcast 向用户所有连接发送消息。"""
    manager = WSManager()
    ws1, ws2 = MagicMock(), MagicMock()
    ws1.accept = AsyncMock()
    ws2.accept = AsyncMock()
    ws1.send_json = AsyncMock()
    ws2.send_json = AsyncMock()

    await manager.connect(ws1, "alice")
    await manager.connect(ws2, "alice")
    await manager.broadcast("alice", {"type": "reminder", "payload": {}})

    ws1.send_json.assert_called_once()
    ws2.send_json.assert_called_once()


async def test_broadcast_removes_dead_conns() -> None:
    """broadcast 时发送失败的连接被移除。"""
    manager = WSManager()
    ws_alive, ws_dead = MagicMock(), MagicMock()
    ws_alive.accept = AsyncMock()
    ws_dead.accept = AsyncMock()
    ws_alive.send_json = AsyncMock()
    ws_dead.send_json = AsyncMock(side_effect=RuntimeError("disconnected"))

    await manager.connect(ws_alive, "alice")
    await manager.connect(ws_dead, "alice")
    await manager.broadcast("alice", {"type": "reminder", "payload": {}})

    assert ws_dead not in manager._conns.get("alice", [])
    assert ws_alive in manager._conns.get("alice", [])
