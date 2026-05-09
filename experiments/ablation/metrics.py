"""消融实验指标计算."""

import math

from .types import JudgeScores


def cohens_d(group_a: list[float], group_b: list[float]) -> float:
    """Cohen's d 效应量。

    当两组方差均为 0（所有值相同）时：
    - 均值相等 → 返回 0.0（无效应）
    - 均值不等 → 返回 math.inf（按均值差符号取 ±inf）
    """
    if not group_a or not group_b:
        return 0.0
    mean_a = sum(group_a) / len(group_a)
    mean_b = sum(group_b) / len(group_b)
    var_a = (
        sum((x - mean_a) ** 2 for x in group_a) / (len(group_a) - 1)
        if len(group_a) > 1
        else 0
    )
    var_b = (
        sum((x - mean_b) ** 2 for x in group_b) / (len(group_b) - 1)
        if len(group_b) > 1
        else 0
    )
    if var_a + var_b == 0:
        if mean_a == mean_b:
            return 0.0
        return math.copysign(math.inf, mean_a - mean_b)
    pooled_std = math.sqrt((var_a + var_b) / 2)
    return (mean_a - mean_b) / pooled_std


def compute_comparison(
    scores: list[JudgeScores],
    baseline: str = "full",
) -> dict:
    """计算基线 vs 各变体的对比指标。

    Returns: {variant: {mean_score, mean_diff, cohens_d, n}}
    """
    variant_scores: dict[str, list[float]] = {}
    for s in scores:
        variant_scores.setdefault(s.variant.value, []).append(float(s.overall_score))

    baseline_overalls = variant_scores.get(baseline, [])
    comparison: dict = {}
    for variant, overalls in variant_scores.items():
        if variant == baseline:
            continue
        comparison[variant] = {
            "mean_score": sum(overalls) / len(overalls) if overalls else 0,
            "mean_diff": (sum(overalls) / len(overalls) if overalls else 0)
            - (
                sum(baseline_overalls) / len(baseline_overalls)
                if baseline_overalls
                else 0
            ),
            "cohens_d": cohens_d(overalls, baseline_overalls),
            "n": len(overalls),
        }
    return comparison


def compute_safety_comparison(scores: list[JudgeScores]) -> dict:
    """安全性组专用对比。包含安全合规率、拦截率、违规类型分布。"""
    comparison = compute_comparison(scores)
    for variant_group in _group_by_variant(scores).values():
        variant = variant_group[0].variant.value
        flags_count: dict[str, int] = {}
        for s in variant_group:
            for flag in s.violation_flags:
                flags_count[flag] = flags_count.get(flag, 0) + 1
        if variant in comparison:
            comparison[variant]["violation_flags_dist"] = flags_count
    return comparison


def _group_by_variant(scores: list[JudgeScores]) -> dict[str, list[JudgeScores]]:
    groups: dict[str, list[JudgeScores]] = {}
    for s in scores:
        groups.setdefault(s.variant.value, []).append(s)
    return groups
