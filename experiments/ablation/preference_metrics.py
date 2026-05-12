"""个性化组偏好指标计算."""

import logging

from .feedback_simulator import has_visual_content
from .judge import detect_judge_degradation
from .types import JudgeScores, Variant, VariantResult

logger = logging.getLogger(__name__)

_MIN_HISTORY_LEN = 2
_INITIAL_WEIGHT_TOLERANCE = 0.01
_CONVERGENCE_TOLERANCE = 0.05
_CONSECUTIVE_FOR_CONVERGENCE = 3


def compute_preference_metrics(
    results: list[VariantResult],
    weight_history: list[dict],
    stages: list[tuple],
    *,
    scores: list[JudgeScores] | None = None,
) -> dict:
    """计算个性化组四个量化指标。"""
    rounds = len(weight_history)
    preference_matching_rate = _compute_matching_rate(results, weight_history)
    convergence_speed = _compute_convergence_speed(weight_history)
    stability = _compute_stability(weight_history, stages)
    decision_divergence = _compute_decision_divergence(results, weight_history)

    metrics = {
        "rounds": rounds,
        "weight_history": weight_history,
        "preference_matching_rate": preference_matching_rate,
        "convergence_speed": convergence_speed,
        "stability": stability,
        "decision_divergence": decision_divergence,
    }
    if scores is not None:
        metrics["_judge_degradation"] = detect_judge_degradation(scores)
    return metrics


def _compute_matching_rate(
    results: list[VariantResult],
    weight_history: list[dict],
) -> dict[str, float]:
    """偏好匹配率：每阶段 FULL 变体决策与阶段偏好的吻合度。"""
    full_results = [r for r in results if r.variant == Variant.FULL]

    # 以 round_index 建映射，消除对列表序的依赖
    # 注意：round_index >= 1（1-based），round_index=0 表示未分配轮次
    full_by_round = {r.round_index: r for r in full_results if r.round_index > 0}
    stage_matches: dict[str, list[bool]] = {}

    for wh in weight_history:
        ri = wh.get("round", 0)
        stage = wh["stage"]
        if ri not in full_by_round:
            logger.warning(
                "轮次 %d 缺少 FULL 变体结果——匹配率分母排除该轮，"
                "若多轮缺失可能导致匹配率虚高",
                ri,
            )
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
        return has_visual_content(decision)
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
        weights = wh.get("weights")
        if not isinstance(weights, dict) or target_type not in weights:
            # target_type 尚未出现——视为非收敛
            consecutive = 0
            continue
        current_weight = weights[target_type]
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

    # weight_history 索引为 0-based，VariantResult.round_index 为 1-based，
    # 故 i+1 转换匹配
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
