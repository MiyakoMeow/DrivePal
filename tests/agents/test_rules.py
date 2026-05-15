"""规则引擎测试."""

from typing import TYPE_CHECKING

import pytest
import tomli_w

from app.agents.rules import (
    SAFETY_RULES,
    Rule,
    apply_rules,
    load_rules,
    postprocess_decision,
)

if TYPE_CHECKING:
    from typing import Any

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
        "scenario": "unknown_scenario",
        "driver": {"fatigue_level": 0.1, "workload": "low"},
    }
    result = apply_rules(ctx, SAFETY_RULES)
    assert set(result["allowed_channels"]) == {"audio", "detailed", "visual"}
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
    assert set(result["allowed_channels"]) == {"audio", "visual"}
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
    assert set(result["allowed_channels"]) == {"audio", "detailed", "visual"}


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
        result, modifications = postprocess_decision(decision, ctx)
        assert result["should_remind"] is False
        assert result["reminder_content"] == ""
        assert modifications

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
        result, modifications = postprocess_decision(decision, ctx)
        assert result["allowed_channels"] == ["audio"]
        assert modifications

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
        result, modifications = postprocess_decision(decision, ctx)
        assert result["should_remind"] is False
        assert modifications

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
        result, modifications = postprocess_decision(decision, ctx)
        assert result["should_remind"] is True
        assert modifications == []


# ---- 新增：数据驱动规则测试 ----


RULES_TOML_7_CONTENT = """[[rules]]
name = "highway_audio_only"
scenario = "highway"
allowed_channels = ["audio"]
max_frequency_minutes = 30
priority = 10

[[rules]]
name = "fatigue_suppress"
fatigue_above = 0.7
only_urgent = true
allowed_channels = ["audio"]
priority = 20

[[rules]]
name = "overloaded_postpone"
workload = "overloaded"
postpone = true
priority = 15

[[rules]]
name = "parked_all_channels"
scenario = "parked"
allowed_channels = ["visual", "audio", "detailed"]
priority = 5

[[rules]]
name = "city_driving_limit"
scenario = "city_driving"
allowed_channels = ["audio"]
max_frequency_minutes = 15
priority = 8

[[rules]]
name = "traffic_jam_calm"
scenario = "traffic_jam"
allowed_channels = ["audio", "visual"]
max_frequency_minutes = 10
priority = 7

[[rules]]
name = "passenger_present_relax"
has_passengers = true
not_scenario = "highway"
extra_channels = ["visual"]
priority = 3
"""


@pytest.fixture
def rules_toml_7(tmp_path):
    """创建包含 7 条规则临时 TOML 文件."""
    path = tmp_path / "rules.toml"
    path.write_text(RULES_TOML_7_CONTENT, encoding="utf-8")
    return path


def test_load_rules_from_toml(rules_toml_7):
    """从 TOML 文件加载 7 条规则。"""
    rules = load_rules(rules_toml_7)
    assert len(rules) == 7
    names = {r.name for r in rules}
    assert "highway_audio_only" in names
    assert "passenger_present_relax" in names


def test_load_rules_fallback(tmp_path, caplog):
    """TOML 缺失时回退到 4 条默认规则并日志警告。"""
    import logging

    caplog.set_level(logging.WARNING)
    rules = load_rules(tmp_path / "nonexistent.toml")
    assert len(rules) >= 4
    assert "fallback" in caplog.text.lower()


def test_city_driving_rule(rules_toml_7):
    """city_driving 场景匹配并限制 audio+15min。"""
    rules = load_rules(rules_toml_7)
    ctx: dict[str, object] = {"scenario": "city_driving"}
    result = apply_rules(ctx, rules)
    assert "audio" in result["allowed_channels"]
    assert result["max_frequency_minutes"] == 15


def test_passenger_extra_channels(rules_toml_7):
    """乘客在场 + city_driving → channels 含 visual（extra 追加）。"""
    rules = load_rules(rules_toml_7)
    ctx: dict[str, object] = {"scenario": "city_driving", "passengers": ["张三"]}
    result = apply_rules(ctx, rules)
    assert "visual" in result["allowed_channels"]
    assert "audio" in result["allowed_channels"]


