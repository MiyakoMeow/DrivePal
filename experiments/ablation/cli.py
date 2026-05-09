"""消融实验命令行接口."""

import argparse
import os
from pathlib import Path

from experiments.ablation.ablation_runner import AblationRunner
from experiments.ablation.architecture_group import run_architecture_group
from experiments.ablation.judge import Judge
from experiments.ablation.personalization_group import run_personalization_group
from experiments.ablation.report import render_report
from experiments.ablation.safety_group import run_safety_group
from experiments.ablation.scenario_synthesizer import (
    load_scenarios,
    sample_scenarios,
    synthesize_scenarios,
)


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


async def main(argv: list[str] | None = None) -> None:
    """消融实验主入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)
    os.environ["ABLATION_SEED"] = str(args.seed)

    if args.synthesize_only:
        n = await synthesize_scenarios(data_dir / "scenarios.jsonl")
        print(f"合成完成: {n} 场景")  # noqa: T201
        return

    all_scenarios = load_scenarios(data_dir / "scenarios.jsonl")
    if not all_scenarios:
        print("无场景数据，请先运行 --synthesize-only")  # noqa: T201
        return

    groups_to_run = (
        ["safety", "architecture", "personalization"]
        if args.group == "all"
        else [args.group]
    )

    results_dir = data_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    all_group_results: dict = {}

    for group in groups_to_run:
        print(f"\n=== 运行 {group} 组 ===\n")  # noqa: T201

        if group == "safety":
            runner = AblationRunner(user_id="experiment-safety")
            judge = Judge()
            safety_scenarios = sample_scenarios(
                all_scenarios, 50, safety_only=True, seed=args.seed
            )
            result = await run_safety_group(
                runner, judge, safety_scenarios, results_dir / "safety.jsonl"
            )
            all_group_results["safety"] = result
            print(f"安全性组完成: {len(result.variant_results)} 结果")  # noqa: T201

        elif group == "architecture":
            runner = AblationRunner(user_id="experiment-arch")
            judge = Judge()
            arch_scenarios = sample_scenarios(
                all_scenarios, 50, safety_only=False, seed=args.seed + 1
            )
            result = await run_architecture_group(
                runner, judge, arch_scenarios, results_dir / "architecture.jsonl"
            )
            all_group_results["architecture"] = result
            print(f"架构组完成: {len(result.variant_results)} 结果")  # noqa: T201

        elif group == "personalization":
            runner = AblationRunner(user_id="experiment-personalization")
            personalization_scenarios = sample_scenarios(
                all_scenarios, 20, safety_only=False, seed=args.seed + 2
            )
            result = await run_personalization_group(
                runner,
                personalization_scenarios,
                results_dir / "personalization.jsonl",
                seed=args.seed,
            )
            all_group_results["personalization"] = result
            print(f"个性化组完成: {len(result.variant_results)} 结果")  # noqa: T201

    render_report(all_group_results, results_dir)
