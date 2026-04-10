"""规则引擎测试."""

from typing import TYPE_CHECKING

from app.agents.rules import SAFETY_RULES, Rule, apply_rules, format_constraints

if TYPE_CHECKING:
    from typing import Any


def test_rule_dataclass() -> None:
    """验证 Rule 数据类."""
    r = Rule(
        name="test",
        condition=lambda ctx: True,
        constraint={"allowed_channels": ["audio"]},
        priority=10,
    )
    assert r.name == "test"
    assert r.priority == 10


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
            condition=lambda c: True,
            constraint={"max_frequency_minutes": 30},
            priority=10,
        ),
        Rule(
            name="r2",
            condition=lambda c: True,
            constraint={"max_frequency_minutes": 10},
            priority=20,
        ),
    ]
    result = apply_rules(
        {"scenario": "any", "driver": {"fatigue_level": 0, "workload": "low"}},
        rules,
    )
    assert result["max_frequency_minutes"] == 10


def test_missing_field_not_constraining() -> None:
    """规则A有 allowed_channels，规则B只有 postpone → allowed_channels 仅从A."""
    rules = [
        Rule(
            name="a",
            condition=lambda c: True,
            constraint={"allowed_channels": ["audio", "visual"]},
            priority=10,
        ),
        Rule(
            name="b",
            condition=lambda c: True,
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
            condition=lambda c: True,
            constraint={"allowed_channels": ["audio"]},
            priority=20,
        ),
        Rule(
            name="b",
            condition=lambda c: True,
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


def test_empty_driver_dict() -> None:
    """空 driver dict 不触发 fatigue/overloaded 规则."""
    ctx: dict[str, Any] = {"scenario": "highway", "driver": {}}
    result = apply_rules(ctx, SAFETY_RULES)
    assert result["allowed_channels"] == ["audio"]
    assert result["only_urgent"] is False
    assert result["postpone"] is False


def test_missing_driver_key() -> None:
    """完全无 driver key 不崩溃."""
    ctx: dict[str, Any] = {"scenario": "city_driving"}
    result = apply_rules(ctx, SAFETY_RULES)
    assert result["only_urgent"] is False
    assert result["postpone"] is False
