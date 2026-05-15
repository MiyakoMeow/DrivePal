"""v1 Query 路由测试."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from app.agents.state import WorkflowStages
from app.agents.workflow import WorkflowError

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_query_without_context(app_client: TestClient) -> None:
    """POST /api/v1/query 无上下文基础请求正常返回."""
    stages = WorkflowStages()
    with (
        patch("app.api.v1.query.get_memory_module"),
        patch("app.api.v1.query.AgentWorkflow") as mock_wf,
    ):
        mock_instance = mock_wf.return_value
        mock_instance.run_with_stages = AsyncMock(
            return_value=("处理完成", "evt_001", stages),
        )
        resp = app_client.post(
            "/api/v1/query",
            json={"query": "明天开会"},
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"] == "处理完成"
        assert data["event_id"] == "evt_001"


def test_query_with_context(app_client: TestClient) -> None:
    """POST /api/v1/query 携带驾驶上下文."""
    stages = WorkflowStages(context={"scenario": "highway"})
    with (
        patch("app.api.v1.query.get_memory_module"),
        patch("app.api.v1.query.AgentWorkflow") as mock_wf,
    ):
        mock_instance = mock_wf.return_value
        mock_instance.run_with_stages = AsyncMock(
            return_value=("高速提醒", None, stages),
        )
        resp = app_client.post(
            "/api/v1/query",
            json={
                "query": "提醒我休息",
                "context": {"scenario": "highway"},
            },
            headers={"X-User-Id": "bob"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"] == "高速提醒"
        assert data["stages"]["context"] == {"scenario": "highway"}


def test_query_chat_model_unavailable(app_client: TestClient) -> None:
    """POST /api/v1/query LLM不可用时返回503."""
    with (
        patch("app.api.v1.query.get_memory_module"),
        patch("app.api.v1.query.AgentWorkflow") as mock_wf,
    ):
        mock_instance = mock_wf.return_value
        mock_instance.run_with_stages = AsyncMock(
            side_effect=WorkflowError(
                code="MODEL_UNAVAILABLE", message="ChatModel not available"
            ),
        )
        resp = app_client.post(
            "/api/v1/query",
            json={"query": "测试"},
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["code"] == "STORAGE_ERROR"
        assert body["error"]["message"] == "Service temporarily unavailable"


def test_query_internal_error(app_client: TestClient) -> None:
    """POST /api/v1/query 工作流内部异常返回500."""
    with (
        patch("app.api.v1.query.get_memory_module"),
        patch("app.api.v1.query.AgentWorkflow") as mock_wf,
    ):
        mock_instance = mock_wf.return_value
        mock_instance.run_with_stages = AsyncMock(
            side_effect=RuntimeError("boom"),
        )
        resp = app_client.post(
            "/api/v1/query",
            json={"query": "测试"},
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert body["error"]["message"] == "Internal server error"


def test_query_user_id_from_middleware(app_client: TestClient) -> None:
    """POST /api/v1/query 中间件注入 user_id 传入工作流."""
    stages = WorkflowStages()
    with (
        patch("app.api.v1.query.get_memory_module"),
        patch("app.api.v1.query.AgentWorkflow") as mock_wf,
    ):
        mock_instance = mock_wf.return_value
        mock_instance.run_with_stages = AsyncMock(
            return_value=("ok", None, stages),
        )
        app_client.post(
            "/api/v1/query",
            json={"query": "测试"},
            headers={"X-User-Id": "charlie"},
        )
        init_call = mock_wf.call_args
        assert init_call.kwargs["current_user"] == "charlie"
