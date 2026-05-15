"""测试 ProactiveScheduler tick 流程。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scheduler.context_monitor import ContextDelta
from app.scheduler.scheduler import ProactiveScheduler
from app.scheduler.trigger_evaluator import TriggerDecision, TriggerSignal


@pytest.fixture
def mock_workflow():
    wf = MagicMock()
    wf.current_user = "default"
    wf.memory_module = MagicMock()
    wf.memory_module.write = AsyncMock()
    wf.proactive_run = AsyncMock(return_value=("result", "evt1", MagicMock()))
    return wf


@pytest.fixture
def mock_memory():
    return MagicMock()


@pytest.fixture
def scheduler(mock_workflow, mock_memory):
    with patch.object(ProactiveScheduler, "_load_config", return_value={}):
        s = ProactiveScheduler(
            workflow=mock_workflow,
            memory_module=mock_memory,
            tick_interval=1,
            debounce_seconds=0,
        )
    s._pending_manager = MagicMock()
    return s


async def test_drain_voice_queue_writes_to_memory(scheduler, mock_workflow):
    """Given 语音队列有文本, When _tick, Then memory_module.write 被调用。"""
    await scheduler._voice_queue.put("明天开会")
    await scheduler._drain_voice_queue()
    mock_workflow.memory_module.write.assert_awaited_once()
    event = mock_workflow.memory_module.write.call_args[0][0]
    assert event.content == "明天开会"


async def test_drain_voice_queue_skips_empty_text(scheduler, mock_workflow):
    """Given 语音队列有空字符串, When _tick, Then write 不被调用。"""
    await scheduler._voice_queue.put("   ")
    await scheduler._drain_voice_queue()
    mock_workflow.memory_module.write.assert_not_awaited()


async def test_drain_voice_queue_write_failure_graceful(scheduler, mock_workflow):
    """Given write 抛异常, When _tick, Then 不崩溃。"""
    mock_workflow.memory_module.write.side_effect = RuntimeError("boom")
    await scheduler._voice_queue.put("hello")
    await scheduler._drain_voice_queue()


async def test_poll_pending_triggers_proactive_run(scheduler, mock_workflow):
    """Given pending reminder 满足条件, When _poll_pending, Then proactive_run 被调用。"""
    scheduler._pending_manager.poll = AsyncMock(
        return_value=[{"id": "r1", "content": "提醒"}]
    )
    await scheduler._poll_pending({"scenario": "city_driving"})
    mock_workflow.proactive_run.assert_awaited_once()


async def test_poll_pending_failure_graceful(scheduler, mock_workflow):
    """Given proactive_run 抛异常, When _poll_pending, Then 不崩溃。"""
    scheduler._pending_manager.poll = AsyncMock(return_value=[{"id": "r1"}])
    mock_workflow.proactive_run.side_effect = RuntimeError("fail")
    await scheduler._poll_pending({"scenario": "parked"})


def test_build_signals_scenario_change(scheduler):
    """Given delta.scenario_changed, When _build_signals, Then 含 context_change 信号。"""
    delta = ContextDelta(scenario_changed=True)
    signals = scheduler._build_signals({"scenario": "highway"}, delta, [])
    sources = [s.source for s in signals]
    assert "context_change" in sources


def test_build_signals_location_change(scheduler):
    """Given delta.location_changed, When _build_signals, Then 含 location 信号。"""
    delta = ContextDelta(location_changed=True)
    signals = scheduler._build_signals({"scenario": "city_driving"}, delta, [])
    sources = [s.source for s in signals]
    assert "location" in sources


def test_build_signals_state_change(scheduler):
    """Given delta.fatigue_increased, When _build_signals, Then 含 state 信号。"""
    delta = ContextDelta(fatigue_increased=True)
    signals = scheduler._build_signals({"scenario": "parked"}, delta, [])
    sources = [s.source for s in signals]
    assert "state" in sources


def test_build_signals_periodic_trigger(scheduler):
    """Given 时间匹配 review_hour, When _build_signals, Then 含 periodic 信号。"""
    scheduler._last_review_date = None
    now = MagicMock()
    now.hour = scheduler._review_hour
    now.minute = scheduler._review_minute
    now.strftime.return_value = "2026-05-15"
    now.astimezone.return_value = now
    with patch("app.scheduler.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = now
        signals = scheduler._build_signals({"scenario": "parked"}, ContextDelta(), [])
    sources = [s.source for s in signals]
    assert "periodic" in sources


async def test_evaluate_and_execute_broadcasts_via_ws(scheduler, mock_workflow):
    """Given should_trigger, When evaluate_and_execute, Then ws_manager.broadcast 被调用。"""
    ws = MagicMock()
    ws.broadcast_reminder = AsyncMock()
    scheduler._ws_manager = ws

    signal = TriggerSignal(source="state", priority=2, context={})
    with patch.object(
        scheduler._trigger_evaluator,
        "evaluate",
        return_value=TriggerDecision(
            should_trigger=True, reason="state 触发", interrupt_level=2
        ),
    ):
        await scheduler._evaluate_and_execute([signal], {"scenario": "parked"})

    ws.broadcast_reminder.assert_awaited_once()
