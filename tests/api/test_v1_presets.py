"""v1 presets 路由测试."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_list_presets_empty(app_client: TestClient) -> None:
    """GET /api/v1/presets 无预设时返空列表."""
    with patch("app.api.v1.presets._preset_store") as mock_store_fn:
        store = AsyncMock()
        store.read.return_value = []
        mock_store_fn.return_value = store
        resp = app_client.get("/api/v1/presets", headers={"X-User-Id": "alice"})
        assert resp.status_code == 200
        assert resp.json() == []


def test_save_and_list_preset(app_client: TestClient) -> None:
    """POST /api/v1/presets 保存后可列出."""
    preset_data = {
        "id": "preset_001",
        "name": "通勤",
        "context": {
            "scenario": "city_driving",
            "spatial": {},
            "temporal": {},
        },
        "created_at": "2025-01-01T00:00:00",
    }
    with patch("app.api.v1.presets._preset_store") as mock_store_fn:
        store = AsyncMock()
        store.append.return_value = None
        store.read.return_value = [preset_data]
        mock_store_fn.return_value = store
        resp = app_client.post(
            "/api/v1/presets",
            json={"name": "通勤", "context": {"scenario": "city_driving"}},
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "通勤"


def test_delete_preset_found(app_client: TestClient) -> None:
    """DELETE /api/v1/presets/{id} 存在时返 success."""
    with patch("app.api.v1.presets._preset_store") as mock_store_fn:
        store = AsyncMock()
        store.read.return_value = [{"id": "p1", "name": "x"}]
        store.write.return_value = None
        mock_store_fn.return_value = store
        resp = app_client.delete("/api/v1/presets/p1", headers={"X-User-Id": "alice"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True


def test_delete_preset_not_found(app_client: TestClient) -> None:
    """DELETE /api/v1/presets/{id} 不存在时返 success=false."""
    with patch("app.api.v1.presets._preset_store") as mock_store_fn:
        store = AsyncMock()
        store.read.return_value = [{"id": "p1", "name": "x"}]
        mock_store_fn.return_value = store
        resp = app_client.delete("/api/v1/presets/p9", headers={"X-User-Id": "alice"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False
