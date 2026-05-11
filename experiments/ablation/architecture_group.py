"""架构组实验——四 Agent 流水线 vs 单 LLM 调用的决策质量对比."""

import asyncio
import logging
import os
import statistics
from pathlib import Path
from typing import Any

from ._io import dump_variant_results_jsonl
from .ablation_runner import AblationRunner
from .judge import Judge
from .types import (
    GroupResult,
    JudgeScores,
    Scenario,
    Variant,
    VariantResult,
)

logger = logging.getLogger(__name__)


def _get_fatigue_threshold() -> float:
    """安全读取 FATIGUE_THRESHOLD 环境变量，解析失败回退默认 0.7。"""
    raw = os.getenv("FATIGUE_THRESHOLD", "0.7").strip()
    try:
        return float(raw)
    except ValueError:
        logger.warning("FATIGUE_THRESHOLD=%r 无效，使用默认值 0.7", raw)
        return 0.7


FATIGUE_THRESHOLD: float = _get_fatigue_threshold()
"""与 scenario_synthesizer.FATIGUE_SAFETY_THRESHOLD 同源（同一环境变量），此处用于架构组场景过滤。"""


def _arch_stratum(s: Scenario) -> str:
    """架构组分层键——按 scenario × task_type 组合分组，保证覆盖。"""
    scenario = s.driving_context.get("scenario", "unknown")
    return f"{scenario}:{s.expected_task_type}"


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

    results = await runner.run_batch(
        arch_scenarios, variants, checkpoint_path=output_path
    )

    scores: list[JudgeScores] = []

    async def score_one(scenario: Scenario) -> list[JudgeScores]:
        vrs = [r for r in results if r.scenario_id == scenario.id]
        return await judge.score_batch(scenario, vrs)

    tasks = [score_one(s) for s in arch_scenarios]
    scores_batches = await asyncio.gather(*tasks, return_exceptions=True)
    for batch in scores_batches:
        if isinstance(batch, Exception):
            logger.error("Judge scoring failed: %s", batch)
        elif isinstance(batch, list):
            scores.extend(batch)

    await dump_variant_results_jsonl(output_path, results, include_modifications=True)

    metrics = compute_quality_metrics(scores, results)

    full_results = [r for r in results if r.variant == Variant.FULL]
    metrics["stage_scores"] = await _aggregate_full_stage_scores(judge, full_results)

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
        if len(latencies) >= 2:
            percentiles = statistics.quantiles(latencies, n=100, method="inclusive")
            p50 = percentiles[49]
            p90 = percentiles[89]
        elif len(latencies) == 1:
            p50 = p90 = latencies[0]
        else:
            p50 = p90 = 0.0

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


async def _aggregate_full_stage_scores(
    judge: Judge, full_results: list[VariantResult]
) -> dict[str, float]:
    """聚合所有 Full 变体的中间阶段平均评分（并发）。"""

    async def _score_one(fr: VariantResult) -> dict:
        try:
            return await judge.score_stages(fr)
        except Exception as exc:
            logger.warning("Stage scoring failed: %s", exc)
            return {}

    tasks = [asyncio.create_task(_score_one(fr)) for fr in full_results]
    raw_scores = await asyncio.gather(*tasks, return_exceptions=True)
    all_scores: list[dict[str, Any]] = []
    for r in raw_scores:
        if isinstance(r, Exception):
            logger.warning("Stage scoring task failed: %s", r)
        elif isinstance(r, dict):
            all_scores.append(r)

    ctx_scores: list[float] = []
    task_scores: list[float] = []
    dec_scores: list[float] = []
    for stage_scores in all_scores:
        if stage_scores.get("context", {}).get("score", 0) > 0:
            ctx_scores.append(stage_scores["context"]["score"])
        if stage_scores.get("task", {}).get("score", 0) > 0:
            task_scores.append(stage_scores["task"]["score"])
        if stage_scores.get("decision", {}).get("score", 0) > 0:
            dec_scores.append(stage_scores["decision"]["score"])
    return {
        "context": sum(ctx_scores) / len(ctx_scores) if ctx_scores else 0.0,
        "task": sum(task_scores) / len(task_scores) if task_scores else 0.0,
        "decision": sum(dec_scores) / len(dec_scores) if dec_scores else 0.0,
    }


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
