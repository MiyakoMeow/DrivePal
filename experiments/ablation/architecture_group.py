"""架构组实验——四 Agent 流水线 vs 单 LLM 调用的决策质量对比."""

import json
from pathlib import Path

import aiofiles

from experiments.ablation.ablation_runner import AblationRunner
from experiments.ablation.judge import Judge
from experiments.ablation.types import (
    GroupResult,
    JudgeScores,
    Scenario,
    Variant,
    VariantResult,
)


async def run_architecture_group(
    runner: AblationRunner,
    judge: Judge,
    scenarios: list[Scenario],
    output_path: Path,
) -> GroupResult:
    """架构组实验。

    变体: FULL, SINGLE_LLM
    场景: 非安全关键场景 (safety_relevant=False)
    """
    variants = [Variant.FULL, Variant.SINGLE_LLM]
    arch_scenarios = [s for s in scenarios if not s.safety_relevant]

    results = await runner.run_batch(arch_scenarios, variants)

    scores: list[JudgeScores] = []
    for scenario in arch_scenarios:
        scenario_results = [r for r in results if r.scenario_id == scenario.id]
        batch_scores = await judge.score_batch(scenario, scenario_results)
        scores.extend(batch_scores)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(output_path, "w") as f:
        for r in results:
            await f.write(
                json.dumps(
                    {
                        "scenario_id": r.scenario_id,
                        "variant": r.variant.value,
                        "decision": r.decision,
                        "latency_ms": r.latency_ms,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    metrics = _compute_quality_metrics(scores, results)
    return GroupResult(
        group="architecture",
        variant_results=results,
        judge_scores=scores,
        metrics=metrics,
    )


def _compute_quality_metrics(
    scores: list[JudgeScores], results: list[VariantResult]
) -> dict:
    """计算决策质量指标（评分均值、P50/P90 延迟）。"""
    by_variant: dict[str, list[JudgeScores]] = {}
    for s in scores:
        by_variant.setdefault(s.variant.value, []).append(s)

    metrics: dict[str, dict] = {}
    for variant, variant_scores in by_variant.items():
        n = len(variant_scores)
        variant_results = [r for r in results if r.variant.value == variant]
        latencies = sorted([r.latency_ms for r in variant_results])
        p50 = latencies[len(latencies) // 2] if latencies else 0
        p90_idx = int(len(latencies) * 0.9)
        p90 = latencies[min(p90_idx, len(latencies) - 1)] if latencies else 0

        metrics[variant] = {
            "n": n,
            "avg_overall_score": (
                sum(s.overall_score for s in variant_scores) / n if n else 0
            ),
            "avg_safety_score": (
                sum(s.safety_score for s in variant_scores) / n if n else 0
            ),
            "avg_reasonableness_score": (
                sum(s.reasonableness_score for s in variant_scores) / n if n else 0
            ),
            "latency_p50_ms": p50,
            "latency_p90_ms": p90,
        }
    return metrics
