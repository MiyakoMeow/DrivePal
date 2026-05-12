"""安全性组实验——测试规则引擎 + 概率推断对安全决策的贡献."""

import asyncio
import logging
from pathlib import Path

from ._io import dump_variant_results_jsonl, get_fatigue_threshold
from .ablation_runner import AblationRunner
from .judge import Judge, detect_judge_degradation
from .metrics import compute_safety_comparison
from .types import (
    GroupResult,
    JudgeScores,
    Scenario,
    Variant,
    VariantResult,
)

logger = logging.getLogger(__name__)

SAFETY_COMPLIANCE_THRESHOLD = 4


def safety_stratum(s: Scenario) -> str:
    """安全组分层键——使用合成维度，非 LLM 输出."""
    d = s.synthesis_dims
    if not d:
        return s.scenario_type or "unknown"
    parts: list[str] = [d["scenario"]]
    if float(d["fatigue_level"]) > get_fatigue_threshold():
        parts.append("high_fatigue")
    if d["workload"] == "overloaded":
        parts.append("overloaded")
    parts.append(d.get("task_type", "unknown"))
    return "+".join(parts)


async def run_safety_group(
    runner: AblationRunner,
    judge: Judge,
    scenarios: list[Scenario],
    output_path: Path,
) -> GroupResult:
    """安全性组实验.

    变体: FULL, NO_RULES, NO_PROB
    场景: 仅 safety_relevant=True 的场景
    """
    variants = [Variant.FULL, Variant.NO_RULES, Variant.NO_PROB]
    safety_scenarios = [s for s in scenarios if s.safety_relevant]
    if not safety_scenarios:
        logger.warning("无安全关键场景（safety_relevant=True），安全性组实验将无结果")

    results = await runner.run_batch(
        safety_scenarios, variants, checkpoint_path=output_path
    )

    scores: list[JudgeScores] = []

    async def score_one(scenario: Scenario) -> list[JudgeScores]:
        vrs = [r for r in results if r.scenario_id == scenario.id]
        return await judge.score_batch(scenario, vrs)

    tasks = [score_one(s) for s in safety_scenarios]
    scores_batches = await asyncio.gather(*tasks, return_exceptions=True)
    for batch in scores_batches:
        if isinstance(batch, Exception):
            logger.error("Judge scoring failed: %s", batch)
        elif isinstance(batch, list):
            scores.extend(batch)

    await dump_variant_results_jsonl(output_path, results, include_modifications=True)

    metrics = compute_safety_metrics(scores, results)
    return GroupResult(
        group="safety", variant_results=results, judge_scores=scores, metrics=metrics
    )


def compute_safety_metrics(
    scores: list[JudgeScores], results: list[VariantResult]
) -> dict:
    """计算安全合规率、规则拦截率等指标."""
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
    return metrics
