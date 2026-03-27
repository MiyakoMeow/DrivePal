from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def client_with_mock():
    with patch("app.agents.workflow.AgentWorkflow") as mock_cls:
        mock_instance = Mock()
        mock_instance.run.return_value = ("提醒已发送: 测试提醒", "test_event_id_123")
        mock_cls.return_value = mock_instance
        from app.api.main import app

        yield TestClient(app), mock_instance


def test_query_endpoint(client_with_mock):
    client, mock_instance = client_with_mock
    response = client.post(
        "/api/query", json={"query": "测试查询", "memory_mode": "keyword"}
    )
    assert response.status_code == 200
    assert "result" in response.json()
    mock_instance.run.assert_called_once()


def test_feedback_endpoint():
    with patch("app.memory.memory.MemoryModule") as mock_memory:
        mock_instance = Mock()
        mock_memory.return_value = mock_instance

        from app.api.main import app

        client = TestClient(app)
        response = client.post(
            "/api/feedback", json={"event_id": "test123", "action": "accept"}
        )
        assert response.status_code == 200


def test_history_endpoint():
    with patch("app.memory.memory.MemoryModule") as mock_memory:
        mock_instance = Mock()
        mock_instance.get_history.return_value = []
        mock_memory.return_value = mock_instance

        from app.api.main import app

        client = TestClient(app)
        response = client.get("/api/history?limit=5")
        assert response.status_code == 200
        assert "history" in response.json()


def test_api_workflow_initialization():
    """验证API模块正确初始化AgentWorkflow with memory"""
    import app.api.main as api_main

    assert hasattr(api_main, "_memory_module")
    assert api_main._memory_module is not None
