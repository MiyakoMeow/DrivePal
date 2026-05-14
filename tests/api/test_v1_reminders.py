"""v1 reminders 路由测试（列表 + 取消 + 轮询触发 + WS 广播）."""

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
        pm.cancel.return_value = None
        mock_pm_cls.return_value = pm
        resp = app_client.delete(
            "/api/v1/reminders/pr1",
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        pm.cancel.assert_called_once_with("pr1")


def test_poll_triggers_and_broadcasts(app_client: TestClient) -> None:
    """POST /api/v1/reminders/poll 触发提醒并经 WS 广播."""
    fake_triggered = [
        {
            "id": "pr1",
            "event_id": "e1",
            "content": {"speakable_text": "该休息了"},
            "trigger_type": "time",
            "created_at": "2025-01-01T00:00:00",
            "status": "triggered",
        },
    ]
    with (
        patch("app.api.v1.reminders.PendingReminderManager") as mock_pm_cls,
        patch("app.api.v1.reminders.ws_manager.broadcast", new=AsyncMock()) as mock_broadcast,
    ):
        pm = AsyncMock()
        pm.poll.return_value = fake_triggered
        mock_pm_cls.return_value = pm
        resp = app_client.post(
            "/api/v1/reminders/poll",
            json={"context": {"scenario": "highway"}},
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["triggered"]) == 1
        assert body["triggered"][0]["id"] == "pr1"
        mock_broadcast.assert_called_once_with(
            "alice",
            {"type": "reminder_triggered", "data": fake_triggered[0]},
        )


def test_poll_no_context_no_triggers(app_client: TestClient) -> None:
    """POST /api/v1/reminders/poll 无上下文无触发."""
    with patch("app.api.v1.reminders.PendingReminderManager") as mock_pm_cls:
        pm = AsyncMock()
        pm.poll.return_value = []
        mock_pm_cls.return_value = pm
        resp = app_client.post(
            "/api/v1/reminders/poll",
            json={},
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        assert resp.json()["triggered"] == []
