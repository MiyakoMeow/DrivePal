"""轻量规则引擎 — 安全约束规则定义与合并."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass
class Rule:
    """安全约束规则."""

    name: str
    condition: Callable[[dict], bool]
    constraint: dict[str, Any]
    priority: int = 0


SCENARIO_HIGHWAY = "highway"
SCENARIO_PARKED = "parked"
WORKLOAD_OVERLOADED = "overloaded"
# 疲劳阈值，超过此值触发疲劳抑制规则
FATIGUE_THRESHOLD = 0.7


SAFETY_RULES: list[Rule] = [
    Rule(
        name="highway_audio_only",
        condition=lambda ctx: ctx.get("scenario") == SCENARIO_HIGHWAY,
        constraint={"allowed_channels": ["audio"], "max_frequency_minutes": 30},
        priority=10,
    ),
    Rule(
        name="fatigue_suppress",
        condition=lambda ctx: (
            ctx.get("driver", {}).get("fatigue_level", 0) > FATIGUE_THRESHOLD
        ),
        constraint={"only_urgent": True, "allowed_channels": ["audio"]},
        priority=20,
    ),
    Rule(
        name="overloaded_postpone",
        condition=lambda ctx: (
            ctx.get("driver", {}).get("workload", "") == WORKLOAD_OVERLOADED
        ),
        constraint={"postpone": True},
        priority=15,
    ),
    Rule(
        name="parked_all_channels",
        condition=lambda ctx: ctx.get("scenario") == SCENARIO_PARKED,
        constraint={"allowed_channels": ["visual", "audio", "detailed"]},
        priority=5,
    ),
]


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
        merged_channels = sorted(channels)
    else:
        merged_channels = sorted(["visual", "audio", "detailed"])

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


def format_constraints(constraints: dict[str, Any]) -> str:
    """将约束字典格式化为中文提示文本."""
    lines = ["【安全约束规则】", "你必须遵守以下约束（由系统规则引擎生成，不可违反）："]
    ch = constraints.get("allowed_channels")
    if ch:
        lines.append(f"- 允许的提醒通道: {ch}")
    if constraints.get("only_urgent"):
        lines.append("- 仅允许紧急提醒: true")
    freq = constraints.get("max_frequency_minutes")
    if freq is not None:
        lines.append(f"- 最大提醒频率: {freq}分钟")
    if constraints.get("postpone"):
        lines.append("- 当前状态需要延后提醒")
    lines.append("")
    lines.append("请在以上约束范围内做出决策。")
    return "\n".join(lines)
