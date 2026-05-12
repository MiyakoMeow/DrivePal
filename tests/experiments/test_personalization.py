"""测试个性化组指标."""

from experiments.ablation.preference_metrics import (
    _compute_convergence_speed,
    _compute_decision_divergence,
    _compute_matching_rate,
    _compute_stability,
)
from experiments.ablation.types import Variant, VariantResult


def test_stability_no_oscillation_returns_zero():
    """给定切换后权重稳定不变，当计算稳定性，则应为 0.0。"""
    wh = [
        {"weights": {"meeting": 0.9, "travel": 0.5}},  # round 1
        {"weights": {"meeting": 0.9, "travel": 0.5}},  # round 2 (切换点=2)
        {"weights": {"meeting": 0.3, "travel": 0.5}},  # round 3
        {"weights": {"meeting": 0.3, "travel": 0.5}},  # round 4
        {"weights": {"meeting": 0.3, "travel": 0.5}},  # round 5
        {"weights": {"meeting": 0.3, "travel": 0.5}},  # round 6
        {"weights": {"meeting": 0.3, "travel": 0.5}},  # round 7
    ]
    stages = [("high-freq", 0, 2), ("silent", 2, 7)]
    result = _compute_stability(wh, stages)
    assert result == 0.0


def test_stability_with_oscillation_returns_positive():
    """给定切换后目标类型权重振荡，当计算稳定性，则结果应 > 0。"""
    wh = [
        {"weights": {"meeting": 0.9, "travel": 0.5}},  # round 1
        {"weights": {"meeting": 0.9, "travel": 0.5}},  # round 2 (切换)
        {"weights": {"meeting": 0.3, "travel": 0.5}},  # round 3
        {"weights": {"meeting": 0.7, "travel": 0.5}},  # round 4 (上跳)
        {"weights": {"meeting": 0.2, "travel": 0.5}},  # round 5 (下跳)
        {"weights": {"meeting": 0.6, "travel": 0.5}},  # round 6
        {"weights": {"meeting": 0.4, "travel": 0.5}},  # round 7
    ]
    stages = [("high-freq", 0, 2), ("silent", 2, 7)]
    result = _compute_stability(wh, stages)
    assert result > 0.0


def test_stability_initial_state_skipped_returns_zero():
    """给定所有权重均为初始态 0.5，当计算稳定性，则跳过切换点返回 0.0。"""
    wh = [
        {"weights": {"meeting": 0.5, "travel": 0.5}},  # round 1
        {"weights": {"meeting": 0.5, "travel": 0.5}},  # round 2
        {"weights": {"meeting": 0.5, "travel": 0.5}},  # round 3
    ]
    stages = [("high-freq", 0, 2), ("silent", 2, 3)]
    result = _compute_stability(wh, stages)
    assert result == 0.0


def test_decision_divergence_same_decisions_returns_zero():
    """给定 FULL 与 NO_FEEDBACK 决策完全相同，当计算分歧度，则应为 0.0。"""
    vr_full = VariantResult(
        "s1",
        Variant.FULL,
        {"should_remind": True},
        "",
        None,
        {},
        0,
        round_index=17,
    )
    vr_nofb = VariantResult(
        "s1",
        Variant.NO_FEEDBACK,
        {"should_remind": True},
        "",
        None,
        {},
        0,
        round_index=17,
    )
    wh = [{"stage": "mixed"} for _ in range(20)]
    result = _compute_decision_divergence([vr_full, vr_nofb], wh)
    assert result == 0.0


def test_decision_divergence_different_decisions_returns_positive():
    """给定 FULL 与 NO_FEEDBACK 决策不同，当计算分歧度，则结果应 > 0。"""
    vr_full = VariantResult(
        "s1",
        Variant.FULL,
        {"should_remind": True, "allowed_channels": ["audio"]},
        "",
        None,
        {},
        0,
        round_index=17,
    )
    vr_nofb = VariantResult(
        "s1",
        Variant.NO_FEEDBACK,
        {"should_remind": False, "allowed_channels": ["visual"]},
        "",
        None,
        {},
        0,
        round_index=17,
    )
    wh = [{"stage": "mixed"} for _ in range(20)]
    result = _compute_decision_divergence([vr_full, vr_nofb], wh)
    assert result > 0.0


def test_has_visual_content_prefers_stages_over_decision():
    """给定 stages 中有视觉内容但 decision 中被清除，当检测视觉内容，则应返回 True。"""
    from experiments.ablation.feedback_simulator import has_visual_content

    decision = {"should_remind": False, "reminder_content": ""}
    stages = {
        "decision": {
            "reminder_content": {
                "display_text": "会议 · 15:00",
                "detailed": "下午3点在公司3楼会议室",
            }
        }
    }
    assert has_visual_content(decision, stages=stages)


def test_has_visual_content_falls_back_to_decision():
    """给定 stages 为空，当检测视觉内容，则应回退到 decision 检查。"""
    from experiments.ablation.feedback_simulator import has_visual_content

    decision = {
        "reminder_content": {
            "display_text": "会议 · 15:00",
        }
    }
    assert has_visual_content(decision, stages={})


