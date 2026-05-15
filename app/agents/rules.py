"""轻量规则引擎 — 安全约束规则定义与合并."""

from __future__ import annotations

import contextvars
import logging
import math
import os
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.config import ensure_config, get_config_root

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass
class Rule:
    """安全约束规则."""

    name: str
    condition: Callable[[dict], bool]
    constraint: dict[str, Any]
    priority: int = 0


URGENT_TYPES = frozenset({"warning", "safety", "alert"})


_cached_fatigue_threshold: float | None = None


def _get_fatigue_threshold() -> float:
    global _cached_fatigue_threshold
    if _cached_fatigue_threshold is not None:
        return _cached_fatigue_threshold
    raw = os.environ.get("DRIVEPAL_FATIGUE_THRESHOLD") or os.environ.get(
        "FATIGUE_THRESHOLD", "0.7"
    )
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "Invalid DRIVEPAL_FATIGUE_THRESHOLD/FATIGUE_THRESHOLD=%r, using default 0.7",
            raw,
        )
        _cached_fatigue_threshold = 0.7
        return 0.7
    if not math.isfinite(value):
        logger.warning("FATIGUE_THRESHOLD=%r is NaN/Inf, using default 0.7", raw)
        _cached_fatigue_threshold = 0.7
        return 0.7
    if not 0.0 <= value <= 1.0:
        logger.warning(
            "FATIGUE_THRESHOLD=%r out of range [0,1], using default 0.7", raw
        )
        _cached_fatigue_threshold = 0.7
        return 0.7
    _cached_fatigue_threshold = value
    return value


def get_fatigue_threshold() -> float:
    """获取疲劳阈值（公开接口）。"""
    return _get_fatigue_threshold()


def reset_fatigue_threshold_cache() -> None:
    """重置疲劳阈值缓存（供测试使用）。"""
    global _cached_fatigue_threshold
    _cached_fatigue_threshold = None


_ablation_disable_rules: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_ablation_disable_rules", default=False
)


def set_ablation_disable_rules(v: bool) -> None:
    """设置消融实验标记：禁用规则引擎后处理。ContextVar 自动任务隔离。"""
    _ablation_disable_rules.set(v)


def get_ablation_disable_rules() -> bool:
    """读取消融实验标记（当前 Context 的值）。"""
    return _ablation_disable_rules.get()


_FALLBACK_RULES: list[Rule] = [
    Rule(
        name="highway_audio_only",
        condition=lambda ctx: ctx.get("scenario") == "highway",
        constraint={"allowed_channels": ["audio"], "max_frequency_minutes": 30},
        priority=10,
    ),
    Rule(
        name="fatigue_suppress",
        condition=lambda ctx: (
            ctx.get("driver", {}).get("fatigue_level", 0) > _get_fatigue_threshold()
        ),
        constraint={"only_urgent": True, "allowed_channels": ["audio"]},
        priority=20,
    ),
    Rule(
        name="overloaded_postpone",
        condition=lambda ctx: ctx.get("driver", {}).get("workload", "") == "overloaded",
        constraint={"postpone": True},
        priority=15,
    ),
    Rule(
        name="parked_all_channels",
        condition=lambda ctx: ctx.get("scenario") == "parked",
        constraint={"allowed_channels": ["visual", "audio", "detailed"]},
        priority=5,
    ),
    Rule(
        name="city_driving_limit",
        condition=lambda ctx: ctx.get("scenario") == "city_driving",
        constraint={"allowed_channels": ["audio"], "max_frequency_minutes": 15},
        priority=8,
    ),
    Rule(
        name="traffic_jam_calm",
        condition=lambda ctx: ctx.get("scenario") == "traffic_jam",
        constraint={
            "allowed_channels": ["audio", "visual"],
            "max_frequency_minutes": 10,
        },
        priority=7,
    ),
    Rule(
        name="passenger_present_relax",
        condition=lambda ctx: (
            bool(ctx.get("passengers")) and ctx.get("scenario") != "highway"
        ),
        constraint={"extra_channels": ["visual"]},
        priority=3,
    ),
]


