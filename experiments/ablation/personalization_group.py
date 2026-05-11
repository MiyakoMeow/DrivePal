"""个性化组实验——反馈学习机制的个性化效果."""

import asyncio
import dataclasses
import json
import logging
import random
from collections.abc import MutableMapping
from pathlib import Path
from typing import Literal

import aiofiles

from app.config import user_data_dir
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.storage.toml_store import TOMLStore

from ._io import dump_variant_results_jsonl
from .ablation_runner import AblationRunner, _append_checkpoint
from .judge import Judge
from .types import GroupResult, JudgeScores, Scenario, Variant, VariantResult

logger = logging.getLogger(__name__)

_SIMULATED_ACCEPT_PROB = 0.5
_MIN_HISTORY_LEN = 2
_INITIAL_WEIGHT_TOLERANCE = 0.01
_CONVERGENCE_TOLERANCE = 0.05
_CONSECUTIVE_FOR_CONVERGENCE = 3

STAGES: list[tuple[str, int, int]] = [
    ("high-freq", 0, 8),
    ("silent", 8, 16),
    ("visual-detail", 16, 24),
    ("mixed", 24, 32),
]


def pers_stratum(s: Scenario) -> str:
    """个性化组分层键——按任务类型分组，保证各类型有场景覆盖。"""
    return getattr(s, "expected_task_type", None) or "unknown"


async def run_personalization_group(
    runner: AblationRunner,
    scenarios: list[Scenario],
    output_path: Path,
    seed: int = 42,
    *,
    judge: Judge,
) -> GroupResult:
    """个性化组实验。32 轮，4 阶段偏好切换。

    场景不足 32 时通过取模循环复用（i % len），保证每轮有场景可用。
    """
    rng = random.Random(seed)
    personalization_scenarios = scenarios[:32]

    if not personalization_scenarios:
        msg = "no personalization scenarios available"
        raise ValueError(msg)

    stages = STAGES[:]  # 浅拷贝防止调用方修改

    all_results: list[VariantResult] = []
    weight_history: list[dict] = []

    for stage_name, start, end in stages:
        for i in range(start, end):
            scenario = personalization_scenarios[i % len(personalization_scenarios)]

            for variant in [Variant.FULL, Variant.NO_FEEDBACK]:
                # FULL 用 base_user_id —— update_feedback_weight 写同一目录，反馈回路正确
                # NO_FEEDBACK 用独立 uid —— MemoryBank 隔离，不受 FULL 写入事件干扰
                uid = (
                    runner.base_user_id
                    if variant == Variant.FULL
                    else f"{runner.base_user_id}-{variant.value}"
                )
                try:
                    vr = await runner.run_variant(scenario, variant, user_id=uid)
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
                await _append_checkpoint(
                    output_path.with_suffix(".checkpoint.jsonl"),
                    vr,
                    include_modifications=True,
                )

                if variant == Variant.FULL:
                    task_type = _extract_task_type(vr.stages)
                    if task_type:
                        try:
                            action = simulate_feedback(vr.decision, stage_name, rng)
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

            snapshot = await _read_weights(runner.base_user_id)
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

    metrics = compute_preference_metrics(all_results, weight_history, stages)

    # 写 VariantResult JSONL 到 output_path（供 --judge-only 重载）
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await dump_variant_results_jsonl(output_path, all_results)

    # 清理中间 checkpoint（实验完成后只需最终 results JSONL）
    checkpoint_path = output_path.with_suffix(".checkpoint.jsonl")
    await asyncio.to_thread(checkpoint_path.unlink, missing_ok=True)

    # 写 weight_history + metrics 到侧车文件
    summary_path = output_path.with_suffix(".summary.json")
    async with aiofiles.open(summary_path, "w") as f:
        await f.write(
            json.dumps(
                {"weight_history": weight_history, "metrics": metrics},
                ensure_ascii=False,
            )
            + "\n"
        )

    return GroupResult(
        group="personalization",
        variant_results=all_results,
        judge_scores=scores,
        metrics=metrics,
    )


def simulate_feedback(
    decision: dict, stage: str, rng: random.Random
) -> Literal["accept", "ignore"]:
    """模拟用户反馈——根据阶段偏好决定 accept 或 ignore。

    实验简写版：直接操作 strategies.toml 的 reminder_weights，
    不走正式 submitFeedback mutation（不写 feedback.jsonl、不更新 memory_strength）。

    TODO: 可选集成正式 submitFeedback API。

    #126 后策略 Agent 输出 is_emergency（非 is_urgent），allowed_channels 列表（非 channel 字符串）。
    """
    if stage == "high-freq":
        return "accept" if decision.get("should_remind") else "ignore"
    if stage == "silent":
        return (
            "accept"
            if decision.get("should_remind") and decision.get("is_emergency")
            else "ignore"
        )
    if stage == "visual-detail":
        return (
            "accept" if "visual" in decision.get("allowed_channels", []) else "ignore"
        )
    if stage == "mixed":
        return "accept" if rng.random() < _SIMULATED_ACCEPT_PROB else "ignore"
    return "ignore"


