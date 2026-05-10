"""消融实验命令行接口."""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

import aiofiles

from .ablation_runner import AblationRunner
from .architecture_group import (
    compute_quality_metrics,
    run_architecture_group,
)
from .judge import Judge
from .personalization_group import (
    STAGES,
    _compute_preference_metrics,
    run_personalization_group,
)
from .report import render_report
from .safety_group import compute_safety_metrics, run_safety_group
from .scenario_synthesizer import (
    load_scenarios,
    sample_scenarios,
    synthesize_scenarios,
)
from .types import (
    GroupResult,
    JudgeScores,
    Scenario,
    Variant,
    VariantResult,
)

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """构建消融实验命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="DrivePal-2 消融实验")
    parser.add_argument(
        "--group",
        choices=["safety", "architecture", "personalization", "all"],
        default="all",
        help="实验组",
    )
    parser.add_argument("--synthesize-only", action="store_true", help="仅合成场景")
    parser.add_argument("--judge-only", action="store_true", help="仅重新评分")
    parser.add_argument("--data-dir", default="data/experiments")
    parser.add_argument("--seed", type=int, default=42, help="ABLATION_SEED")
    return parser


async def _score_group(
    judge: Judge,
    scenarios_for_results: dict[str, list[VariantResult]],
    scenario_by_id: dict[str, Scenario],
) -> list[JudgeScores]:
    """对一组结果的各场景并发评分并汇总。"""

    async def score_one(sid: str, vrs: list[VariantResult]) -> list[JudgeScores]:
        scenario = scenario_by_id.get(sid)
        if scenario is None:
            return []
        return await judge.score_batch(scenario, vrs)

    tasks = [score_one(sid, vrs) for sid, vrs in scenarios_for_results.items()]
    batches = await asyncio.gather(*tasks)
    return [s for batch in batches for s in batch]


async def _judge_only(data_dir: Path, *, groups: list[str]) -> None:
    """仅重新评分：加载已有结果 JSONL → Judge 评分 → 覆盖输出。"""
    all_scenarios = load_scenarios(data_dir / "scenarios.jsonl")
    if not all_scenarios:
        print("无场景数据，请先运行 --synthesize-only")
        return

    scenario_by_id: dict[str, Scenario] = {s.id: s for s in all_scenarios}
    results_dir = data_dir / "results"
    judge = Judge()
    all_group_results: dict[str, GroupResult] = {}

    for group_name in groups:
        result_path = results_dir / f"{group_name}.jsonl"
        if not result_path.exists():
            continue

        variant_results = await _load_variant_results(result_path)
        scenarios_for_results: dict[str, list[VariantResult]] = {}
        for vr in variant_results:
            scenarios_for_results.setdefault(vr.scenario_id, []).append(vr)

        scores = await _score_group(judge, scenarios_for_results, scenario_by_id)

        if group_name == "safety":
            metrics = compute_safety_metrics(scores, variant_results)
        elif group_name == "architecture":
            metrics = compute_quality_metrics(scores, variant_results)
        else:  # personalization
            summary_path = result_path.with_suffix(".summary.json")
            try:
                raw = json.loads(summary_path.read_text())
            except FileNotFoundError:
                logger.warning(
                    "个性化组 .summary.json 不存在（%s），指标将为空。"
                    "请先运行完整个性化组实验。",
                    summary_path,
                )
                metrics = {}
            except json.JSONDecodeError:
                logger.warning(
                    "个性化组 .summary.json 解析失败（%s），指标将为空。", summary_path
                )
                metrics = {}
            else:
                weight_history = raw.get("weight_history", [])
                # 重新计算偏好指标（依赖 weight_history + variant_results）
                metrics = _compute_preference_metrics(
                    variant_results, weight_history, STAGES
                )

        all_group_results[group_name] = GroupResult(
            group=group_name,
            variant_results=variant_results,
            judge_scores=scores,
            metrics=metrics,
        )
        print(f"{group_name} 组重新评分完成: {len(scores)} 评分")

    render_report(all_group_results, results_dir)


async def _load_variant_results(path: Path) -> list[VariantResult]:
    """从 JSONL 重建 VariantResult 列表。"""
    results: list[VariantResult] = []
    async with aiofiles.open(path) as f:
        async for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            d = json.loads(stripped)
            try:
                variant = Variant(d["variant"])
            except KeyError, ValueError:
                logger.warning("跳过无效变体: %s", d.get("variant", "缺失"))
                continue
            results.append(
                VariantResult(
                    scenario_id=d["scenario_id"],
                    variant=variant,
                    decision=d.get("decision", {}),
                    result_text="",
                    event_id=None,
                    stages=d.get("stages", {}),
                    latency_ms=d.get("latency_ms", 0),
                    modifications=d.get("modifications", []),
                    round_index=d.get("round_index", 0),
                )
            )
    return results


async def _run_safety_experiment(
    data_dir: Path, all_scenarios: list[Scenario], seed: int
) -> GroupResult:
    """运行安全性组实验。"""
    runner = AblationRunner(base_user_id="experiment-safety")
    judge = Judge()
    safety_scenarios = sample_scenarios(all_scenarios, 50, safety_only=True, seed=seed)
    return await run_safety_group(
        runner, judge, safety_scenarios, data_dir / "results" / "safety.jsonl"
    )


async def _run_architecture_experiment(
    data_dir: Path, all_scenarios: list[Scenario], seed: int
) -> GroupResult:
    """运行架构组实验。"""
    runner = AblationRunner(base_user_id="experiment-arch")
    judge = Judge()
    arch_scenarios = sample_scenarios(
        all_scenarios, 50, safety_only=False, seed=seed + 1
    )
    return await run_architecture_group(
        runner, judge, arch_scenarios, data_dir / "results" / "architecture.jsonl"
    )


async def _run_personalization_experiment(
    data_dir: Path, all_scenarios: list[Scenario], seed: int
) -> GroupResult:
    """运行个性化组实验。"""
    runner = AblationRunner(base_user_id="experiment-personalization")
    judge = Judge()
    personalization_scenarios = sample_scenarios(
        all_scenarios, 20, safety_only=False, seed=seed + 2
    )
    return await run_personalization_group(
        runner,
        personalization_scenarios,
        data_dir / "results" / "personalization.jsonl",
        seed=seed,
        judge=judge,
    )


async def main(argv: list[str] | None = None) -> None:
    """消融实验主入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)
    os.environ["ABLATION_SEED"] = str(args.seed)

    groups_to_run = (
        ["safety", "architecture", "personalization"]
        if args.group == "all"
        else [args.group]
    )

    if args.synthesize_only:
        n = await synthesize_scenarios(data_dir / "scenarios.jsonl")
        print(f"合成完成: {n} 场景")
        return

    if args.judge_only:
        await _judge_only(data_dir, groups=groups_to_run)
        return

    all_scenarios = load_scenarios(data_dir / "scenarios.jsonl")
    if not all_scenarios:
        print("无场景数据，请先运行 --synthesize-only")
        return

    results_dir = data_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    all_group_results: dict[str, GroupResult] = {}

    async def _run_one(group: str) -> tuple[str, GroupResult]:
        if group == "safety":
            print(f"\n=== 运行 {group} 组 ===\n")
            result = await _run_safety_experiment(data_dir, all_scenarios, args.seed)
            print(f"安全性组完成: {len(result.variant_results)} 结果")
            return group, result
        if group == "architecture":
            print(f"\n=== 运行 {group} 组 ===\n")
            result = await _run_architecture_experiment(
                data_dir, all_scenarios, args.seed
            )
            print(f"架构组完成: {len(result.variant_results)} 结果")
            return group, result
        msg = f"未知组: {group}"
        raise ValueError(msg)

    concurrent_groups = [g for g in groups_to_run if g != "personalization"]
    serial_group = "personalization" if "personalization" in groups_to_run else None

    if concurrent_groups:
        tasks = [asyncio.create_task(_run_one(g)) for g in concurrent_groups]
        all_group_results.update(await asyncio.gather(*tasks))

    if serial_group:
        group = serial_group
        print(f"\n=== 运行 {group} 组 ===\n")
        result = await _run_personalization_experiment(
            data_dir, all_scenarios, args.seed
        )
        all_group_results[group] = result
        print(f"个性化组完成: {len(result.variant_results)} 结果")

    render_report(all_group_results, results_dir)
