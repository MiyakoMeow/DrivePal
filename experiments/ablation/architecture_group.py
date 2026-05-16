"""架构组实验——三 Agent 流水线 vs 单 LLM 调用的决策质量对比."""

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


def classify_complexity(dims: dict) -> bool:
    """判断场景是否复杂：highway OR 高疲劳 OR 过载。

    阈值与 _io.get_fatigue_threshold() 对齐。
    用于架构组 2x2 的指标分层。
    缺失 fatigue 数据时默认 0——保守假设无疲劳，避免误归为复杂场景扭曲统计。
    """
    fatigue = dims.get("fatigue_level", 0)
    try:
        fatigue_val = float(fatigue)
    except ValueError, TypeError:
        fatigue_val = 0.0
    return (
        dims.get("scenario") == "highway"
        or fatigue_val > get_fatigue_threshold()
        or dims.get("workload") == "overloaded"
    )


def make_architecture_config(
    scenario_complexity_map: dict[str, bool] | None = None,
) -> GroupConfig:
    """构造架构组配置（含 stage_scores post_hook）。

    scenario_complexity_map: scenario_id → is_complex，用于指标分层。
    None 或空 dict 时 metrics 保持扁平（向后兼容）。
    """

    def _metrics(scores: list[JudgeScores], results: list[VariantResult]) -> dict:
        return compute_quality_metrics(
            scores, results, complexity_map=scenario_complexity_map or {}
        )

    return GroupConfig(
        group_name="architecture",
        variants=[Variant.FULL, Variant.SINGLE_LLM],
        scenario_filter=lambda _: True,
        metrics_computer=_metrics,
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


def _compute_variant_metrics(
    scores: list[JudgeScores],
    results: list[VariantResult],
) -> dict[str, dict]:
    """按 variant 分组计算指标（共享逻辑）。"""
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


def _split_by_complexity(
    scores: list[JudgeScores],
    results: list[VariantResult],
    complexity_map: dict[str, bool],
) -> tuple:
    """将 scores/results 按复杂度分为 simple/complex 两组。"""
    simple_scores = [s for s in scores if not complexity_map.get(s.scenario_id, False)]
    complex_scores = [s for s in scores if complexity_map.get(s.scenario_id, False)]
    simple_results = [
        r for r in results if not complexity_map.get(r.scenario_id, False)
    ]
    complex_results = [r for r in results if complexity_map.get(r.scenario_id, False)]
    return simple_scores, complex_scores, simple_results, complex_results


def compute_quality_metrics(
    scores: list[JudgeScores],
    results: list[VariantResult],
    complexity_map: dict[str, bool] | None = None,
) -> dict:
    """计算决策质量指标（评分均值、P50/P90 延迟）。

    传 complexity_map 时输出双层结构（simple/complex），
    不传或空 dict 时输出扁平结构（向后兼容）。
    """
    if not complexity_map:
        metrics = _compute_variant_metrics(scores, results)
        metrics["_judge_degradation"] = detect_judge_degradation(scores)
        metrics["_comparison"] = compute_comparison(scores)
        return metrics

    simple_scores, complex_scores, simple_results, complex_results = (
        _split_by_complexity(scores, results, complexity_map)
    )
    return {
        "simple": _compute_variant_metrics(simple_scores, simple_results),
        "complex": _compute_variant_metrics(complex_scores, complex_results),
        "comparison_simple": compute_comparison(simple_scores),
        "comparison_complex": compute_comparison(complex_scores),
        "_judge_degradation": detect_judge_degradation(scores),
    }


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
