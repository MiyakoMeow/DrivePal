"""GraphQL 端点测试."""

import os
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from tests.fixtures import reset_all_singletons

if TYPE_CHECKING:
    from collections.abc import Generator

_MODULES_WITH_DATA_DIR = [
    "app.config",
    "app.api.main",
    "app.api.resolvers.mutation",
    "app.memory.singleton",
]


@pytest.fixture
def isolated_app(tmp_path: Path) -> Generator[TestClient]:
    """每个测试获取独立的 FastAPI app 实例."""
    data_dir = tmp_path / "data"
    os.environ["DATA_DIR"] = str(data_dir)
    target = Path(data_dir)
    with ExitStack() as stack:
        for mod in _MODULES_WITH_DATA_DIR:
            stack.enter_context(patch(f"{mod}.DATA_DIR", target))
        reset_all_singletons()
        yield TestClient(app)
        reset_all_singletons()


GRAPHQL_ENDPOINT = "/graphql"


def _graphql_query(
    isolated_app: TestClient,
    query: str,
    variables: dict | None = None,
) -> dict:
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = isolated_app.post(GRAPHQL_ENDPOINT, json=payload)
    return resp.json()


def test_graphql_endpoint_responds(isolated_app: TestClient) -> None:
    """验证 GraphQL 端点正常响应."""
    result = _graphql_query(isolated_app, "{ __typename }")
    assert "data" in result


def test_experiment_report_query(isolated_app: TestClient) -> None:
    """验证 experimentReport 查询."""
    result = _graphql_query(isolated_app, "{ experimentReport { report } }")
    assert "data" in result
    assert result["data"]["experimentReport"]["report"] is not None


def test_scenario_presets_query(isolated_app: TestClient) -> None:
    """验证 scenarioPresets 查询."""
    result = _graphql_query(isolated_app, "{ scenarioPresets { id name } }")
    assert "data" in result
    assert isinstance(result["data"]["scenarioPresets"], list)


def test_save_scenario_preset(isolated_app: TestClient) -> None:
    """验证保存场景预设."""
    result = _graphql_query(
        isolated_app,
        """
        mutation($name: String!, $ctx: DrivingContextInput!) {
            saveScenarioPreset(input: { name: $name, context: $ctx }) {
                id name
            }
        }
    """,
        {"name": "test-highway", "ctx": {"scenario": "HIGHWAY"}},
    )
    assert "data" in result
    preset = result["data"]["saveScenarioPreset"]
    assert preset["name"] == "test-highway"
    assert preset["id"] != ""


def test_delete_scenario_preset(isolated_app: TestClient) -> None:
    """验证删除场景预设."""
    result = _graphql_query(
        isolated_app,
        """
        mutation($name: String!, $ctx: DrivingContextInput!) {
            saveScenarioPreset(input: { name: $name, context: $ctx }) { id }
        }
    """,
        {"name": "to-delete", "ctx": {"scenario": "PARKED"}},
    )
    preset_id = result["data"]["saveScenarioPreset"]["id"]

    del_result = _graphql_query(
        isolated_app,
        """
        mutation($presetId: String!) { deleteScenarioPreset(presetId: $presetId) }
    """,
        {"presetId": preset_id},
    )
    assert del_result["data"]["deleteScenarioPreset"] is True


def test_delete_nonexistent_preset(isolated_app: TestClient) -> None:
    """验证删除不存在的预设返回 False."""
    result = _graphql_query(
        isolated_app,
        """
        mutation { deleteScenarioPreset(presetId: "nonexistent") }
    """,
    )
    assert result["data"]["deleteScenarioPreset"] is False


def test_feedback_invalid_action(isolated_app: TestClient) -> None:
    """验证无效 action 提交反馈返回错误."""
    result = _graphql_query(
        isolated_app,
        """
        mutation {
            submitFeedback(input: { eventId: "x", action: "invalid" }) {
                status
            }
        }
    """,
    )
    assert "errors" in result


def test_history_query(isolated_app: TestClient) -> None:
    """验证历史记录查询."""
    result = _graphql_query(
        isolated_app,
        """
        query { history(limit: 5, memoryMode: MEMORY_BANK) { id content } }
    """,
    )
    assert "data" in result
    assert isinstance(result["data"]["history"], list)


@pytest.mark.integration
def test_process_query_without_context(isolated_app: TestClient) -> None:
    """测试不带上下文的 processQuery mutation（需要 LLM）。"""
    result = _graphql_query(
        isolated_app,
        """
        mutation($query: String!) {
            processQuery(input: { query: $query, memoryMode: MEMORY_BANK }) {
                result
                eventId
                stages { context task decision execution }
            }
        }
    """,
        {"query": "明天上午9点有个会议"},
    )
    assert "data" in result
    pqr = result["data"]["processQuery"]
    assert pqr["result"] is not None


@pytest.mark.integration
def test_process_query_with_context(isolated_app: TestClient) -> None:
    """测试带上下文的 processQuery mutation（验证规则引擎）。"""
    result = _graphql_query(
        isolated_app,
        """
        mutation($input: ProcessQueryInput!) {
            processQuery(input: $input) {
                result
                eventId
                stages { context task decision execution }
            }
        }
    """,
        {
            "input": {
                "query": "提醒我买牛奶",
                "memoryMode": "MEMORY_BANK",
                "context": {
                    "driver": {
                        "emotion": "CALM",
                        "workload": "NORMAL",
                        "fatigueLevel": 0.2,
                    },
                    "spatial": {
                        "currentLocation": {
                            "latitude": 39.9042,
                            "longitude": 116.4074,
                            "address": "北京市东城区",
                            "speedKmh": 0,
                        },
                        "destination": {
                            "latitude": 39.9142,
                            "longitude": 116.4174,
                            "address": "国贸大厦",
                        },
                    },
                    "traffic": {
                        "congestionLevel": "SMOOTH",
                        "incidents": [],
                        "estimatedDelayMinutes": 0,
                    },
                    "scenario": "PARKED",
                },
            },
        },
    )
    assert "data" in result
    pqr = result["data"]["processQuery"]
    assert pqr["result"] is not None
    assert pqr["stages"] is not None
