"""测试独立语音服务。"""

from fastapi.testclient import TestClient

from app.voice.server import app


def test_server_status_returns_dict():
    """Given 独立服务 app, When GET /api/v1/voice/status, Then 200 + 含 enabled 字段。"""
    with TestClient(app) as c:
        resp = c.get("/api/v1/voice/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data


def test_server_voice_routes_registered():
    """Given 独立服务 app, When GET /api/v1/voice/config, Then 200。"""
    with TestClient(app) as c:
        resp = c.get("/api/v1/voice/config")
        assert resp.status_code == 200
