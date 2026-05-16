"""个性化组实验——反馈学习机制的个性化效果."""

import asyncio
import dataclasses
import logging
import random
import sys
from pathlib import Path

from ._io import (
    VARIANT_TIMEOUT_SECONDS,
    append_checkpoint,
    dump_variant_results_jsonl,
    load_checkpoint,
    write_json_atomic,
)
from .ablation_runner import AblationRunner
from .feedback_simulator import (
    export_state,
    extract_task_type,
    read_weights,
    restore_state,
    simulate_feedback,
    update_feedback_weight,
)
from .judge import Judge
from .preference_metrics import compute_preference_metrics
from .types import GroupResult, JudgeScores, Scenario, Variant, VariantResult

logger = logging.getLogger(__name__)

_MIN_STAGES = 4

STAGES: list[tuple[str, int, int]] = [
    ("high-freq", 0, 8),
    ("silent", 8, 16),
    ("visual-detail", 16, 24),
    ("mixed", 24, 32),
]


def _build_stages(
    total: int,
) -> tuple[list[tuple[str, int, int]], int]:
    """按 total 构建 4 阶段切片，返回 (stages, scenarios)。"""
    available = min(total, 32)
    if available < _MIN_STAGES:
        msg = f"personalization requires ≥{_MIN_STAGES} scenarios, got {total}"
        raise ValueError(msg)
    s = available // _MIN_STAGES
    return [
        ("high-freq", 0, s),
        ("silent", s, s * 2),
        ("visual-detail", s * 2, s * 3),
        ("mixed", s * 3, available),
    ], available


def pers_stratum(s: Scenario) -> str:
    """个性化组分层键——按合成维度任务类型分组，确保确定性。

    与 safety_stratum / arch_stratum 一致，使用合成维度而非 LLM 输出。
    """
    dims = s.synthesis_dims
    if dims:
        return dims.get("task_type", "unknown")
    return "unknown"


