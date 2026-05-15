"""v1 Voice API 测试."""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, PropertyMock, patch

from app.voice.service import VoiceService

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_voice_status(app_client: TestClient) -> None:
    """GET /api/v1/voice/status 返回运行状态。"""
    resp = app_client.get("/api/v1/voice/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "running" in data
    assert "config" in data


def test_voice_config_get(app_client: TestClient) -> None:
    """GET /api/v1/voice/config 返回配置。"""
    resp = app_client.get("/api/v1/voice/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "device_index" in data


def test_voice_start_stop(app_client: TestClient) -> None:
    """POST /api/v1/voice/start + stop 切换运行状态。"""
    app_client.post("/api/v1/voice/stop")
    with patch.object(VoiceService, "start", new=AsyncMock(return_value=True)):
        resp = app_client.post("/api/v1/voice/start")
        assert resp.status_code == 200
    resp = app_client.post("/api/v1/voice/stop")
    assert resp.status_code == 200


def test_voice_config_put(app_client: TestClient) -> None:
    """PUT /api/v1/voice/config 返回已应用的键列表（mock update_config 防写真实文件）。"""
    with patch.object(VoiceService, "update_config", new_callable=AsyncMock) as mock_uc:
        mock_uc.return_value = {
            "applied": ["device_index"],
            "requires_restart": False,
            "running": False,
        }
        resp = app_client.put("/api/v1/voice/config", json={"device_index": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert "applied" in data
        mock_uc.assert_called_once_with({"device_index": 1})


def test_voice_config_put_invalid_returns_400(app_client: TestClient) -> None:
    """PUT /api/v1/voice/config 传无效 vad_mode 返 400。"""
    resp = app_client.put("/api/v1/voice/config", json={"vad_mode": 9})
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "INVALID_INPUT"


def test_voice_transcriptions(app_client: TestClient) -> None:
    """GET /api/v1/voice/transcriptions 返回列表。"""
    resp = app_client.get("/api/v1/voice/transcriptions?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_voice_start_already_running_returns_409(app_client: TestClient) -> None:
    """POST /api/v1/voice/start 已运行时返 409。"""
    with (
        patch.object(VoiceService, "status", new_callable=PropertyMock) as mock_status,
    ):
        mock_status.return_value = {
            "enabled": True,
            "running": True,
            "vad_status": "idle",
            "config": {"device_index": 0},
        }
        resp = app_client.post("/api/v1/voice/start")
        assert resp.status_code == 409
        data = resp.json()
        assert data["error"]["code"] == "ALREADY_RUNNING"


def test_voice_start_disabled_returns_400(app_client: TestClient) -> None:
    """POST /api/v1/voice/start 禁用时返 400。"""
    with (
        patch.object(VoiceService, "status", new_callable=PropertyMock) as mock_status,
        patch.object(VoiceService, "start", new=AsyncMock(return_value=False)),
    ):
        mock_status.return_value = {
            "enabled": True,
            "running": False,
            "vad_status": "idle",
        }
        resp = app_client.post("/api/v1/voice/start")
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == "VOICE_DISABLED"


def test_voice_devices(app_client: TestClient) -> None:
    """GET /api/v1/voice/devices 返回列表（mock get_devices）。"""
    mock_result = [
        {"index": 0, "name": "Mic", "channels": 1},
    ]
    with patch.object(
        VoiceService,
        "get_devices",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        resp = app_client.get("/api/v1/voice/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "Mic"
