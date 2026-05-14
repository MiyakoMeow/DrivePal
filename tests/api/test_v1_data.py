"""v1 data 路由测试."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


def test_history(app_client: TestClient) -> None:
    """GET /api/v1/history 返回历史事件."""
    from app.memory.schemas import MemoryEvent

    events = [
        MemoryEvent(
            id="e1",
            content="开会提醒",
            type="meeting",
            description="明天会议",
            created_at="2025-01-01T00:00:00",
        ),
    ]
    with patch("app.api.v1.data.get_memory_module") as mock_mm:
        mm = AsyncMock()
        mm.get_history.return_value = events
        mock_mm.return_value = mm
        resp = app_client.get("/api/v1/history", headers={"X-User-Id": "alice"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["id"] == "e1"


def test_export_all(app_client: TestClient, tmp_path: Path) -> None:
    """GET /api/v1/export?type=all 导出全部文件."""
    user_dir = tmp_path / "data" / "users" / "alice"
    user_dir.mkdir(parents=True)
    (user_dir / "events.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    (user_dir / "settings.toml").write_text("[x]\ny = 1\n", encoding="utf-8")

    with (
        patch("app.api.v1.data.user_data_dir", return_value=user_dir),
    ):
        resp = app_client.get(
            "/api/v1/export?export_type=all",
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        files = resp.json()["files"]
        assert any(k.endswith(".jsonl") for k in files)
        assert any(k.endswith(".toml") for k in files)


def test_export_events_only(app_client: TestClient, tmp_path: Path) -> None:
    """GET /api/v1/export?export_type=events 仅导出 .jsonl."""
    user_dir = tmp_path / "data" / "users" / "alice"
    user_dir.mkdir(parents=True)
    (user_dir / "events.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    (user_dir / "settings.toml").write_text("[x]\ny = 1\n", encoding="utf-8")

    with (
        patch("app.api.v1.data.user_data_dir", return_value=user_dir),
    ):
        resp = app_client.get(
            "/api/v1/export?export_type=events",
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        files = resp.json()["files"]
        assert any(k.endswith(".jsonl") for k in files)
        assert not any(k.endswith(".toml") for k in files)


def test_export_settings_only(app_client: TestClient, tmp_path: Path) -> None:
    """GET /api/v1/export?export_type=settings 仅导出 .toml."""
    user_dir = tmp_path / "data" / "users" / "alice"
    user_dir.mkdir(parents=True)
    (user_dir / "events.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    (user_dir / "settings.toml").write_text("[x]\ny = 1\n", encoding="utf-8")

    with (
        patch("app.api.v1.data.user_data_dir", return_value=user_dir),
    ):
        resp = app_client.get(
            "/api/v1/export?export_type=settings",
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        files = resp.json()["files"]
        assert any(k.endswith(".toml") for k in files)
        assert not any(k.endswith(".jsonl") for k in files)


def test_experiments(app_client: TestClient) -> None:
    """GET /api/v1/experiments 返回实验结果."""
    with patch("app.api.v1.data.read_benchmark") as mock_read:
        mock_read.return_value = {
            "strategies": {
                "memory_bank": {"exact_match": 0.8, "field_f1": 0.9, "value_f1": 0.85},
            },
        }
        resp = app_client.get("/api/v1/experiments", headers={"X-User-Id": "alice"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["strategies"]) == 1
        assert body["strategies"][0]["strategy"] == "memory_bank"


def test_delete_data(app_client: TestClient, tmp_path: Path) -> None:
    """DELETE /api/v1/data 删除用户数据目录."""
    user_dir = tmp_path / "data" / "users" / "alice"
    user_dir.mkdir(parents=True)
    (user_dir / "test.txt").write_text("hello", encoding="utf-8")

    with patch("app.api.v1.data.user_data_dir", return_value=user_dir):
        resp = app_client.delete("/api/v1/data", headers={"X-User-Id": "alice"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert not user_dir.exists()


def test_delete_data_nonexistent(app_client: TestClient, tmp_path: Path) -> None:
    """DELETE /api/v1/data 目录不存在时返回 success=False."""
    user_dir = tmp_path / "data" / "users" / "nonexistent"

    with patch("app.api.v1.data.user_data_dir", return_value=user_dir):
        resp = app_client.delete("/api/v1/data", headers={"X-User-Id": "alice"})
    assert resp.status_code == 200
    assert resp.json()["success"] is False