def test_has_visual_content_no_visual_returns_false():
    """给定 stages 和 decision 均无视觉内容，当检测视觉内容，则应返回 False。"""
    from experiments.ablation.feedback_simulator import has_visual_content

    assert not has_visual_content({}, stages={})


# ── _compute_matching_rate ──


def test_matching_rate_full_decisions_match_high_freq_stage():
    """给定 FULL 变体在高频阶段所有轮次 should_remind=True，当计算匹配率，则应为 1.0。"""
    results = [
        VariantResult(
            f"s{i}",
            Variant.FULL,
            {"should_remind": True},
            "",
            None,
            {},
            0,
            round_index=i,
        )
        for i in range(1, 5)
    ]
    wh = [{"round": i, "stage": "high-freq"} for i in range(1, 5)]
    r = _compute_matching_rate(results, wh)
    assert "high-freq" in r
    assert r["high-freq"] == 1.0


def test_matching_rate_full_decisions_mismatch_returns_low():
    """给定 FULL 变体在高频阶段所有轮次 should_remind=False，当计算匹配率，则应为 0.0。"""
    results = [
        VariantResult(
            f"s{i}",
            Variant.FULL,
            {"should_remind": False},
            "",
            None,
            {},
            0,
            round_index=i,
        )
        for i in range(1, 5)
    ]
    wh = [{"round": i, "stage": "high-freq"} for i in range(1, 5)]
    r = _compute_matching_rate(results, wh)
    assert r["high-freq"] == 0.0


def test_matching_rate_mixed_stage_excluded():
    """给定 mixed 阶段，当计算匹配率，则 mixed 不应出现在返回键中。"""
    results = [
        VariantResult(
            "s1", Variant.FULL, {"should_remind": True}, "", None, {}, 0, round_index=1
        )
    ]
    wh = [{"round": 1, "stage": "mixed"}]
    r = _compute_matching_rate(results, wh)
    assert "mixed" not in r


def test_matching_rate_empty_weight_history_returns_empty():
    """给定空 weight_history，当计算匹配率，则应返回空 dict。"""
    r = _compute_matching_rate([], [])
    assert r == {}


def test_matching_rate_missing_full_result_logged():
    """给定某轮缺少 FULL 变体结果，当计算匹配率，则跳过该轮且分母不包含。"""
    results = [
        VariantResult(
            "s2", Variant.FULL, {"should_remind": True}, "", None, {}, 0, round_index=2
        )
    ]
    wh = [
        {"round": 1, "stage": "high-freq"},
        {"round": 2, "stage": "high-freq"},
    ]
    r = _compute_matching_rate(results, wh)
    assert r["high-freq"] == 1.0  # 仅计 round 2，符合预期


# ── _compute_convergence_speed ──


def test_convergence_speed_converging_weights():
    """给定权重逐步收敛至目标类型，当计算收敛速度，则应返回 < 1.0 的归一化值。"""
    wh = [
        {"weights": {"meeting": 0.5, "travel": 0.5}},  # 1
        {"weights": {"meeting": 0.6, "travel": 0.5}},  # 2
        {"weights": {"meeting": 0.8, "travel": 0.5}},  # 3
        {"weights": {"meeting": 0.9, "travel": 0.5}},  # 4
        {"weights": {"meeting": 0.9, "travel": 0.5}},  # 5
        {"weights": {"meeting": 0.9, "travel": 0.5}},  # 6
    ]
    result = _compute_convergence_speed(wh)
    assert 0.0 < result < 1.0


def test_convergence_speed_not_converged_returns_negative():
    """给定权重始终振荡未收敛，当计算收敛速度，则应返回 -1.0。"""
    wh = [
        {"weights": {"meeting": 0.3, "travel": 0.5}},
        {"weights": {"meeting": 0.7, "travel": 0.5}},
        {"weights": {"meeting": 0.3, "travel": 0.5}},
        {"weights": {"meeting": 0.7, "travel": 0.5}},
    ]
    result = _compute_convergence_speed(wh)
    assert result == -1.0


def test_convergence_speed_empty_history_returns_negative():
    """给定空 weight_history，当计算收敛速度，则应返回 -1.0。"""
    result = _compute_convergence_speed([])
    assert result == -1.0


def test_convergence_speed_single_entry_returns_negative():
    """给定仅一条 weight_history，当计算收敛速度，则应返回 -1.0（不足 MIN_HISTORY_LEN）。"""
    wh = [{"weights": {"meeting": 0.9}}]
    result = _compute_convergence_speed(wh)
    assert result == -1.0


def test_convergence_speed_target_type_tie_uses_lexical_tiebreaker():
    """给定最终最高权重并列，当计算收敛速度，则应取字典序最小者并正常计算。"""
    wh = [
        {"weights": {"a": 0.5, "z": 0.5}},
        {"weights": {"a": 0.8, "z": 0.8}},
        {"weights": {"a": 0.8, "z": 0.8}},
        {"weights": {"a": 0.8, "z": 0.8}},
    ]
    result = _compute_convergence_speed(wh)
    assert 0.0 <= result <= 1.0  # "a" 应胜出（字典序< "z"）
