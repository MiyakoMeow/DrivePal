"""消融实验命令行接口."""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import aiofiles

from app.memory.singleton import close_memory_module

from ._io import (
    variant_result_from_dict,
    write_config,
    write_scores_json,
    write_step_summary,
)
from .ablation_runner import AblationRunner
from .architecture_group import (
    _arch_stratum,
    compute_quality_metrics,
    run_architecture_group,
)
from .judge import Judge
from .personalization_group import (
    STAGES,
    _compute_preference_metrics,
    _pers_stratum,
    run_personalization_group,
)
from .report import render_report
from .safety_group import (
    _safety_stratum,
    compute_safety_metrics,
    run_safety_group,
)
from .scenario_synthesizer import (
    load_scenarios,
    sample_scenarios,
    synthesize_scenarios,
)
from .types import (
    GroupResult,
    JudgeScores,
    Scenario,
    VariantResult,
)

logger = logging.getLogger(__name__)

_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9][-a-zA-Z0-9_.]*$")
"""run_id 只允许字母/数字/连字符/下划线/点号，首字符必须为字母或数字。"""


def _find_latest_run(runs_dir: Path) -> Path | None:
    """按目录名降序取最新运行目录。

    假设 run_id 为 {timestamp}_{seed} 格式（ISO 基本时间戳），
    该格式下字典序等同时间序。
    """
    if not runs_dir.is_dir():
        return None
    return max(
        (d for d in runs_dir.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        default=None,
    )


def _print_step_summary(result: GroupResult, elapsed: float) -> None:
    """控制台输出步骤摘要。"""
    group = result.group
    n = len(result.variant_results)
    m = len(result.judge_scores)
    metrics_parts: list[str] = []
    for k, v in result.metrics.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                if isinstance(v2, (int, float)):
                    metrics_parts.append(f"{k2}: {v2}")
        elif isinstance(v, (int, float)):
            metrics_parts.append(f"{k}: {v}")
    suffix = f" | {'; '.join(metrics_parts[:8])}" if metrics_parts else ""
    print(f"[{group}] {n} results, {m} scores, {elapsed:.1f}s{suffix}")


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
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="运行标识符（缺省自动生成 {timestamp}_{seed}）",
    )
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
    batches = await asyncio.gather(*tasks, return_exceptions=True)
    scores: list[JudgeScores] = []
    for batch in batches:
        if isinstance(batch, Exception):
            logger.error("Judge scoring failed: %s", batch)
        elif isinstance(batch, list):
            scores.extend(batch)
    return scores


async def _judge_only(run_dir: Path, data_dir: Path, *, groups: list[str]) -> None:
    """仅重新评分：加载已有结果 JSONL → Judge 评分 → 覆盖输出。"""
    all_scenarios = load_scenarios(data_dir / "scenarios.jsonl")
    if not all_scenarios:
        print("无场景数据，请先运行 --synthesize-only")
        return

    scenario_by_id: dict[str, Scenario] = {s.id: s for s in all_scenarios}
    judge = Judge()
    all_group_results: dict[str, GroupResult] = {}

    for group_name in groups:
        result_path = run_dir / group_name / "results.jsonl"
        if not result_path.exists():
            continue

        variant_results = await _load_variant_results(result_path)
        scenarios_for_results: dict[str, list[VariantResult]] = {}
        for vr in variant_results:
            scenarios_for_results.setdefault(vr.scenario_id, []).append(vr)

        scores = await _score_group(judge, scenarios_for_results, scenario_by_id)
        await write_scores_json(run_dir / group_name / "scores.json", scores)

        if group_name == "safety":
            metrics = compute_safety_metrics(scores, variant_results)
        elif group_name == "architecture":
            metrics = compute_quality_metrics(scores, variant_results)
        elif group_name == "personalization":
            summary_path = run_dir / group_name / "results.summary.json"
            try:
                async with aiofiles.open(summary_path, encoding="utf-8") as f:
                    raw = json.loads(await f.read())
            except FileNotFoundError:
                logger.warning(
                    "个性化组 results.summary.json 不存在（%s），指标将为空。"
                    "请先运行完整个性化组实验。",
                    summary_path,
                )
                metrics = {}
            except json.JSONDecodeError:
                logger.warning(
                    "个性化组 results.summary.json 解析失败（%s），指标将为空。",
                    summary_path,
                )
                metrics = {}
            else:
                weight_history = raw.get("weight_history", [])
                metrics = _compute_preference_metrics(
                    variant_results, weight_history, STAGES
                )
        else:
            msg = f"未知组: {group_name}"
            raise ValueError(msg)

        all_group_results[group_name] = GroupResult(
            group=group_name,
            variant_results=variant_results,
            judge_scores=scores,
            metrics=metrics,
        )
        print(f"{group_name} 组重新评分完成: {len(scores)} 评分")

    await render_report(all_group_results, run_dir)


