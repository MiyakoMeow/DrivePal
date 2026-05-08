"""规则引擎测试."""

from typing import TYPE_CHECKING

from app.agents.rules import (
    SAFETY_RULES,
    Rule,
    _get_fatigue_threshold,
    apply_rules,
    format_constraints,
    postprocess_decision,
    reset_fatigue_threshold_cache,
)

if TYPE_CHECKING:
    from typing import Any

    import pytest

# 替换测试中的魔法值
RULE_PRIORITY = 10  # 测试规则优先级
MIN_FREQUENCY_MINUTES = 10  # 最小频率分钟数


def test_rule_dataclass() -> None:
    """验证 Rule 数据类."""
    r = Rule(
        name="test",
        condition=lambda _: True,
        constraint={"allowed_channels": ["audio"]},
        priority=10,
    )
    assert r.name == "test"
    assert r.priority == RULE_PRIORITY


def test_no_matching_rules() -> None:
    """验证无匹配规则时返回默认约束."""
    ctx: dict[str, Any] = {
        "scenario": "city_driving",
        "driver": {"fatigue_level": 0.1, "workload": "low"},
    }
    result = apply_rules(ctx, SAFETY_RULES)
    assert result["allowed_channels"] == ["audio", "detailed", "visual"]
    assert result["only_urgent"] is False
    assert result["postpone"] is False


def test_highway_rule() -> None:
    """验证高速场景规则."""
    ctx: dict[str, Any] = {
        "scenario": "highway",
        "driver": {"fatigue_level": 0.1, "workload": "low"},
    }
    result = apply_rules(ctx, SAFETY_RULES)
    assert result["allowed_channels"] == ["audio"]
    assert result["postpone"] is False


def test_fatigue_rule() -> None:
    """验证疲劳规则."""
    ctx: dict[str, Any] = {
        "scenario": "city_driving",
        "driver": {"fatigue_level": 0.8, "workload": "normal"},
    }
    result = apply_rules(ctx, SAFETY_RULES)
    assert result["only_urgent"] is True
    assert result["allowed_channels"] == ["audio"]


def test_overloaded_rule() -> None:
    """验证高工作负载规则."""
    ctx: dict[str, Any] = {
        "scenario": "city_driving",
        "driver": {"fatigue_level": 0.3, "workload": "overloaded"},
    }
    result = apply_rules(ctx, SAFETY_RULES)
    assert result["postpone"] is True


def test_highway_and_fatigue_intersection() -> None:
    """高速+疲劳 → allowed_channels 取交集."""
    ctx: dict[str, Any] = {
        "scenario": "highway",
        "driver": {"fatigue_level": 0.8, "workload": "normal"},
    }
    result = apply_rules(ctx, SAFETY_RULES)
    assert result["only_urgent"] is True
    assert set(result["allowed_channels"]) == {"audio"}


def test_max_frequency_minutes_takes_min() -> None:
    """多条规则定义 max_frequency_minutes 时取最小值."""
    rules = [
        Rule(
            name="r1",
            condition=lambda _: True,
            constraint={"max_frequency_minutes": 30},
            priority=10,
        ),
        Rule(
            name="r2",
            condition=lambda _: True,
            constraint={"max_frequency_minutes": 10},
            priority=20,
        ),
    ]
    result = apply_rules(
        {"scenario": "any", "driver": {"fatigue_level": 0, "workload": "low"}},
        rules,
    )
    assert result["max_frequency_minutes"] == MIN_FREQUENCY_MINUTES


def test_missing_field_not_constraining() -> None:
    """规则A有 allowed_channels，规则B只有 postpone → allowed_channels 仅从A."""
    rules = [
        Rule(
            name="a",
            condition=lambda _: True,
            constraint={"allowed_channels": ["audio", "visual"]},
            priority=10,
        ),
        Rule(
            name="b",
            condition=lambda _: True,
            constraint={"postpone": True},
            priority=20,
        ),
    ]
    result = apply_rules(
        {"scenario": "any", "driver": {"fatigue_level": 0, "workload": "low"}},
        rules,
    )
    assert result["allowed_channels"] == ["audio", "visual"]
    assert result["postpone"] is True