def _build_condition(rule_cfg: dict) -> Callable[[dict], bool]:
    """从 TOML 配置项构造 Rule.condition 闭包。各条件 AND 组合。"""
    checks: list[Callable[[dict], bool]] = []

    if "scenario" in rule_cfg:
        val = rule_cfg["scenario"]
        checks.append(lambda ctx, v=val: ctx.get("scenario") == v)

    if "not_scenario" in rule_cfg:
        val = rule_cfg["not_scenario"]
        # scenario 缺失时不触发
        checks.append(
            lambda ctx, v=val: bool(ctx.get("scenario")) and ctx.get("scenario") != v
        )

    if "workload" in rule_cfg:
        val = rule_cfg["workload"]
        checks.append(lambda ctx, v=val: ctx.get("driver", {}).get("workload") == v)

    if "fatigue_above" in rule_cfg:
        threshold = rule_cfg["fatigue_above"]
        checks.append(
            lambda ctx, t=threshold: ctx.get("driver", {}).get("fatigue_level", 0) > t
        )

    if "has_passengers" in rule_cfg:
        checks.append(
            lambda ctx: bool(ctx.get("passengers"))
        )  # TOML has_passengers=true 时生效（key 存在且非 false 即可触发）

    def condition(ctx: dict) -> bool:
        return all(check(ctx) for check in checks) if checks else False

    return condition


# TOML 约束字段名集合——不在 condition 条件字段中的。
_CONSTRAINT_FIELDS = frozenset(
    {
        "allowed_channels",
        "max_frequency_minutes",
        "only_urgent",
        "postpone",
        "extra_channels",
    }
)


def load_rules(path: Path) -> list[Rule]:
    """从 TOML 文件加载规则列表。失败时回退到默认规则。"""
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as e:
        logger.warning("Failed to load rules from %s: %s, using fallback", path, e)
        return list(_FALLBACK_RULES)

    raw_rules = data.get("rules", [])
    if not raw_rules:
        logger.warning("No rules found in %s, using fallback", path)
        return list(_FALLBACK_RULES)

    rules: list[Rule] = []
    for cfg in raw_rules:
        constraint = {k: v for k, v in cfg.items() if k in _CONSTRAINT_FIELDS}
        rules.append(
            Rule(
                name=cfg["name"],
                condition=_build_condition(cfg),
                constraint=constraint,
                priority=cfg.get("priority", 0),
            )
        )
    return rules


_RULES_TOML_DEFAULTS: dict = {
    "rules": [
        {
            "name": "highway_audio_only",
            "scenario": "highway",
            "allowed_channels": ["audio"],
            "max_frequency_minutes": 30,
            "priority": 10,
        },
        {
            "name": "fatigue_suppress",
            "fatigue_above": 0.7,
            "only_urgent": True,
            "allowed_channels": ["audio"],
            "priority": 20,
        },
        {
            "name": "overloaded_postpone",
            "workload": "overloaded",
            "postpone": True,
            "priority": 15,
        },
        {
            "name": "parked_all_channels",
            "scenario": "parked",
            "allowed_channels": ["visual", "audio", "detailed"],
            "priority": 5,
        },
        {
            "name": "city_driving_limit",
            "scenario": "city_driving",
            "allowed_channels": ["audio"],
            "max_frequency_minutes": 15,
            "priority": 8,
        },
        {
            "name": "traffic_jam_calm",
            "scenario": "traffic_jam",
            "allowed_channels": ["audio", "visual"],
            "max_frequency_minutes": 10,
            "priority": 7,
        },
        {
            "name": "passenger_present_relax",
            "has_passengers": True,
            "not_scenario": "highway",
            "extra_channels": ["visual"],
            "priority": 3,
        },
    ],
}