async def run_personalization_group(
    runner: AblationRunner,
    scenarios: list[Scenario],
    output_path: Path,
    seed: int = 42,
    *,
    judge: Judge,
) -> GroupResult:
    """个性化组实验。动态轮数，4 阶段偏好切换。

    场景不足 32 时按比例缩小每阶段轮数（总轮数 = 场景数），
    至少需要 4 个场景（每阶段 1 轮）。
    """
    rng = random.Random(seed)
    stages, available = _build_stages(len(scenarios))
    personalization_scenarios = scenarios[:available]

    total = available
    is_tty = sys.stderr.isatty()

    all_results: list[VariantResult] = []
    weight_history: list[dict] = []
    existing_ids: set[tuple[str, str]] = set()

    # 续跑：从 checkpoint 恢复反馈状态 + weight_history + 跳过已完成变体
    ckpt_path = output_path.with_suffix(".checkpoint.jsonl")
    if ckpt_path.exists():
        ckpt_ids, ckpt_results, last_extra = await load_checkpoint(ckpt_path)
        if last_extra:
            restore_state(last_extra)
            if "weight_history" in last_extra:
                weight_history = last_extra["weight_history"]
        existing_ids = ckpt_ids
        # 按 (scenario_id, variant) 去重后恢复已完成结果
        seen: set[tuple[str, str]] = set()
        for r in ckpt_results:
            pair = (r.scenario_id, r.variant.value)
            if pair not in seen:
                seen.add(pair)
                all_results.append(r)

    for stage_name, start, end in stages:
        for i in range(start, end):
            if i >= len(personalization_scenarios):
                logger.warning(
                    "轮次 %d 超出场景数 %d，跳过",
                    i + 1,
                    len(personalization_scenarios),
                )
                continue
            scenario = personalization_scenarios[i]

            # 续跑：该轮两变体均已完成时整轮跳过——weight_history 已从 checkpoint
            # 恢复，不再重复追加（否则下游指标因重复条目失真）。
            # 但 checkpoint 在变体循环内写入，weight_history.append 在循环后——
            # 若中断发生在 append 后、下次 checkpoint 前，last_extra 中缺该轮。
            # 此时需补录：round_done 但 weight_history 无对应条目 → 取快照补上。
            round_done = all(
                (scenario.id, v.value) in existing_ids
                for v in [Variant.FULL, Variant.NO_FEEDBACK]
            )
            if round_done:
                if not any(wh.get("round") == i + 1 for wh in weight_history):
                    snapshot = await read_weights(runner.base_user_id)
                    weight_history.append(
                        {"round": i + 1, "stage": stage_name, "weights": snapshot}
                    )
                continue

            for variant in [Variant.FULL, Variant.NO_FEEDBACK]:
                if (scenario.id, variant.value) in existing_ids:
                    continue
                logger.info(
                    "PERS round=%d/%d stage=%s variant=%s scenario=%s",
                    i + 1,
                    total,
                    stage_name,
                    variant.value,
                    scenario.id,
                )
                if is_tty:
                    print(
                        f"\r  个性化组进度: [{stage_name}] 轮次 {i + 1}/{total} "
                        f"({variant.value}) ...",
                        end="",
                        file=sys.stderr,
                    )
                # FULL 用 base_user_id —— update_feedback_weight 写同一目录，反馈回路正确
                # NO_FEEDBACK 用独立 uid —— MemoryBank 隔离，不受 FULL 写入事件干扰
                uid = (
                    runner.base_user_id
                    if variant == Variant.FULL
                    else f"{runner.base_user_id}-{variant.value}"
                )
                try:
                    async with asyncio.timeout(VARIANT_TIMEOUT_SECONDS):
                        vr = await runner.run_variant(scenario, variant, user_id=uid)
                except TimeoutError:
                    logger.warning(
                        "Variant %s timed out after %ds (round %d, scenario %s)",
                        variant.value,
                        VARIANT_TIMEOUT_SECONDS,
                        i + 1,
                        scenario.id,
                    )
                    vr = VariantResult(
                        scenario_id=scenario.id,
                        variant=variant,
                        decision={"error": "Variant execution timed out"},
                        result_text="",
                        event_id=None,
                        stages={},
                        latency_ms=0,
                        round_index=i + 1,
                    )
                except Exception:
                    logger.exception(
                        "Variant %s failed for round %d scenario %s",
                        variant.value,
                        i + 1,
                        scenario.id,
                    )
                    vr = VariantResult(
                        scenario_id=scenario.id,
                        variant=variant,
                        decision={"error": "Variant execution failed"},
                        result_text="",
                        event_id=None,
                        stages={},
                        latency_ms=0,
                        round_index=i + 1,
                    )
                else:
                    vr = dataclasses.replace(vr, round_index=i + 1)
                all_results.append(vr)
                logger.info(
                    "PERS round=%d/%d variant=%s done latency=%.1fms error=%s",
                    i + 1,
                    total,
                    variant.value,
                    vr.latency_ms,
                    vr.decision.get("error", ""),
                )
                if not is_tty:
                    print(
                        f"[个性化组] [{stage_name}] 轮次 {i + 1}/{total} "
                        f"{variant.value} 完成 ({vr.latency_ms:.0f}ms)",
                        file=sys.stderr,
                    )
                await append_checkpoint(
                    output_path.with_suffix(".checkpoint.jsonl"),
                    vr,
                    include_modifications=True,
                    extra={
                        **export_state(),
                        "weight_history": weight_history,
                    },
                )

                if variant == Variant.FULL:
                    task_type = extract_task_type(vr.stages)
                    if task_type:
                        try:
                            action = simulate_feedback(
                                vr.decision,
                                stage_name,
                                rng,
                                _scenario_id=scenario.id,
                                driving_context=scenario.driving_context,
                            )
                            if action is not None:
                                await update_feedback_weight(
                                    runner.base_user_id,
                                    vr.event_id,
                                    action,
                                    task_type=task_type,
                                )
                        except Exception:
                            logger.exception(
                                "Feedback update failed for round %d, skipping",
                                i + 1,
                            )

            snapshot = await read_weights(runner.base_user_id)
            weight_history.append(
                {"round": i + 1, "stage": stage_name, "weights": snapshot}
            )

    scenario_map = {s.id: s for s in personalization_scenarios}
    scores: list[JudgeScores] = []
    grouped: dict[str, list[VariantResult]] = {}
    for vr in all_results:
        grouped.setdefault(vr.scenario_id, []).append(vr)
    for scenario_id, scenario_vrs in grouped.items():
        scenario = scenario_map.get(scenario_id)
        if scenario is None:
            logger.warning(
                "场景 %s 不在 personalization_scenarios 中，跳过评分", scenario_id
            )
            continue
        batch_scores = await judge.score_batch(scenario, scenario_vrs)
        scores.extend(batch_scores)

    metrics = compute_preference_metrics(
        all_results, weight_history, stages, scores=scores
    )

    # 写 VariantResult JSONL 到 output_path（供 --judge-only 重载）
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await dump_variant_results_jsonl(output_path, all_results)

    # 清理中间 checkpoint（实验完成后只需最终 results JSONL）
    checkpoint_path = output_path.with_suffix(".checkpoint.jsonl")
    await asyncio.to_thread(checkpoint_path.unlink, missing_ok=True)

    # 写 weight_history + metrics 到侧车文件
    summary_path = output_path.with_suffix(".summary.json")

    await write_json_atomic(
        summary_path,
        {
            "weight_history": weight_history,
            "metrics": metrics,
            "stages": stages,
        },
    )

    return GroupResult(
        group="personalization",
        variant_results=all_results,
        judge_scores=scores,
        metrics=metrics,
    )
