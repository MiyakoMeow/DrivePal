"""调度器集成测试——覆盖从上下文更新到触发的完整流水线。验证位置/场景触发与去抖逻辑。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scheduler.scheduler import ProactiveScheduler


@pytest.fixture
def scheduler(mock_workflow, mock_memory):
    with patch("app.scheduler.scheduler.SchedulerConfig.load") as mock_load:
        mock_load.return_value = MagicMock(
            tick_interval_seconds=1,
            debounce_seconds=30,
            enable_periodic_review=False,
            review_time="08:00",
            location_proximity_meters=500,
            fatigue_delta_threshold=0.1,
        )
        s = ProactiveScheduler(
            workflow=mock_workflow,
            memory_module=mock_memory,
            user_id="test_integration",
            tick_interval=1,
            debounce_seconds=30,
        )
    s._pending_manager = MagicMock()
    s._pending_manager.poll = AsyncMock(return_value=[])
    return s


@pytest.mark.parametrize(
    "loc",
    [
        pytest.param(
            {"latitude": 30.01, "longitude": 120.0},
            id="Latitude+0.01 (~1113m)",
        ),
        pytest.param(
            {"latitude": 30.0, "longitude": 120.01},
            id="Longitude+0.01 (~1113m)",
        ),
        pytest.param(
            {"latitude": 31.0, "longitude": 121.0},
            id="Far jump (>100km)",
        ),
    ],
)
async def test_location_change_triggers_proactive_run(scheduler, mock_workflow, loc):
    """Given 位置变化≥500m, When _tick, Then proactive_run 以 source="location" 调用。"""
    ctx1 = {
        "scenario": "city_driving",
        "spatial": {"current_location": {"latitude": 30.0, "longitude": 120.0}},
    }
    scheduler.update_context(ctx1)
    await scheduler._tick()

    ctx2 = {
        "scenario": "city_driving",
        "spatial": {"current_location": loc},
    }
    scheduler.update_context(ctx2)
    await scheduler._tick()

    mock_workflow.proactive_run.assert_awaited_once()
    assert mock_workflow.proactive_run.call_args.kwargs["trigger_source"] == "location"


async def test_scenario_change_triggers_with_memory_hints(
    scheduler, mock_workflow, mock_memory
):
    """Given 场景切换到 parked, When _tick, Then source="context_change" 且含记忆提示。"""
    mock_result = MagicMock()
    mock_result.to_public.return_value = {"content": "上次停车忘了关窗"}
    mock_memory.search = AsyncMock(return_value=[mock_result])

    ctx1 = {"scenario": "city_driving", "spatial": {}}
    scheduler.update_context(ctx1)
    await scheduler._tick()

    ctx2 = {"scenario": "parked", "spatial": {}}
    scheduler.update_context(ctx2)
    await scheduler._tick()

    mock_workflow.proactive_run.assert_awaited_once()
    kwargs = mock_workflow.proactive_run.call_args.kwargs
    assert kwargs["trigger_source"] == "context_change"
    assert kwargs["memory_hints"] == [{"content": "上次停车忘了关窗"}]


async def test_debounce_suppresses_rapid_context_changes(scheduler, mock_workflow):
    """Given 30s内两次位置变化, When _tick 两次, Then 仅首次触发, 第二次被去抖。"""
    ctx1 = {
        "scenario": "city_driving",
        "spatial": {"current_location": {"latitude": 30.0, "longitude": 120.0}},
    }
    scheduler.update_context(ctx1)
    await scheduler._tick()

    ctx2 = {
        "scenario": "city_driving",
        "spatial": {"current_location": {"latitude": 30.01, "longitude": 120.0}},
    }
    scheduler.update_context(ctx2)
    await scheduler._tick()

    ctx3 = {
        "scenario": "city_driving",
        "spatial": {"current_location": {"latitude": 30.02, "longitude": 120.0}},
    }
    scheduler.update_context(ctx3)
    await scheduler._tick()

    assert mock_workflow.proactive_run.call_count == 1
