"""v1 路由健康检查."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_v1_ws_health(app_client: TestClient) -> None:
    """v1 ws 健康检查端点可访问。"""
    resp = app_client.get("/api/v1/ws/health")
    assert resp.status_code == 200
