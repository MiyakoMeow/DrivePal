"""v1 Feedback 路由测试."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_feedback_accept(app_client: TestClient) -> None:
    """POST /api/v1/feedback accept 路径。"""
    with patch("app.api.v1.feedback.get_memory_module") as mock_mm:
        mock_instance = AsyncMock()
        mock_instance.get_event_type.return_value = "meeting"
        mock_instance.update_feedback.return_value = None
        mock_mm.return_value = mock_instance
        resp = app_client.post(
            "/api/v1/feedback",
            json={"event_id": "evt_001", "action": "accept"},
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"


def test_feedback_snooze(app_client: TestClient) -> None:
    """POST /api/v1/feedback snooze 应创建 pending reminder。"""
    with patch("app.api.v1.feedback.PendingReminderManager") as mock_pm:
        mock_instance = AsyncMock()
        mock_instance.add.return_value = AsyncMock(id="pr_001")
        mock_pm.return_value = mock_instance
        resp = app_client.post(
            "/api/v1/feedback",
            json={"event_id": "evt_001", "action": "snooze"},
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        mock_instance.add.assert_called_once()


def test_feedback_modify(app_client: TestClient) -> None:
    """POST /api/v1/feedback modify 应带 modified_content。"""
    with patch("app.api.v1.feedback.get_memory_module") as mock_mm:
        mock_instance = AsyncMock()
        mock_instance.get_event_type.return_value = "meeting"
        mock_instance.update_feedback.return_value = None
        mock_mm.return_value = mock_instance
        resp = app_client.post(
            "/api/v1/feedback",
            json={
                "event_id": "evt_001",
                "action": "modify",
                "modified_content": "改后内容",
            },
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200


def test_feedback_not_found(app_client: TestClient) -> None:
    """POST /api/v1/feedback 事件不存在返 404。"""
    with patch("app.api.v1.feedback.get_memory_module") as mock_mm:
        mock_instance = AsyncMock()
        mock_instance.get_event_type.return_value = None
        mock_mm.return_value = mock_instance
        resp = app_client.post(
            "/api/v1/feedback",
            json={"event_id": "nonexistent", "action": "accept"},
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 404
