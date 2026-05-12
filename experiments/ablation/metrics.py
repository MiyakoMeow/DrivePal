"""消融实验指标计算."""

import math
import random

from scipy.stats import wilcoxon as _scipy_wilcoxon

from .types import JudgeScores


def cohens_d(group_a: list[float], group_b: list[float]) -> float:
    """Cohen's d 效应量.

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


def bootstrap_ci(
    group_a: list[float],
    group_b: list[float],
    *,
    n_bootstrap: int = 10000,
    alpha: float = 0.05,
    seed: int = 42,
) -> dict[str, float | bool]:
    """Bootstrap 置信区间——对均值差做重采样.

    返回 {ci_lower, ci_upper, significant, observed_diff}。
    significant = True 当 CI 不含 0。
    """
    if not group_a or not group_b:
        return {
            "ci_lower": 0.0,
            "ci_upper": 0.0,
            "significant": False,
            "observed_diff": 0.0,
        }

    rng = random.Random(seed)
    n_a, n_b = len(group_a), len(group_b)
    observed = sum(group_a) / n_a - sum(group_b) / n_b

    diffs: list[float] = []
    for _ in range(n_bootstrap):
        sample_a = rng.choices(group_a, k=n_a)
        sample_b = rng.choices(group_b, k=n_b)
        diffs.append(sum(sample_a) / n_a - sum(sample_b) / n_b)

    diffs.sort()
    lower = diffs[int(n_bootstrap * alpha / 2)]
    upper = diffs[int(n_bootstrap * (1 - alpha / 2))]

    return {
        "ci_lower": lower,
        "ci_upper": upper,
        "significant": not (lower <= 0 <= upper),
        "observed_diff": observed,
    }


def wilcoxon_test(
    scores: list[JudgeScores],
    baseline: str = "full",
) -> dict[str, dict]:
    """Wilcoxon signed-rank test——按 scenario_id 配对.

    返回 {variant: {statistic, p_value, n_pairs}}。
    """
    by_pair: dict[str, dict[str, list[float]]] = {}
    for s in scores:
        by_pair.setdefault(s.scenario_id, {}).setdefault(s.variant.value, []).append(
            s.overall_score
        )

    by_variant: dict[str, list[tuple[float, float]]] = {}
    for variants in by_pair.values():
        if baseline not in variants:
            continue
        baseline_val = variants[baseline][0]
        for vname, vvals in variants.items():
            if vname == baseline:
                continue
            by_variant.setdefault(vname, []).append((baseline_val, vvals[0]))

    result: dict[str, dict] = {}
    for vname, pairs in by_variant.items():
        diffs = [a - b for a, b in pairs]
        non_zero = [d for d in diffs if d != 0]
        if len(non_zero) < 2:
            result[vname] = {"statistic": 0.0, "p_value": 1.0, "n_pairs": len(pairs)}
            continue
        stat, p = _scipy_wilcoxon(non_zero)
        result[vname] = {
            "statistic": float(stat),
            "p_value": float(p),
            "n_pairs": len(pairs),
        }

    return result


def compute_comparison(
    scores: list[JudgeScores],
    baseline: str = "full",
) -> dict:
    """计算基线 vs 各变体的对比指标.

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
            # cohens_d(variant, baseline) → 正值表示 variant 优于 baseline
            "cohens_d": cohens_d(overalls, baseline_overalls),
            "n": len(overalls),
        }

    for variant, variant_data in comparison.items():
        variant_scores_list = variant_scores.get(variant, [])
        if variant_scores_list and baseline_overalls:
            variant_data["bootstrap_ci"] = bootstrap_ci(
                variant_scores_list, baseline_overalls
            )

    comparison["_wilcoxon"] = wilcoxon_test(scores, baseline)
    return comparison


def compute_safety_comparison(scores: list[JudgeScores]) -> dict:
    """安全性组专用对比。包含安全合规率、拦截率、违规类型分布."""
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
