"""公共实验编排协议.

设计决策：
- GroupConfig 声明式：每组实验的变体列表、场景过滤、指标计算通过
  dataclass 组合而非子类化。原因：消融实验三组之间仅在配置上有差异（安全性/
  架构/个性化），行为完全一致——声明式比继承树更直观、更易复用。
- filter → run_batch → score → dump → metrics → post_hook 固定流水线：
  各组实验的编排步骤完全相同，差异通过 config 参数化注入。post_hook 用于
  架构组的中间阶段评分聚合等组特化逻辑，不影响通用流水线。
- 并发粒度：score_scenarios_concurrent 按场景并发（每个场景并发评分所有变体），
  而非按变体×场景笛卡尔积并发。原因：Judge.score_batch 内部已按变体并发，
  外层再次并发仅增加调度开销，不减少总耗时。
- CancelledError 显式传播：Python 3.9+ 中它不再是 Exception 子类，
  asyncio.gather(return_exceptions=True) 不会将其自动识别为异常，
  必须显式检查并重抛以保留取消语义。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._io import dump_variant_results_jsonl
from .types import (
    BatchResult,
    GroupResult,
    JudgeScores,
    Scenario,
    Variant,
    VariantResult,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .ablation_runner import AblationRunner
    from .judge import Judge

logger = logging.getLogger(__name__)


@dataclass
class GroupConfig:
    """一组实验的声明式配置."""

    group_name: str
    variants: list[Variant]
    scenario_filter: Callable[[Scenario], bool]
    metrics_computer: Callable[[list[JudgeScores], list[VariantResult]], dict]
    post_hook: (
        Callable[[GroupResult, Judge, list[Scenario]], Awaitable[GroupResult]] | None
    ) = None


async def run_group(
    runner: AblationRunner,
    judge: Judge,
    scenarios: list[Scenario],
    config: GroupConfig,
    output_path: Path,
) -> GroupResult:
    """通用实验编排：filter → run_batch → score → dump → metrics → post_hook."""
    filtered = [s for s in scenarios if config.scenario_filter(s)]
    batch: BatchResult = await runner.run_batch(
        filtered, config.variants, checkpoint_path=output_path
    )
    scores = await score_scenarios_concurrent(judge, filtered, batch.results)
    await dump_variant_results_jsonl(
        output_path, batch.results, include_modifications=True
    )
    metrics = config.metrics_computer(scores, batch.results)
    group_result = GroupResult(
        group=config.group_name,
        variant_results=batch.results,
        judge_scores=scores,
        metrics=metrics,
        batch_stats={
            "expected": batch.expected,
            "actual": batch.actual,
            "failures": batch.failures,
        },
    )
    if config.post_hook:
        group_result = await config.post_hook(group_result, judge, filtered)
    return group_result


async def score_scenarios_concurrent(
    judge: Judge,
    scenarios: list[Scenario],
    results: list[VariantResult],
) -> list[JudgeScores]:
    """并发评分所有场景的所有变体.

    CancelledError 需显式传播——Python 3.9+ 中它是 BaseException 子类，
    不会被 isinstance(batch, Exception) 捕获。
    """

    async def score_one(scenario: Scenario) -> list[JudgeScores]:
        vrs = [r for r in results if r.scenario_id == scenario.id]
        return await judge.score_batch(scenario, vrs)

    tasks = [score_one(s) for s in scenarios]
    batches = await asyncio.gather(*tasks, return_exceptions=True)
    scores: list[JudgeScores] = []
    for scenario, batch in zip(scenarios, batches, strict=True):
        if isinstance(batch, BaseException):
            if isinstance(batch, asyncio.CancelledError):
                raise batch
            logger.error("Judge scoring failed for %s: %s", scenario.id, batch)
        elif isinstance(batch, list):
            scores.extend(batch)
    return scores
