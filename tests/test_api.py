"""Tests for the API endpoints."""

from fastapi.testclient import TestClient

import pytest

from tests.conftest import SKIP_IF_NO_LLM


@pytest.fixture
def client():
    """Provide a FastAPI test client."""
    from app.api.main import app

    return TestClient(app)


@SKIP_IF_NO_LLM
def test_query_endpoint(client):
    """Verify the /api/query endpoint returns a valid response."""
    response = client.post(
        "/api/query", json={"query": "测试查询", "memory_mode": "keyword"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    assert "event_id" in data


@SKIP_IF_NO_LLM
def test_feedback_endpoint(client):
    """Verify the /api/feedback endpoint accepts feedback actions."""
    response = client.post(
        "/api/feedback", json={"event_id": "test123", "action": "accept"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


@SKIP_IF_NO_LLM
def test_history_endpoint(client):
    """Verify the /api/history endpoint returns history records."""
    response = client.get("/api/history?limit=5")
    assert response.status_code == 200
    assert "history" in response.json()
