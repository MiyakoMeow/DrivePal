"""WebSocket 端点测试."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


async def _mock_run_stream(*args, **kwargs):
    """Mock run_stream 产出固定事件序列。"""
    yield {"event": "stage_start", "data": {"stage": "context"}}
    yield {"event": "context_done", "data": {"context": {"scenario": "parked"}}}
    yield {
        "event": "stage_start",
        "data": {"stage": "joint_decision"},
    }
    yield {
        "event": "decision",
        "data": {"task_type": "general", "should_remind": True},
    }
    yield {"event": "stage_start", "data": {"stage": "execution"}}
    yield {
        "event": "done",
        "data": {
            "status": "delivered",
            "event_id": "evt_001",
            "result": {"text": "提醒已发送"},
        },
    }


def test_ws_query_flow(app_client: TestClient) -> None:
    """WS 查询应流式返回各阶段事件。"""
    with patch("app.api.v1.ws.AgentWorkflow") as mock_wf:
        mock_instance = mock_wf.return_value
        mock_instance.run_stream = _mock_run_stream
        with app_client.websocket_connect(
            "/api/v1/ws", headers={"X-User-Id": "test"}
        ) as ws:
            ws.send_json({"type": "query", "payload": {"query": "明天开会"}})
            events = []
            for _ in range(6):
                raw = ws.receive_text()
                msg = json.loads(raw)
                events.append(msg["type"])
            assert "stage_start" in events
            assert "done" in events


def test_ws_ping_pong(app_client: TestClient) -> None:
    """WS ping/pong 应正确响应。"""
    with app_client.websocket_connect(
        "/api/v1/ws", headers={"X-User-Id": "test"}
    ) as ws:
        ws.send_json({"type": "ping"})
        raw = ws.receive_text()
        msg = json.loads(raw)
        assert msg["type"] == "pong"
