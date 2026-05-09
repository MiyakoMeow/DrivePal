"""个性化组实验——反馈学习机制的个性化效果."""

import random
from collections.abc import MutableMapping
from pathlib import Path
from typing import Literal

from app.config import user_data_dir
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.storage.toml_store import TOMLStore

from .ablation_runner import AblationRunner
from .types import GroupResult, Scenario, Variant, VariantResult


async def run_personalization_group(
    runner: AblationRunner,
    scenarios: list[Scenario],
    output_path: Path,
    seed: int = 42,
) -> GroupResult:
    """个性化组实验。20 轮，4 阶段偏好切换。"""
    rng = random.Random(seed)
    personalization_scenarios = scenarios[:20]

    stages = [
        ("high-freq", 0, 5),
        ("silent", 5, 10),
        ("visual-detail", 10, 15),
        ("mixed", 15, 20),
    ]

    all_results: list[VariantResult] = []
    weight_history: list[dict] = []

    for stage_name, start, end in stages:
        for i in range(start, end):
            scenario = personalization_scenarios[i % len(personalization_scenarios)]

            for variant in [Variant.FULL, Variant.NO_FEEDBACK]:
                vr = await runner.run_variant(scenario, variant)
                all_results.append(vr)

                if variant == Variant.FULL and vr.event_id:
                    action = simulate_feedback(vr.decision, stage_name, rng)
                    await update_feedback_weight(runner.user_id, vr.event_id, action)

            snapshot = await _read_weights(runner.user_id)
            weight_history.append(
                {"round": i + 1, "stage": stage_name, "weights": snapshot}
            )

    metrics = _compute_preference_metrics(all_results, weight_history, stages)
    return GroupResult(
        group="personalization",
        variant_results=all_results,
        judge_scores=[],
        metrics=metrics,
    )


def simulate_feedback(
    decision: dict, stage: str, rng: random.Random
) -> Literal["accept", "ignore"]:
    if stage == "high-freq":
        return "accept" if decision.get("should_remind") else "ignore"
    if stage == "silent":
        return (
            "accept"
            if decision.get("should_remind") and decision.get("is_urgent")
            else "ignore"
        )
    if stage == "visual-detail":
        return "accept" if decision.get("channel") == "visual" else "ignore"
    if stage == "mixed":
        return "accept" if rng.random() < 0.5 else "ignore"
    return "ignore"


async def update_feedback_weight(
    user_id: str, event_id: str, action: Literal["accept", "ignore"]
) -> None:
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


def _compute_preference_metrics(
    results: list[VariantResult],
    weight_history: list[dict],
    stages: list[tuple],
) -> dict:
    """计算个性化组四个量化指标。"""
    rounds = len(weight_history)
    preference_matching_rate = _compute_matching_rate(results, weight_history)
    convergence_speed = _compute_convergence_speed(weight_history)
    stability = _compute_stability(weight_history, stages)
    overfitting_gap = _compute_overfitting_gap(results, weight_history)

    return {
        "rounds": rounds,
        "weight_history": weight_history,
        "preference_matching_rate": preference_matching_rate,
        "convergence_speed": convergence_speed,
        "stability": stability,
        "overfitting_gap": overfitting_gap,
    }


def _compute_matching_rate(
    results: list[VariantResult],
    weight_history: list[dict],
) -> dict[str, float]:
    """偏好匹配率：每阶段 FULL 变体决策与阶段偏好的吻合度。"""
    full_results = [r for r in results if r.variant == Variant.FULL]
    stage_matches: dict[str, list[bool]] = {}

    for i, wh in enumerate(weight_history):
        stage = wh["stage"]
        if i >= len(full_results):
            break
        decision = full_results[i].decision
        matched = _decision_matches_stage(decision, stage)
        stage_matches.setdefault(stage, []).append(matched)

    return {
        stage: sum(matches) / len(matches) if matches else 0.0
        for stage, matches in stage_matches.items()
    }


def _decision_matches_stage(decision: dict, stage: str) -> bool:
    """单条决策是否匹配阶段偏好。"""
    if stage == "high-freq":
        return bool(decision.get("should_remind"))
    if stage == "silent":
        return bool(decision.get("should_remind")) and bool(decision.get("is_urgent"))
    if stage == "visual-detail":
        return decision.get("channel") == "visual"
    if stage == "mixed":
        return True  # 混合阶段无固定偏好
    return True


def _compute_convergence_speed(weight_history: list[dict]) -> float:
    """收敛速度：最高权重类型首次距终值 ±0.05 内且持续 ≥3 轮的轮次号（归一化）。"""
    if not weight_history or len(weight_history) < 2:
        return 1.0

    final_weights = weight_history[-1].get("weights", {})
    if not final_weights:
        return 1.0

    target_type = max(final_weights, key=final_weights.get)
    target_final = final_weights[target_type]

    consecutive = 0
    first_stable_round = -1
    for i, wh in enumerate(weight_history):
        current_weight = wh.get("weights", {}).get(target_type, 0.5)
        if abs(current_weight - target_final) <= 0.05:
            consecutive += 1
            if consecutive >= 3 and first_stable_round < 0:
                first_stable_round = i - 2
        else:
            consecutive = 0

    if first_stable_round < 0:
        return 1.0
    return first_stable_round / len(weight_history)


def _compute_stability(weight_history: list[dict], stages: list[tuple]) -> float:
    """稳定性：偏好切换后连续 5 轮权重的平均标准差。"""
    if not weight_history:
        return 0.0

    switch_points = [end for _, _, end in stages[:-1]]
    stds: list[float] = []

    for sp in switch_points:
        if sp >= len(weight_history):
            continue
        window = weight_history[sp : min(sp + 5, len(weight_history))]
        if not window:
            continue
        weights_per_round = [
            sum(wh.get("weights", {}).values()) / max(1, len(wh.get("weights", {})))
            for wh in window
        ]
        if len(weights_per_round) < 2:
            continue
        mean = sum(weights_per_round) / len(weights_per_round)
        variance = sum((w - mean) ** 2 for w in weights_per_round) / len(
            weights_per_round
        )
        stds.append(variance**0.5)

    return sum(stds) / len(stds) if stds else 0.0


def _compute_overfitting_gap(
    results: list[VariantResult],
    weight_history: list[dict],
) -> float:
    """过拟合检测：mixed 阶段 FULL vs NO_FEEDBACK 的偏好匹配率差（绝对值）。"""
    mixed_rounds = [
        i for i, wh in enumerate(weight_history) if wh.get("stage") == "mixed"
    ]
    if not mixed_rounds:
        return 0.0

    full_rounds = [r for r in results if r.variant == Variant.FULL]
    no_fb_rounds = [r for r in results if r.variant == Variant.NO_FEEDBACK]

    full_mixed = full_rounds[mixed_rounds[0] : mixed_rounds[-1] + 1]
    no_fb_mixed = no_fb_rounds[mixed_rounds[0] : mixed_rounds[-1] + 1]

    full_matches = sum(1 for r in full_mixed if bool(r.decision.get("should_remind")))
    no_fb_matches = sum(1 for r in no_fb_mixed if bool(r.decision.get("should_remind")))

    full_rate = full_matches / len(full_mixed) if full_mixed else 0.0
    no_fb_rate = no_fb_matches / len(no_fb_mixed) if no_fb_mixed else 0.0

    return abs(full_rate - no_fb_rate)