def test_passenger_not_on_highway(rules_toml_7):
    """highway 场景排除乘客规则（not_scenario）。"""
    rules = load_rules(rules_toml_7)
    ctx: dict[str, object] = {"scenario": "highway", "passengers": ["张三"]}
    matched = [r for r in rules if r.condition(ctx)]
    assert not any("passenger" in r.name for r in matched)


def test_not_scenario_missing_ctx(rules_toml_7):
    """scenario 缺失时 not_scenario 规则不触发。"""
    rules = load_rules(rules_toml_7)
    ctx: dict[str, object] = {}  # 无 scenario 字段
    matched = [r for r in rules if r.condition(ctx)]
    assert not any("passenger" in r.name for r in matched)


def test_max_frequency_merge_takes_min(rules_toml_7):
    """多规则含 max_frequency 时取最小值。"""
    rules = load_rules(rules_toml_7)
    ctx: dict[str, object] = {"scenario": "traffic_jam"}
    extra_rule = Rule(
        name="test",
        condition=lambda _: True,
        constraint={"max_frequency_minutes": 5},
        priority=0,
    )
    result = apply_rules(ctx, rules + [extra_rule])
    assert result["max_frequency_minutes"] == 5  # min(10, 5)


def test_extra_channels_appended_in_intersection(rules_toml_7):
    """extra_channels 不影响取交结果，仅追加。"""
    rules = load_rules(rules_toml_7)
    # city_driving(audio) + passenger(extra=visual)
    ctx: dict[str, object] = {"scenario": "city_driving", "passengers": ["张三"]}
    result = apply_rules(ctx, rules)
    assert result["allowed_channels"] == ["audio", "visual"]


def test_only_urgent_preserved_with_city_driving(rules_toml_7):
    """city_driving + fatigue → fatigue 的 only_urgent 保留。"""
    rules = load_rules(rules_toml_7)
    ctx: dict[str, object] = {
        "scenario": "city_driving",
        "driver": {"fatigue_level": 0.8, "workload": "normal"},
    }
    result = apply_rules(ctx, rules)
    assert result["only_urgent"] is True
    assert "audio" in result["allowed_channels"]


def test_disable_rules_skips_postprocess() -> None:
    """set_ablation_disable_rules(True) 使 postprocess_decision 跳过修改"""
    from app.agents.rules import postprocess_decision, set_ablation_disable_rules

    set_ablation_disable_rules(True)
    try:
        decision = {"should_remind": True, "reminder_content": "test"}
        ctx: dict[str, Any] = {"scenario": "highway"}
        result, mods = postprocess_decision(decision, ctx)
        assert result is decision
        assert mods == []
    finally:
        set_ablation_disable_rules(False)


def test_ensure_postprocessed_skips_already_processed():
    """ensure_postprocessed 对已处理 decision 直接返回，不重复应用规则。"""
    from app.agents.execution_agent import ExecutionAgent

    # fatigue 上下文：若规则被执行，should_remind 会被改为 False
    decision = {
        "should_remind": True,
        "reminder_content": "测试",
        "_postprocessed": True,
    }
    driving_ctx = {"scenario": "highway", "driver": {"fatigue_level": 0.9}}

    result, mods = ExecutionAgent.ensure_postprocessed(decision, driving_ctx)
    assert result["should_remind"] is True
    assert mods == []


def test_fatigue_threshold_cached(monkeypatch):
    """_get_fatigue_threshold 首次读 env 后缓存，改 env 不生效"""
    from app.agents.rules import _get_fatigue_threshold, reset_fatigue_threshold_cache

    reset_fatigue_threshold_cache()
    monkeypatch.setenv("FATIGUE_THRESHOLD", "0.85")
    first = _get_fatigue_threshold()
    monkeypatch.setenv("FATIGUE_THRESHOLD", "0.5")
    second = _get_fatigue_threshold()
    assert first == second == 0.85
    reset_fatigue_threshold_cache()


def test_ensure_postprocessed_idempotent():
    """调用 ensure_postprocessed 两次仅处理一次。"""
    from app.agents.execution_agent import ExecutionAgent

    decision = {"should_remind": True, "reminder_content": "测试"}
    driving_ctx = {"scenario": "highway"}

    result1, mods1 = ExecutionAgent.ensure_postprocessed(decision, driving_ctx)
    assert "_postprocessed" in result1
    assert result1["_postprocessed"] is True

    result2, mods2 = ExecutionAgent.ensure_postprocessed(result1, driving_ctx)
    assert mods2 == []
    assert result2 is result1
