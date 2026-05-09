"""个性化组实验——反馈学习机制的个性化效果."""

import random
from collections.abc import MutableMapping
from pathlib import Path
from typing import Literal

from app.config import user_data_dir
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.storage.toml_store import TOMLStore
from experiments.ablation.ablation_runner import AblationRunner
from experiments.ablation.types import GroupResult, TestScenario, Variant, VariantResult


async def run_personalization_group(
    runner: AblationRunner,
    scenarios: list[TestScenario],
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

    metrics = _compute_preference_metrics(all_results, weight_history)
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


def _compute_preference_metrics(results, weight_history) -> dict:
    return {
        "rounds": len(weight_history),
        "weight_history": weight_history,
    }
