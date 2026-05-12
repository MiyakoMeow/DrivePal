"""公共实验编排协议."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._io import dump_variant_results_jsonl
from .types import BatchResult, GroupResult, JudgeScores, Scenario, VariantResult

if TYPE_CHECKING:
    from pathlib import Path

    from .ablation_runner import AblationRunner
    from .judge import Judge

logger = logging.getLogger(__name__)


@dataclass
class GroupConfig:
    """一组实验的声明式配置."""

    group_name: str
    variants: list
    scenario_filter: Callable[[Scenario], bool]
    metrics_computer: Callable[..., dict]
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
    scores = await _score_scenarios_concurrent(judge, filtered, batch.results)
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


async def _score_scenarios_concurrent(
    judge: Judge,
    scenarios: list[Scenario],
    results: list[VariantResult],
) -> list[JudgeScores]:
    """并发评分所有场景的所有变体."""

    async def score_one(scenario: Scenario) -> list[JudgeScores]:
        vrs = [r for r in results if r.scenario_id == scenario.id]
        return await judge.score_batch(scenario, vrs)

    tasks = [score_one(s) for s in scenarios]
    batches = await asyncio.gather(*tasks, return_exceptions=True)
    scores: list[JudgeScores] = []
    for batch in batches:
        if isinstance(batch, Exception):
            logger.error("Judge scoring failed: %s", batch)
        elif isinstance(batch, list):
            scores.extend(batch)
    return scores
