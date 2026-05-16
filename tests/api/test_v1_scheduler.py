"""v1 scheduler 路由测试（trigger 端点）。"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_given_scheduler_running_when_trigger_then_returns_success(
    app_client: TestClient,
) -> None:
    """POST /api/v1/scheduler/trigger 调度器运行中时返 200 + triggered。"""
    with patch("app.api.v1.scheduler.trigger_scheduler") as mock_trigger:
        mock_trigger.return_value = True
        resp = app_client.post(
            "/api/v1/scheduler/trigger",
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "triggered"
        assert body["user_id"] == "alice"


def test_given_scheduler_not_running_when_trigger_then_returns_service_unavailable(
    app_client: TestClient,
) -> None:
    """POST /api/v1/scheduler/trigger 调度器未运行时返 503。"""
    with patch("app.api.v1.scheduler.trigger_scheduler") as mock_trigger:
        mock_trigger.return_value = False
        resp = app_client.post(
            "/api/v1/scheduler/trigger",
            headers={"X-User-Id": "bob"},
        )
        assert resp.status_code == 503
