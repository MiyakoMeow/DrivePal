"""v1 metrics 路由测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_get_metrics(app_client: TestClient) -> None:
    """GET /api/v1/metrics 返回 MemoryBank 指标。"""
    with patch("app.api.v1.data.get_memory_module") as mock_mm:
        mock_mm.return_value.get_metrics.return_value = {
            "search_count": 5,
            "search_latency_ms": 12.3,
            "search_empty_index_count": 1,
            "search_empty_count": 0,
            "forget_count": 0,
            "forget_removed_count": 0,
            "write_count": 10,
            "write_latency_ms": 8.1,
            "embedding_latency_ms": 45.2,
            "background_task_failures": 0,
            "index_load_warnings": 0,
        }
        resp = app_client.get("/api/v1/metrics", headers={"X-User-Id": "alice"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["search_count"] == 5
        assert body["write_count"] == 10


def test_get_metrics_uninitialized(app_client: TestClient) -> None:
    """GET /api/v1/metrics store 未初始化时返全零。"""
    with patch("app.api.v1.data.get_memory_module") as mock_mm:
        mock_mm.return_value.get_metrics.return_value = None
        resp = app_client.get("/api/v1/metrics", headers={"X-User-Id": "bob"})
        assert resp.status_code == 200
        body = resp.json()
        assert all(v == 0 for v in body.values())
