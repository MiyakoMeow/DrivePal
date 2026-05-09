"""架构组实验——四 Agent 流水线 vs 单 LLM 调用的决策质量对比."""

import json
import os
from pathlib import Path

import aiofiles

from .ablation_runner import AblationRunner
from .judge import Judge
from .types import (
    GroupResult,
    JudgeScores,
    Scenario,
    Variant,
    VariantResult,
)

FATIGUE_THRESHOLD: float = float(os.getenv("FATIGUE_THRESHOLD", "0.7"))


async def run_architecture_group(
    runner: AblationRunner,
    judge: Judge,
    scenarios: list[Scenario],
    output_path: Path,
) -> GroupResult:
    """架构组实验。

    变体: FULL, SINGLE_LLM
    场景: 非安全关键场景（排除 highway 及高疲劳/过载的 city_driving）
    """
    variants = [Variant.FULL, Variant.SINGLE_LLM]
    arch_scenarios = [s for s in scenarios if _is_arch_scenario(s)]

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

    metrics = compute_quality_metrics(scores, results)

    full_results = [r for r in results if r.variant == Variant.FULL]
    stage_scores_by_scenario: dict[str, dict] = {}
    for fr in full_results:
        stage_scores = await judge.score_stages(fr)
        stage_scores_by_scenario[fr.scenario_id] = stage_scores
    if stage_scores_by_scenario:
        context_scores = [
            v["context"]["score"]
            for v in stage_scores_by_scenario.values()
            if "context" in v and isinstance(v["context"].get("score"), (int, float))
        ]
        task_scores = [
            v["task"]["score"]
            for v in stage_scores_by_scenario.values()
            if "task" in v and isinstance(v["task"].get("score"), (int, float))
        ]
        decision_scores = [
            v["decision"]["score"]
            for v in stage_scores_by_scenario.values()
            if "decision" in v and isinstance(v["decision"].get("score"), (int, float))
        ]
        metrics["stage_scores"] = {
            "context": sum(context_scores) / len(context_scores)
            if context_scores
            else 0,
            "task": sum(task_scores) / len(task_scores) if task_scores else 0,
            "decision": sum(decision_scores) / len(decision_scores)
            if decision_scores
            else 0,
        }

    return GroupResult(
        group="architecture",
        variant_results=results,
        judge_scores=scores,
        metrics=metrics,
    )


def compute_quality_metrics(
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


def _is_arch_scenario(s: Scenario) -> bool:
    """判定场景是否属于架构组（排除安全关键场景）。"""
    scenario = s.driving_context.get("scenario", "")
    driver = s.driving_context.get("driver", {})
    fatigue = driver.get("fatigue_level", 0)
    workload = driver.get("workload", "")
    return (
        scenario != "highway"
        and fatigue <= FATIGUE_THRESHOLD
        and workload != "overloaded"
    )
