"""v1 reminders 路由测试（列表 + 取消）."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_list_pending_reminders(app_client: TestClient) -> None:
    """GET /api/v1/reminders 返回待触发列表."""
    with patch("app.api.v1.reminders.PendingReminderManager") as mock_pm_cls:
        pm = AsyncMock()
        pm.list_pending.return_value = [
            {
                "id": "pr1",
                "event_id": "e1",
                "trigger_type": "time",
                "trigger_text": "5分钟后",
                "status": "pending",
                "created_at": "2025-01-01T00:00:00",
            },
        ]
        mock_pm_cls.return_value = pm
        resp = app_client.get("/api/v1/reminders", headers={"X-User-Id": "alice"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["id"] == "pr1"


def test_cancel_reminder(app_client: TestClient) -> None:
    """DELETE /api/v1/reminders/{id} 取消提醒."""
    with patch("app.api.v1.reminders.PendingReminderManager") as mock_pm_cls:
        pm = AsyncMock()
        pm.cancel.return_value = True
        mock_pm_cls.return_value = pm
        resp = app_client.delete(
            "/api/v1/reminders/pr1",
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        pm.cancel.assert_called_once_with("pr1")


def test_poll_endpoint_removed(app_client: TestClient) -> None:
    """POST /api/v1/reminders/poll 已删除（405 或 404）."""
    resp = app_client.post(
        "/api/v1/reminders/poll",
        json={},
        headers={"X-User-Id": "alice"},
    )
    assert resp.status_code in (404, 405)
