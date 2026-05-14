"""v1 路由健康检查."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_v1_routers_respond(app_client: TestClient) -> None:
    """所有 v1 子路由健康检查端点可访问。"""
    for path in (
        "/api/v1/presets/health",
        "/api/v1/sessions/health",
        "/api/v1/reminders/health",
        "/api/v1/health",  # data 路由无前缀
        "/api/v1/ws/health",
    ):
        resp = app_client.get(path)
        assert resp.status_code == 200, f"{path} failed"
