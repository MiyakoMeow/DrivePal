"""安全性组实验——测试规则引擎 + 概率推断对安全决策的贡献."""

import logging

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
        variants=[Variant.FULL, Variant.NO_RULES, Variant.NO_PROB, Variant.NO_SAFETY],
        scenario_filter=lambda s: s.safety_relevant,
        metrics_computer=compute_safety_metrics,
    )


def compute_safety_metrics(
    scores: list[JudgeScores],
    results: list[VariantResult],
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

        fallback_variants = {Variant.NO_RULES.value, Variant.NO_SAFETY.value}
        if variant in fallback_variants:
            objective_compliant = compliant
        else:
            objective_compliant = sum(1 for r in variant_results if not r.modifications)
        objective_compliance_rate = objective_compliant / n_results if n_results else 0

        metrics[variant] = {
            "n": n,
            "compliance_rate": compliant / n if n else 0,
            "interception_rate": intercepted / n_results if n_results else 0,
            "avg_overall_score": avg_quality,
            "objective_compliance_rate": objective_compliance_rate,
            "objective_compliant_n": objective_compliant,
        }
    metrics["_judge_degradation"] = detect_judge_degradation(scores)
    metrics["_comparison"] = compute_safety_comparison(scores)
    return metrics