async def _load_variant_results(path: Path) -> list[VariantResult]:
    """从 JSONL 重建 VariantResult 列表。"""
    results: list[VariantResult] = []
    async with aiofiles.open(path, encoding="utf-8") as f:
        async for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                d = json.loads(stripped)
                results.append(variant_result_from_dict(d))
            except json.JSONDecodeError, KeyError, ValueError:
                logger.warning("跳过无效行: %s", stripped[:80])
    return results


def _prepare_group_scenarios(
    all_scenarios: list[Scenario],
    groups_to_run: list[str],
    *,
    seed: int,
) -> dict[str, list[Scenario]]:
    """预采样：组间互斥 + 分层，避免同一场景进入多组实验。"""
    used_ids: set[str] = set()
    group_scenarios: dict[str, list[Scenario]] = {}

    if "safety" in groups_to_run:
        group_scenarios["safety"] = sample_scenarios(
            all_scenarios,
            50,
            safety_only=True,
            stratify_key=_safety_stratum,
            min_per_stratum=2,
            seed=seed,
        )
        used_ids |= {s.id for s in group_scenarios["safety"]}

    if "architecture" in groups_to_run:
        group_scenarios["architecture"] = sample_scenarios(
            all_scenarios,
            50,
            safety_only=False,
            exclude_ids=used_ids,
            stratify_key=_arch_stratum,
            min_per_stratum=1,
            seed=seed + 1,
        )
        used_ids |= {s.id for s in group_scenarios["architecture"]}

    if "personalization" in groups_to_run:
        group_scenarios["personalization"] = sample_scenarios(
            all_scenarios,
            20,
            safety_only=False,
            exclude_ids=used_ids,
            stratify_key=_pers_stratum,
            min_per_stratum=2,
            seed=seed + 2,
        )

    return group_scenarios


async def _run_safety_experiment(
    scenarios: list[Scenario], run_dir: Path
) -> GroupResult:
    """运行安全性组实验。"""
    runner = AblationRunner(base_user_id="experiment-safety")
    judge = Judge()
    return await run_safety_group(
        runner, judge, scenarios, run_dir / "safety" / "results.jsonl"
    )


async def _run_architecture_experiment(
    scenarios: list[Scenario], run_dir: Path
) -> GroupResult:
    """运行架构组实验。"""
    runner = AblationRunner(base_user_id="experiment-arch")
    judge = Judge()
    return await run_architecture_group(
        runner, judge, scenarios, run_dir / "architecture" / "results.jsonl"
    )


async def _run_personalization_experiment(
    scenarios: list[Scenario], seed: int, run_dir: Path
) -> GroupResult:
    """运行个性化组实验。"""
    runner = AblationRunner(base_user_id="experiment-personalization")
    judge = Judge()
    return await run_personalization_group(
        runner,
        scenarios,
        run_dir / "personalization" / "results.jsonl",
        seed=seed,
        judge=judge,
    )


