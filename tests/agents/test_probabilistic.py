"""概率推断模块测试."""

import pytest

from app.agents.probabilistic import compute_interrupt_risk, infer_intent, is_enabled
from app.memory.schemas import SearchResult


def make_search_result(event_type: str, score: float) -> SearchResult:
    """构造 SearchResult mock。"""
    return SearchResult(
        event={"type": event_type, "content": "test event"},
        score=score,
        interactions=[],
    )


class MockStore:
    """Mock MemoryBankStore，仅实现 search 方法。"""

    def __init__(self) -> None:
        """初始化 mock 存储。"""
        self._results: list[SearchResult] = []

    def set_results(self, results: list[SearchResult]) -> None:
        self._results = results

    async def search(self, query: str, top_k: int = 20) -> list[SearchResult]:
        return self._results


@pytest.mark.asyncio
async def test_infer_intent_aggregates_by_type():
    """多个同 type 事件的 score 聚合——meeting 为主意图。"""
    store = MockStore()
    store.set_results(
        [
            make_search_result("meeting", 0.8),
            make_search_result("meeting", 0.6),
            make_search_result("travel", 0.4),
        ]
    )
    result = await infer_intent("明天开会", store)
    assert result["intent_confidence"] > result["alt_confidence"]
    assert result["alternative"] is not None


@pytest.mark.asyncio
async def test_cold_start_uniform():
    """检索无结果时所有 type 等概率。"""
    store = MockStore()
    store.set_results([])
    result = await infer_intent("明天开会", store)
    assert result["intent_confidence"] == pytest.approx(0.2, abs=0.1)
    assert result["alternative"] is None
    assert result["alt_confidence"] == 0.0


def test_interrupt_risk_calculation():
    """打断风险加权公式——验证数值计算。"""
    ctx = {
        "driver_state": {"fatigue_level": 0.7, "workload": "normal"},
        "scenario": "city_driving",
        "spatial": {"current_location": {"speed_kmh": 50}},
    }
    risk = compute_interrupt_risk(ctx)
    # 0.4*0.7 + 0.3*0.3 + 0.2*0.4 + 0.1*0.5 = 0.28+0.09+0.08+0.05 = 0.50
    assert risk == pytest.approx(0.50, abs=0.01)


def test_interrupt_risk_scenario_none_fallback():
    """scenario 缺失时 scenario_risk 取 0.5。"""
    ctx = {"driver_state": {"fatigue_level": 0.5, "workload": "low"}}
    risk = compute_interrupt_risk(ctx)
    # 0.4*0.5 + 0.3*0.1 + 0.2*0.5 + 0.1*0.0 = 0.20+0.03+0.10 = 0.33
    assert risk == pytest.approx(0.33, abs=0.01)


def test_interrupt_risk_overloaded_warning(caplog):
    """overloaded 且 risk ≥ 0.36 时输出日志。"""
    import logging

    caplog.set_level(logging.INFO)
    ctx = {
        "driver_state": {"fatigue_level": 0.9, "workload": "overloaded"},
        "scenario": "highway",
        "spatial": {"current_location": {"speed_kmh": 100}},
    }
    risk = compute_interrupt_risk(ctx)
    assert risk >= 0.36
    assert "High interrupt risk" in caplog.text


def test_interrupt_risk_bounds():
    """风险分数始终在 [0, 1] 范围内。"""
    # 空 context：0.4*0 + 0.3*0.3 + 0.2*0.5 + 0.1*0 = 0.19
    assert compute_interrupt_risk({}) == pytest.approx(0.19, abs=0.01)
    ctx_max = {
        "driver_state": {"fatigue_level": 1.0, "workload": "overloaded"},
        "scenario": "highway",
        "spatial": {"current_location": {"speed_kmh": 120}},
    }
    assert compute_interrupt_risk(ctx_max) <= 1.0


def test_is_enabled_default():
    """默认情况下概率推断启用。"""
    assert is_enabled() is True


def test_speed_factor():
    """各速度区间的 speed_factor。"""
    from app.agents.probabilistic import _speed_factor

    assert _speed_factor(0) == 0.0
    assert _speed_factor(20) == 0.3
    assert _speed_factor(60) == 0.5
    assert _speed_factor(100) == 0.8
