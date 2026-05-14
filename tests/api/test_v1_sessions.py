"""v1 sessions 路由测试."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_close_session_success(app_client: TestClient) -> None:
    """POST /api/v1/sessions/{id}/close 关闭成功."""
    with patch("app.api.v1.sessions._conversation_manager") as mock_cm:
        mock_cm.close.return_value = True
        resp = app_client.post(
            "/api/v1/sessions/sess_001/close",
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


def test_close_session_not_owner(app_client: TestClient) -> None:
    """POST /api/v1/sessions/{id}/close 非归属用户返 success=false."""
    with patch("app.api.v1.sessions._conversation_manager") as mock_cm:
        mock_cm.close.return_value = False
        resp = app_client.post(
            "/api/v1/sessions/sess_001/close",
            headers={"X-User-Id": "bob"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False
