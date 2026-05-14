"""REST API 端点测试."""

import os
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.config import user_data_dir
from app.memory.singleton import get_memory_module
from app.storage.toml_store import TOMLStore
from tests.fixtures import reset_all_singletons

if TYPE_CHECKING:
    from collections.abc import Generator

_MODULES_WITH_DATA_DIR = [
    "app.config",
    "app.api.main",
    "app.memory.singleton",
]

_MODULES_WITH_DATA_ROOT = [
    "app.config",
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
        for mod in _MODULES_WITH_DATA_ROOT:
            stack.enter_context(patch(f"{mod}.DATA_ROOT", target))
        reset_all_singletons()
        yield TestClient(app)
        reset_all_singletons()


def test_scenario_presets_list(isolated_app: TestClient) -> None:
    """验证 GET /api/presets 返回列表."""
    resp = isolated_app.get("/api/presets")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_save_scenario_preset(isolated_app: TestClient) -> None:
    """验证保存场景预设."""
    resp = isolated_app.post(
        "/api/presets",
        json={
            "name": "test-highway",
            "context": {"scenario": "highway"},
            "current_user": "default",
        },
    )
    assert resp.status_code == 200
    preset = resp.json()
    assert preset["name"] == "test-highway"
    assert preset["id"] != ""


def test_delete_scenario_preset(isolated_app: TestClient) -> None:
    """验证删除场景预设."""
    save_resp = isolated_app.post(
        "/api/presets",
        json={"name": "to-delete", "context": {"scenario": "parked"}},
    )
    preset_id = save_resp.json()["id"]

    del_resp = isolated_app.delete(f"/api/presets/{preset_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True


def test_delete_nonexistent_preset(isolated_app: TestClient) -> None:
    """验证删除不存在的预设返回 False."""
    resp = isolated_app.delete("/api/presets/nonexistent")
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_feedback_invalid_action(isolated_app: TestClient) -> None:
    """验证无效 action 提交反馈返回 422."""
    resp = isolated_app.post(
        "/api/feedback",
        json={"event_id": "x", "action": "invalid"},
    )
    assert resp.status_code == 422


@pytest.mark.embedding
async def test_feedback_success_updates_strategy_weight(
    isolated_app: TestClient,
) -> None:
    """验证 POST /api/feedback 成功路径按事件类型更新策略权重."""
    mm = get_memory_module()
    interaction_result = await mm.write_interaction(
        "项目周会",
        "好的",
        event_type="meeting",
    )
    event_id = interaction_result.event_id

    resp = isolated_app.post(
        "/api/feedback",
        json={"event_id": event_id, "action": "accept"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    strategies = await TOMLStore(
        user_dir=user_data_dir("default"),
        filename="strategies.toml",
        default_factory=dict,
    ).read()
    assert "meeting" in strategies.get("reminder_weights", {})
    assert strategies["reminder_weights"]["meeting"] == pytest.approx(0.6)

    from app.storage.feedback_log import feedback_log_store

    log = feedback_log_store(user_data_dir("default"))
    records = await log.read_all()
    assert len(records) == 1
    assert records[0]["action"] == "accept"
    assert records[0]["type"] == "meeting"


@pytest.mark.integration
def test_process_query_without_context(isolated_app: TestClient) -> None:
    """测试不带上下文的 POST /api/query（需要 LLM）。"""
    resp = isolated_app.post(
        "/api/query",
        json={"query": "明天上午9点有个会议"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] is not None


@pytest.mark.integration
def test_process_query_with_context(isolated_app: TestClient) -> None:
    """测试带上下文的 POST /api/query（验证规则引擎）。"""
    resp = isolated_app.post(
        "/api/query",
        json={
            "query": "提醒我买牛奶",
            "context": {
                "driver": {
                    "emotion": "calm",
                    "workload": "normal",
                    "fatigue_level": 0.2,
                },
                "spatial": {
                    "current_location": {
                        "latitude": 39.9042,
                        "longitude": 116.4074,
                        "address": "北京市东城区",
                        "speed_kmh": 0,
                    },
                    "destination": {
                        "latitude": 39.9142,
                        "longitude": 116.4174,
                        "address": "国贸大厦",
                    },
                },
                "traffic": {
                    "congestion_level": "smooth",
                    "incidents": [],
                    "estimated_delay_minutes": 0,
                },
                "scenario": "parked",
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] is not None
    assert data["stages"] is not None