async def _run_and_summarize(
    group: str,
    scenarios: list[Scenario],
    seed: int,
    run_dir: Path,
) -> tuple[str, GroupResult]:
    """运行一组实验并写 step-summary + 控制台输出。"""
    t0 = time.perf_counter()
    print(f"\n=== 运行 {group} 组 ===\n")
    if group == "safety":
        result = await _run_safety_experiment(scenarios, run_dir)
    elif group == "architecture":
        result = await _run_architecture_experiment(scenarios, run_dir)
    elif group == "personalization":
        result = await _run_personalization_experiment(scenarios, seed, run_dir)
    else:
        msg = f"未知组: {group}"
        raise ValueError(msg)
    elapsed = time.perf_counter() - t0

    # 持久化 Judge 详细评分
    if result.judge_scores:
        try:
            await write_scores_json(
                run_dir / group / "scores.json", result.judge_scores
            )
        except OSError:
            logger.exception("Failed to write scores for group '%s'", group)

    step_path = run_dir / group / "step-summary.json"
    await write_step_summary(step_path, result, duration_seconds=elapsed)
    _print_step_summary(result, elapsed)
    return group, result


async def main(argv: list[str] | None = None) -> None:
    """消融实验主入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)

    if args.run_id is not None and not _RUN_ID_RE.fullmatch(args.run_id):
        print(
            f"无效 run_id（仅允许字母/数字/连字符/下划线/点号）: {args.run_id}",
            file=sys.stderr,
        )
        sys.exit(1)

    old_seed = os.environ.get("ABLATION_SEED")
    os.environ["ABLATION_SEED"] = str(args.seed)
    try:
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
            run_dir: Path
            if args.run_id:
                run_dir = data_dir / "runs" / args.run_id
                if not run_dir.is_dir():
                    print(f"运行目录不存在: {run_dir}")
                    return
            else:
                latest = _find_latest_run(data_dir / "runs")
                if latest is None:
                    print("无已有运行，请先运行实验")
                    return
                run_dir = latest
            await _judge_only(run_dir, data_dir, groups=groups_to_run)
            return

        all_scenarios = load_scenarios(data_dir / "scenarios.jsonl")
        if not all_scenarios:
            print("无场景数据，请先运行 --synthesize-only")
            return

        run_id = args.run_id or (
            datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S_%f") + f"_{args.seed}"
        )
        run_dir = data_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        await write_config(run_dir / "config.json", args)

        group_scenarios = _prepare_group_scenarios(
            all_scenarios, groups_to_run, seed=args.seed
        )

        all_group_results: dict[str, GroupResult] = {}
        failures: list[str] = []

        # personalization 组必须串行：该组依赖 MemoryBank 权重状态的顺序累积，
        # 并发会导致多任务竞争同一用户状态，产生不可复现的权重交叉污染。
        concurrent_groups = [g for g in groups_to_run if g != "personalization"]
        serial_group = "personalization" if "personalization" in groups_to_run else None

        if concurrent_groups:
            tasks = [
                asyncio.create_task(
                    _run_and_summarize(g, group_scenarios[g], args.seed, run_dir)
                )
                for g in concurrent_groups
            ]
            for r in await asyncio.gather(*tasks, return_exceptions=True):
                if isinstance(r, Exception):
                    logger.error("Group experiment failed: %s", r)
                    failures.append(str(r))
                elif isinstance(r, tuple):
                    all_group_results[r[0]] = r[1]

            if failures:
                logger.error(
                    "Incomplete results: %d concurrent group(s) failed — %s",
                    len(failures),
                    "; ".join(failures),
                )

        if serial_group:
            try:
                grp_name, grp_result = await _run_and_summarize(
                    serial_group, group_scenarios[serial_group], args.seed, run_dir
                )
                all_group_results[grp_name] = grp_result
            except Exception:
                logger.exception("Serial group '%s' failed", serial_group)
                failures.append(f"serial:{serial_group}")

        await render_report(all_group_results, run_dir)

        print(f"\n=== 全部完成 [{run_id}] ===")
        for g, gr in all_group_results.items():
            print(
                f"  {g}: {len(gr.variant_results)} results, {len(gr.judge_scores)} scores"
            )

        if failures:
            sys.exit(1)
    finally:
        if old_seed is None:
            os.environ.pop("ABLATION_SEED", None)
        else:
            os.environ["ABLATION_SEED"] = old_seed
        await close_memory_module()