_KNOWN_TASK_TYPES: frozenset[str] = frozenset(
    {"meeting", "travel", "shopping", "contact", "other"}
)


def _extract_task_type(stages: dict) -> str | None:
    """从 stages.task 提取任务类型。

    LLM 输出的 key 名不一致——可能为 task_type / task_attribution。
    返回值仅接受已知类型集合，过滤无效值。
    """
    task_stage = stages.get("task", {})
    if isinstance(task_stage, dict):
        for key in ("task_type", "task_attribution"):
            val = task_stage.get(key)
            if isinstance(val, str) and val.strip():
                stripped = val.strip()
                if stripped in _KNOWN_TASK_TYPES:
                    return stripped
                logger.debug("task_type=%r 不在已知类型集合中，跳过反馈", stripped)
    return None


async def update_feedback_weight(
    user_id: str,
    event_id: str | None,
    action: Literal["accept", "ignore"],
    *,
    task_type: str | None = None,
) -> None:
    """模拟反馈写入 strategies.toml，更新 reminder_weights。

    优先使用显式传入的 task_type；否则回退 MemoryBank 查询。
    """
    event_type = task_type
    if not event_type:
        logger.debug(
            "task_type 未从 stages 提取（event_id=%s），回退 MemoryBank 查询", event_id
        )
        if event_id:
            mm = get_memory_module()
            mode = MemoryMode.MEMORY_BANK
            event_type = await mm.get_event_type(event_id, mode=mode, user_id=user_id)
    if not event_type:
        return
    ud = user_data_dir(user_id)
    strategy_store = TOMLStore(
        user_dir=ud, filename="strategies.toml", default_factory=dict
    )
    current = await strategy_store.read()
    weights: dict[str, float] = {}
    if isinstance(current, MutableMapping):
        weights = dict(current.get("reminder_weights", {}))
    delta = 0.1 if action == "accept" else -0.1
    weights[event_type] = max(0.1, min(1.0, weights.get(event_type, 0.5) + delta))
    await strategy_store.update("reminder_weights", weights)


async def _read_weights(user_id: str) -> dict:
    ud = user_data_dir(user_id)
    store = TOMLStore(user_dir=ud, filename="strategies.toml", default_factory=dict)
    current = await store.read()
    return (
        current.get("reminder_weights", {})
        if isinstance(current, MutableMapping)
        else {}
    )


def compute_preference_metrics(
    results: list[VariantResult],
    weight_history: list[dict],
    stages: list[tuple],
) -> dict:
    """计算个性化组四个量化指标。"""
    rounds = len(weight_history)
    preference_matching_rate = _compute_matching_rate(results, weight_history)
    convergence_speed = _compute_convergence_speed(weight_history)
    stability = _compute_stability(weight_history, stages)
    decision_divergence = _compute_decision_divergence(results, weight_history)

    return {
        "rounds": rounds,
        "weight_history": weight_history,
        "preference_matching_rate": preference_matching_rate,
        "convergence_speed": convergence_speed,
        "stability": stability,
        "decision_divergence": decision_divergence,
    }


def _compute_matching_rate(
    results: list[VariantResult],
    weight_history: list[dict],
) -> dict[str, float]:
    """偏好匹配率：每阶段 FULL 变体决策与阶段偏好的吻合度。"""
    full_results = [r for r in results if r.variant == Variant.FULL]

    # 以 round_index 建映射，消除对列表序的依赖
    full_by_round = {r.round_index: r for r in full_results if r.round_index > 0}
    stage_matches: dict[str, list[bool]] = {}

    for wh in weight_history:
        ri = wh.get("round", 0)
        stage = wh["stage"]
        if ri not in full_by_round:
            continue
        decision = full_by_round[ri].decision
        matched = _decision_matches_stage(decision, stage)
        if matched is None:
            continue  # mixed 阶段不参与匹配率计算
        stage_matches.setdefault(stage, []).append(matched)

    return {
        stage: sum(matches) / len(matches) if matches else 0.0
        for stage, matches in stage_matches.items()
    }


def _decision_matches_stage(decision: dict, stage: str) -> bool | None:
    """单条决策是否匹配阶段偏好。mixed 阶段返回 None 表示不适用。"""
    if stage == "mixed":
        return None
    if stage == "high-freq":
        return bool(decision.get("should_remind"))
    if stage == "silent":
        return bool(decision.get("should_remind")) and bool(
            decision.get("is_emergency")
        )
    if stage == "visual-detail":
        return "visual" in decision.get("allowed_channels", [])
    return True


