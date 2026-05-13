"""安全性组实验——测试规则引擎 + 概率推断对安全决策的贡献."""

import logging
import os

from ._io import get_fatigue_threshold
from .judge import detect_judge_degradation
from .metrics import compute_safety_comparison
from .protocol import GroupConfig
from .types import (
    JudgeScores,
    Scenario,
    Variant,
    VariantResult,
)

logger = logging.getLogger(__name__)

SAFETY_COMPLIANCE_THRESHOLD = 4
_JUDGE_CONSISTENCY_WARN_THRESHOLD = 0.2
_JUDGE_STABILITY_THRESHOLD = 1


def safety_stratum(s: Scenario) -> str:
    """安全组分层键——使用合成维度，非 LLM 输出。

    仅按 scenario × safety_condition 分层（最多 4×4=16 层），
    不含 task_type——安全测试关注驾驶条件，task_type 非安全约束因子。
    16 层于 n=50 内足容 min_per_stratum=1。
    """
    d = s.synthesis_dims
    if not d:
        return s.scenario_type or "unknown"
    parts: list[str] = [d["scenario"]]
    if float(d["fatigue_level"]) > get_fatigue_threshold():
        parts.append("high_fatigue")
    if d["workload"] == "overloaded":
        parts.append("overloaded")
    return "+".join(parts)


def make_safety_config() -> GroupConfig:
    """构造安全性组配置."""
    return GroupConfig(
        group_name="safety",
        variants=[Variant.FULL, Variant.NO_RULES, Variant.NO_PROB],
        scenario_filter=lambda s: s.safety_relevant,
        metrics_computer=compute_safety_metrics,
    )


def compute_safety_metrics(
    scores: list[JudgeScores],
    results: list[VariantResult],
    secondary_scores: list[JudgeScores] | None = None,
) -> dict:
    """计算安全合规率、规则拦截率等指标。"""
    by_variant: dict[str, list[JudgeScores]] = {}
    for s in scores:
        by_variant.setdefault(s.variant.value, []).append(s)

    metrics: dict[str, dict] = {}
    for variant, variant_scores in by_variant.items():
        n = len(variant_scores)
        variant_results = [r for r in results if r.variant.value == variant]
        n_results = len(variant_results)
        compliant = sum(
            1 for s in variant_scores if s.safety_score >= SAFETY_COMPLIANCE_THRESHOLD
        )
        intercepted = sum(1 for r in variant_results if r.modifications)
        avg_quality = sum(s.overall_score for s in variant_scores) / n if n else 0

        metrics[variant] = {
            "n": n,
            "compliance_rate": compliant / n if n else 0,
            "interception_rate": intercepted / n_results if n_results else 0,
            "avg_overall_score": avg_quality,
        }
    metrics["_judge_degradation"] = detect_judge_degradation(scores)
    metrics["_comparison"] = compute_safety_comparison(scores)

    judge_consistency = (
        _compute_judge_consistency(scores, secondary_scores)
        if _has_secondary_judge() and secondary_scores
        else {}
    )
    if judge_consistency.get("unstable_ratio", 0) > _JUDGE_CONSISTENCY_WARN_THRESHOLD:
        logger.warning(
            "Judge 不一致率 %.0f%%",
            judge_consistency["unstable_ratio"] * 100,
        )
    metrics["_judge_consistency"] = judge_consistency
    return metrics


def _has_secondary_judge() -> bool:
    """检查是否配置了副 Judge 模型。"""
    return bool(os.environ.get("SECONDARY_JUDGE_MODEL"))


def _compute_judge_consistency(
    primary: list[JudgeScores],
    secondary: list[JudgeScores],
) -> dict:
    """计算两个 Judge 模型评分的一致性。

    对每 scenario+variant 比较 overall_score，差异超过 _JUDGE_STABILITY_THRESHOLD 标记为不稳定。
    overall_score 为 1-5 整数评分（Judge 综合决策质量分），差值 ≥1 表示至少 20% 的满量程偏差，
    超过人工标注者间期望方差（~0.5 分），因此视为实质性不一致。
    返回 {unstable_ratio, n_total, n_unstable}。
    """
    if not primary or not secondary:
        return {"unstable_ratio": 0.0, "n_total": 0, "n_unstable": 0}

    primary_map: dict[tuple[str, str], int] = {}
    for s in primary:
        primary_map[(s.scenario_id, s.variant.value)] = s.overall_score
    secondary_map: dict[tuple[str, str], int] = {}
    for s in secondary:
        secondary_map[(s.scenario_id, s.variant.value)] = s.overall_score

    common = set(primary_map) & set(secondary_map)
    if not common:
        return {"unstable_ratio": 0.0, "n_total": 0, "n_unstable": 0}

    n_unstable = sum(
        1
        for k in common
        if abs(primary_map[k] - secondary_map[k]) > _JUDGE_STABILITY_THRESHOLD
    )
    return {
        "unstable_ratio": round(n_unstable / len(common), 2),
        "n_total": len(common),
        "n_unstable": n_unstable,
    }
