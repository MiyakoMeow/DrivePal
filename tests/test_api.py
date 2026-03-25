from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

with patch("app.agents.workflow.ChatModel") as mock_chat:
    mock_instance = Mock()
    mock_instance.generate.return_value = '{"result": "测试回复"}'
    mock_chat.return_value = mock_instance

    from app.api.main import app

client = TestClient(app)


def test_query_endpoint():
    response = client.post(
        "/api/query", json={"query": "测试查询", "memory_mode": "keyword"}
    )
    assert response.status_code == 200
    assert "result" in response.json()


def test_feedback_endpoint():
    with patch("app.memory.memory.MemoryModule") as mock_memory:
        mock_instance = Mock()
        mock_memory.return_value = mock_instance

        response = client.post(
            "/api/feedback", json={"event_id": "test123", "action": "accept"}
        )
        assert response.status_code == 200


def test_history_endpoint():
    with patch("app.memory.memory.MemoryModule") as mock_memory:
        mock_instance = Mock()
        mock_instance.get_history.return_value = []
        mock_memory.return_value = mock_instance

        response = client.get("/api/history?limit=5")
        assert response.status_code == 200
        assert "history" in response.json()


def test_api_workflow_initialization():
    """验证API模块正确初始化AgentWorkflow with memory"""
    import app.api.main as api_main

    assert hasattr(api_main, "_memory_module")
    assert api_main._memory_module is not None