def _compute_convergence_speed(weight_history: list[dict]) -> float:
    """收敛速度：最高权重类型最长稳定段的起始轮次（归一化）。

    追踪权重在终值 ±0.05 范围内最长的连续稳定段（≥3 轮），
    返回该段起始轮次 / 总轮数。返回值 ∈ [0, 1]（越小越快），-1.0 表示未收敛。
    """
    if not weight_history or len(weight_history) < _MIN_HISTORY_LEN:
        return -1.0

    final_weights = weight_history[-1].get("weights", {})
    if not final_weights:
        return -1.0

    # 取最终最高权重类型，并列时取字典序最小以确定性消歧
    max_w = max(final_weights.values())
    target_types = sorted(t for t, w in final_weights.items() if w == max_w)
    target_type = target_types[0]
    if len(target_types) > 1:
        logger.debug(
            "最终最高权重类型并列（%s），取 %s 计算收敛速度",
            target_types,
            target_type,
        )
    target_final = final_weights[target_type]

    consecutive = 0
    best_start = -1
    best_len = 0
    current_start = 0
    for i, wh in enumerate(weight_history):
        current_weight = wh.get("weights", {}).get(target_type, 0.5)
        if abs(current_weight - target_final) <= _CONVERGENCE_TOLERANCE:
            if consecutive == 0:
                current_start = i
            consecutive += 1
            if consecutive >= _CONSECUTIVE_FOR_CONVERGENCE and consecutive > best_len:
                best_start = current_start
                best_len = consecutive
        else:
            consecutive = 0

    if best_start < 0:
        return -1.0  # 未收敛
    return best_start / len(weight_history)


def _compute_stability(weight_history: list[dict], stages: list[tuple]) -> float:
    """偏好切换后目标类型权重的平均标准差。

    对每个切换点（high-freq→silent, silent→visual-detail, visual-detail→mixed）：
    1. 取上一阶段最后一轮最高权重类型（目标类型）
    2. 若所有权重均为 0.5（初始态），跳过该切换点
    3. 并列最高时取类型名字典序最小者
    4. 跟踪该类型在新阶段连续 5 轮的权重，计算标准差
    5. 返回所有切换点标准差的均值
    """
    if not weight_history:
        return 0.0

    switch_points = [end for _, _, end in stages[:-1]]
    stds: list[float] = []

    for sp in switch_points:
        if sp < 1 or sp >= len(weight_history):
            # 需要上一轮数据才能确定目标类型，不存在则跳过
            continue

        prev_weights = weight_history[sp - 1].get("weights", {})
        if not prev_weights or all(
            abs(w - 0.5) < _INITIAL_WEIGHT_TOLERANCE for w in prev_weights.values()
        ):
            continue

        max_w = max(prev_weights.values())
        target_types = [t for t, w in prev_weights.items() if w == max_w]
        target_type = sorted(target_types)[0]  # 并列取字典序最小，确定性消歧

        window = weight_history[sp : min(sp + 5, len(weight_history))]
        weights_in_window = [
            wh.get("weights", {}).get(target_type, 0.5) for wh in window
        ]
        if len(weights_in_window) < _MIN_HISTORY_LEN:
            continue

        mean = sum(weights_in_window) / len(weights_in_window)
        variance = sum((w - mean) ** 2 for w in weights_in_window) / len(
            weights_in_window
        )
        stds.append(variance**0.5)

    return sum(stds) / len(stds) if stds else 0.0


def _compute_decision_divergence(
    results: list[VariantResult],
    weight_history: list[dict],
) -> float:
    """FULL vs NO_FEEDBACK 在 mixed 阶段的决策分歧度。

    对每个 mixed 轮次，比较两个变体的 decision dict 差异字段比例，
    取所有轮次的平均。越高说明 FULL 学偏了。
    """
    mixed_rounds = [
        i for i, wh in enumerate(weight_history) if wh.get("stage") == "mixed"
    ]
    if not mixed_rounds:
        return 0.0

    mixed_indices = {i + 1 for i in mixed_rounds}
    full_mixed = [
        r
        for r in results
        if r.variant == Variant.FULL and r.round_index in mixed_indices
    ]
    no_fb_mixed = [
        r
        for r in results
        if r.variant == Variant.NO_FEEDBACK and r.round_index in mixed_indices
    ]

    full_by_round = {r.round_index: r for r in full_mixed}
    no_fb_by_round = {r.round_index: r for r in no_fb_mixed}
    common_rounds = set(full_by_round) & set(no_fb_by_round)
    if not common_rounds:
        return 0.0

    divergences: list[float] = []
    for ri in common_rounds:
        d1 = full_by_round[ri].decision
        d2 = no_fb_by_round[ri].decision
        all_keys = set(d1) | set(d2)
        diff_count = sum(1 for k in all_keys if d1.get(k) != d2.get(k))
        divergences.append(diff_count / max(1, len(all_keys)))

    return sum(divergences) / len(divergences)