_RULES_PATH: Path = get_config_root() / "rules.toml"
# ensure_config 内部全 catch（I/O 失败返默认 dict），
# load_rules 内部有 _FALLBACK_RULES 兜底，两者均不抛。
ensure_config(_RULES_PATH, _RULES_TOML_DEFAULTS)
SAFETY_RULES: list[Rule] = load_rules(_RULES_PATH)


def apply_rules(
    driving_context: dict,
    rules: list[Rule] | None = None,
) -> dict[str, Any]:
    """对驾驶上下文应用规则，返回合并后的约束."""
    matched = [r for r in (rules or SAFETY_RULES) if r.condition(driving_context)]
    matched.sort(key=lambda r: r.priority, reverse=True)

    channels_rules = [r for r in matched if "allowed_channels" in r.constraint]
    if channels_rules:
        channels = set(channels_rules[0].constraint["allowed_channels"])
        for r in channels_rules[1:]:
            channels &= set(r.constraint["allowed_channels"])
        if not channels:
            channels = {"visual", "audio", "detailed"}
        merged_channels = list(channels)
    else:
        merged_channels = sorted(["visual", "audio", "detailed"])

    # extra_channels：交集后追加
    extra = set()
    for r in matched:
        ec = r.constraint.get("extra_channels", [])
        if isinstance(ec, list):
            extra.update(ec)
    if extra:
        merged_channels = sorted(set(merged_channels) | extra)

    only_urgent = any(r.constraint.get("only_urgent", False) for r in matched)
    postpone = any(r.constraint.get("postpone", False) for r in matched)

    freq_rules = [r for r in matched if "max_frequency_minutes" in r.constraint]
    max_freq = (
        min(r.constraint["max_frequency_minutes"] for r in freq_rules)
        if freq_rules
        else None
    )

    result: dict[str, Any] = {
        "allowed_channels": merged_channels,
        "only_urgent": only_urgent,
        "postpone": postpone,
    }
    if max_freq is not None:
        result["max_frequency_minutes"] = max_freq
    return result


def postprocess_decision(
    decision: dict, driving_context: dict
) -> tuple[dict, list[str]]:
    """在 LLM 决策后强制应用安全规则，不可绕过。

    Returns:
        (修改后的决策, 被修改的字段列表)

    """
    if _ablation_disable_rules.get():
        return decision, []

    result = dict(decision)
    # LLM 可能输出 null，归一化为 ""，避免下游 None 检查
    if "reminder_content" in result and result["reminder_content"] is None:
        result["reminder_content"] = ""
    modifications: list[str] = []
    constraints = apply_rules(driving_context)

    # 硬约束 1：postpone → 禁止发送
    if constraints.get("postpone", False):
        if result.get("should_remind", True):
            modifications.append("should_remind→false(postpone)")
        if result.get("reminder_content"):
            modifications.append("reminder_content→cleared(postpone)")
        result["should_remind"] = False
        result["reminder_content"] = ""

    # 硬约束 2：allowed_channels 过滤
    allowed = constraints.get("allowed_channels")
    if allowed is not None:
        channels = result.get("allowed_channels", list(allowed))
        if isinstance(channels, list):
            filtered = [c for c in channels if c in allowed]
            if len(filtered) != len(channels):
                removed = set(channels) - set(filtered)
                modifications.append(f"allowed_channels −{removed}")
            result["allowed_channels"] = filtered or allowed

    # 硬约束 3：only_urgent → 非紧急类型禁止
    if constraints.get("only_urgent", False):
        event_type = (result.get("type", "general") or "").lower()
        if event_type not in URGENT_TYPES:
            if result.get("should_remind", True):
                modifications.append("should_remind→false(only_urgent)")
            if result.get("reminder_content"):
                modifications.append("reminder_content→cleared(only_urgent)")
            result["should_remind"] = False
            result["reminder_content"] = ""

    return result, modifications