def test_empty_intersection_fallback() -> None:
    """allowed_channels 交集为空时回退到默认通道."""
    rules = [
        Rule(
            name="a",
            condition=lambda _: True,
            constraint={"allowed_channels": ["audio"]},
            priority=20,
        ),
        Rule(
            name="b",
            condition=lambda _: True,
            constraint={"allowed_channels": ["visual"]},
            priority=10,
        ),
    ]
    result = apply_rules(
        {"scenario": "any", "driver": {"fatigue_level": 0, "workload": "low"}},
        rules,
    )
    assert result["allowed_channels"] == ["audio", "detailed", "visual"]


def test_format_constraints() -> None:
    """验证格式化约束输出."""
    ctx: dict[str, Any] = {
        "scenario": "highway",
        "driver": {"fatigue_level": 0.8, "workload": "normal"},
    }
    result = apply_rules(ctx, SAFETY_RULES)
    text = format_constraints(result)
    assert "audio" in text
    assert "紧急" in text


def test_format_empty_constraints() -> None:
    """验证格式化空约束输出."""
    text = format_constraints(
        {
            "only_urgent": False,
            "postpone": False,
            "allowed_channels": ["visual", "audio", "detailed"],
        },
    )
    assert "audio" in text


def test_fatigue_threshold_cache_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证疲劳阈值缓存可重置，重置后读取新的环境变量值。"""
    reset_fatigue_threshold_cache()
    with monkeypatch.context() as m:
        m.setenv("FATIGUE_THRESHOLD", "0.5")
        assert _get_fatigue_threshold() == 0.5
    reset_fatigue_threshold_cache()
    with monkeypatch.context() as m:
        m.delenv("FATIGUE_THRESHOLD", raising=False)
        assert _get_fatigue_threshold() == 0.7


def test_empty_driver_dict() -> None:
    """空 driver dict 不触发 fatigue/overloaded 规则."""
    ctx: dict[str, Any] = {"scenario": "highway", "driver": {}}
    result = apply_rules(ctx, SAFETY_RULES)
    assert result["allowed_channels"] == ["audio"]
    assert result["only_urgent"] is False
    assert result["postpone"] is False


class TestPostprocessDecision:
    """规则后处理测试."""

    def test_postpone_overrides_decision(self) -> None:
        """postpone=True → should_remind=false, reminder_content 置空."""
        ctx: dict[str, Any] = {
            "driver": {"workload": "overloaded"},
            "scenario": "city_driving",
        }
        decision: dict[str, Any] = {
            "should_remind": True,
            "reminder_content": "提醒事项",
            "allowed_channels": ["visual", "audio"],
        }
        result = postprocess_decision(decision, ctx)
        assert result["should_remind"] is False
        assert result["reminder_content"] == ""

    def test_allowed_channels_filtered(self) -> None:
        """allowed_channels 被安全规则过滤."""
        ctx: dict[str, Any] = {
            "driver": {"fatigue_level": 0.0, "workload": "low"},
            "scenario": "highway",
        }
        decision: dict[str, Any] = {
            "should_remind": True,
            "reminder_content": "前方出口",
            "allowed_channels": ["visual", "audio", "detailed"],
        }
        result = postprocess_decision(decision, ctx)
        assert result["allowed_channels"] == ["audio"]

    def test_only_urgent_blocks_non_urgent(self) -> None:
        """only_urgent=True 且 type=general → should_remind=false."""
        ctx: dict[str, Any] = {
            "driver": {"fatigue_level": 0.8, "workload": "normal"},
            "scenario": "city_driving",
        }
        decision: dict[str, Any] = {
            "should_remind": True,
            "reminder_content": "普通提醒",
            "type": "general",
        }
        result = postprocess_decision(decision, ctx)
        assert result["should_remind"] is False

    def test_only_urgent_allows_urgent_types(self) -> None:
        """only_urgent=True 但 type=warning → 正常通过."""
        ctx: dict[str, Any] = {
            "driver": {"fatigue_level": 0.8, "workload": "normal"},
            "scenario": "city_driving",
        }
        decision: dict[str, Any] = {
            "should_remind": True,
            "reminder_content": "油量不足",
            "type": "warning",
        }
        result = postprocess_decision(decision, ctx)
        assert result["should_remind"] is True
