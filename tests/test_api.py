from fastapi.testclient import TestClient
import os

import pytest

SKIP_IF_NO_API_KEY = pytest.mark.skipif(
    not os.getenv("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set",
)


@pytest.fixture
def client():
    from app.api.main import app

    return TestClient(app)


@SKIP_IF_NO_API_KEY
def test_query_endpoint(client):
    response = client.post(
        "/api/query", json={"query": "测试查询", "memory_mode": "keyword"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    assert "event_id" in data


@SKIP_IF_NO_API_KEY
def test_feedback_endpoint(client):
    response = client.post(
        "/api/feedback", json={"event_id": "test123", "action": "accept"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


@SKIP_IF_NO_API_KEY
def test_history_endpoint(client):
    response = client.get("/api/history?limit=5")
    assert response.status_code == 200
    assert "history" in response.json()
