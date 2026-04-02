"""API 端点测试."""

from fastapi.testclient import TestClient

import pytest

from app.models.chat import ChatModel
from app.models.settings import LLMProviderConfig


@pytest.fixture
def client() -> TestClient:
    """提供 FastAPI 测试客户端."""
    from app.api.main import app

    return TestClient(app)


@pytest.mark.integration
def test_query_endpoint(
    client: TestClient, llm_provider: LLMProviderConfig | None
) -> None:
    """验证 /api/query 端点返回有效响应."""
    if llm_provider is None:
        pytest.skip("No LLM provider available")
    ChatModel(providers=[llm_provider])
    response = client.post(
        "/api/query", json={"query": "测试查询", "memory_mode": "memory_bank"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    assert "event_id" in data


@pytest.mark.integration
def test_feedback_endpoint(
    client: TestClient, llm_provider: LLMProviderConfig | None
) -> None:
    """验证 /api/feedback 端点接受反馈操作."""
    if llm_provider is None:
        pytest.skip("No LLM provider available")
    ChatModel(providers=[llm_provider])
    response = client.post(
        "/api/feedback", json={"event_id": "test123", "action": "accept"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


@pytest.mark.integration
def test_history_endpoint(
    client: TestClient, llm_provider: LLMProviderConfig | None
) -> None:
    """验证 /api/history 端点返回历史记录."""
    if llm_provider is None:
        pytest.skip("No LLM provider available")
    ChatModel(providers=[llm_provider])
    response = client.get("/api/history?limit=5")
    assert response.status_code == 200
    assert "history" in response.json()
