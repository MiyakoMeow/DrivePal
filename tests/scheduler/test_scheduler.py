"""测试主动调度器组件。"""

from app.scheduler.context_monitor import ContextMonitor
from app.scheduler.trigger_evaluator import TriggerEvaluator, TriggerSignal


def test_context_monitor_first_update_no_delta():
    mon = ContextMonitor()
    delta = mon.update({"scenario": "parked", "spatial": {}})
    assert not delta.scenario_changed
    assert not delta.location_changed


def test_context_monitor_scenario_change():
    mon = ContextMonitor()
    mon.update({"scenario": "parked", "spatial": {}})
    delta = mon.update({"scenario": "highway", "spatial": {}})
    assert delta.scenario_changed


def test_trigger_evaluator_debounce():
    ev = TriggerEvaluator(debounce_seconds=30.0)
    signal = TriggerSignal(source="test", priority=1)
    first = ev.evaluate(signal, None)
    assert first.should_trigger
    second = ev.evaluate(signal, None)
    assert not second.should_trigger
    assert "去抖" in second.reason
