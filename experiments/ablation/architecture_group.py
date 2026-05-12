"""架构组实验——四 Agent 流水线 vs 单 LLM 调用的决策质量对比."""

import asyncio
import dataclasses
import logging
import statistics
from typing import Any

from ._io import get_fatigue_threshold
from .judge import Judge, detect_judge_degradation
from .metrics import compute_comparison
from .protocol import GroupConfig
from .types import (
    GroupResult,
    JudgeScores,
    Scenario,
    Variant,
    VariantResult,
)

logger = logging.getLogger(__name__)


def arch_stratum(s: Scenario) -> str:
    """架构组分层键——使用合成维度。"""
    d = s.synthesis_dims
    if not d:
        return f"{s.scenario_type}:{s.expected_task_type}"
    return f"{d['scenario']}:{d['task_type']}"


def make_architecture_config() -> GroupConfig:
    """构造架构组配置（含 stage_scores post_hook）。"""
    return GroupConfig(
        group_name="architecture",
        variants=[Variant.FULL, Variant.SINGLE_LLM],
        scenario_filter=is_arch_scenario,
        metrics_computer=compute_quality_metrics,
        post_hook=_stage_scores_hook,
    )


async def _stage_scores_hook(
    gr: GroupResult,
    judge: Judge,
    _scenarios: list[Scenario],
) -> GroupResult:
    """架构组后处理：聚合 Full 变体中间阶段评分。

    返回新 GroupResult（不原地修改），保持数据流不可变。
    """
    full_results = [r for r in gr.variant_results if r.variant == Variant.FULL]
    return dataclasses.replace(
        gr,
        metrics={
            **gr.metrics,
            "stage_scores": await _aggregate_full_stage_scores(judge, full_results),
        },
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
    metrics["_judge_degradation"] = detect_judge_degradation(scores)
    metrics["_comparison"] = compute_comparison(scores)
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

    tasks = [_score_one(fr) for fr in full_results]
    raw_scores = await asyncio.gather(*tasks, return_exceptions=True)
    all_scores: list[dict[str, Any]] = []
    for r in raw_scores:
        if isinstance(r, asyncio.CancelledError):
            raise r  # 传播取消语义
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


def is_arch_scenario(s: Scenario) -> bool:
    """判定场景是否属于架构组——使用合成维度。"""
    d = s.synthesis_dims
    if not d:
        return False
    return (
        d["scenario"] != "highway"
        and float(d["fatigue_level"]) <= get_fatigue_threshold()
        and d["workload"] != "overloaded"
    )
