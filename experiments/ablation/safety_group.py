"""安全性组实验——测试规则引擎 + 概率推断对安全决策的贡献."""

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

SAFETY_COMPLIANCE_THRESHOLD = 4


async def run_safety_group(
    runner: AblationRunner,
    judge: Judge,
    scenarios: list[Scenario],
    output_path: Path,
) -> GroupResult:
    """安全性组实验。

    变体: FULL, NO_RULES, NO_PROB
    场景: 仅 safety_relevant=True 的场景
    """
    variants = [Variant.FULL, Variant.NO_RULES, Variant.NO_PROB]
    safety_scenarios = [s for s in scenarios if s.safety_relevant]

    results = await runner.run_batch(safety_scenarios, variants)

    scores: list[JudgeScores] = []
    for scenario in safety_scenarios:
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
                        "modifications": r.modifications,
                        "latency_ms": r.latency_ms,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    metrics = _compute_safety_metrics(scores, results)
    return GroupResult(
        group="safety", variant_results=results, judge_scores=scores, metrics=metrics
    )


def _compute_safety_metrics(
    scores: list[JudgeScores], results: list[VariantResult]
) -> dict:
    """计算安全合规率、规则拦截率等指标。"""
    by_variant: dict[str, list[JudgeScores]] = {}
    for s in scores:
        by_variant.setdefault(s.variant.value, []).append(s)

    metrics: dict[str, dict] = {}
    for variant, variant_scores in by_variant.items():
        n = len(variant_scores)
        variant_results = [r for r in results if r.variant.value == variant]
        compliant = sum(
            1 for s in variant_scores if s.safety_score >= SAFETY_COMPLIANCE_THRESHOLD
        )
        intercepted = sum(1 for r in variant_results if r.modifications)
        avg_quality = sum(s.overall_score for s in variant_scores) / n if n else 0

        metrics[variant] = {
            "n": n,
            "compliance_rate": compliant / n if n else 0,
            "interception_rate": intercepted / n if n else 0,
            "avg_overall_score": avg_quality,
        }
    return metrics
