"""测试个性化组指标."""

import random
from unittest import mock

import pytest

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


def test_has_visual_content_detects_display_text():
    """给定 decision 仅含 display_text，当检测视觉内容，则应返回 True。"""
    from experiments.ablation.feedback_simulator import has_visual_content

    decision = {
        "reminder_content": {
            "display_text": "会议 · 15:00",
        }
    }
    assert has_visual_content(decision)


def test_has_visual_content_detects_detailed_only():
    """给定 decision 仅含 detailed（无 display_text），当检测视觉内容，则应返回 True。"""
    from experiments.ablation.feedback_simulator import has_visual_content

    decision = {
        "reminder_content": {
            "detailed": "下午3点在公司3楼会议室",
        }
    }
    assert has_visual_content(decision)


def test_has_visual_content_no_visual_returns_false():
    """给定 decision 无任何视觉内容，当检测视觉内容，则应返回 False。"""
    from experiments.ablation.feedback_simulator import has_visual_content

    assert not has_visual_content({})


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


# ── simulate_feedback 三要素模型 ──


def test_simulate_high_freq_should_remind_returns_accept():
    """Given high-freq stage with should_remind=True, When feedback simulated, Then returns accept."""
    from experiments.ablation.feedback_simulator import simulate_feedback

    with mock.patch(
        "experiments.ablation.feedback_simulator.get_fatigue_threshold",
        return_value=0.9,
    ):
        ctx = {"driver": {"fatigue_level": 0.0, "workload": "normal"}}
        rng = random.Random(1)
        assert (
            simulate_feedback(
                {"should_remind": True}, "high-freq", rng, driving_context=ctx
            )
            == "accept"
        )


def test_simulate_high_freq_no_remind_returns_ignore():
    """Given high-freq stage with should_remind=False, When feedback simulated, Then returns ignore."""
    from experiments.ablation.feedback_simulator import simulate_feedback

    with mock.patch(
        "experiments.ablation.feedback_simulator.get_fatigue_threshold",
        return_value=0.9,
    ):
        ctx = {"driver": {"fatigue_level": 0.0, "workload": "normal"}}
        rng = random.Random(1)
        assert (
            simulate_feedback(
                {"should_remind": False}, "high-freq", rng, driving_context=ctx
            )
            == "ignore"
        )


def test_simulate_silent_no_remind_returns_accept():
    """Given silent stage with should_remind=False, When feedback simulated, Then returns accept."""
    from experiments.ablation.feedback_simulator import simulate_feedback

    with mock.patch(
        "experiments.ablation.feedback_simulator.get_fatigue_threshold",
        return_value=0.9,
    ):
        ctx = {"driver": {"fatigue_level": 0.0, "workload": "normal"}}
        rng = random.Random(1)
        assert (
            simulate_feedback(
                {"should_remind": False}, "silent", rng, driving_context=ctx
            )
            == "accept"
        )


def test_simulate_silent_emergency_returns_accept():
    """Given silent stage with is_emergency=True, When feedback simulated, Then returns accept."""
    from experiments.ablation.feedback_simulator import simulate_feedback

    with mock.patch(
        "experiments.ablation.feedback_simulator.get_fatigue_threshold",
        return_value=0.9,
    ):
        ctx = {"driver": {"fatigue_level": 0.0, "workload": "normal"}}
        rng = random.Random(1)
        assert (
            simulate_feedback(
                {"should_remind": True, "is_emergency": True},
                "silent",
                rng,
                driving_context=ctx,
            )
            == "accept"
        )


def test_simulate_silent_non_emergency_returns_ignore():
    """Given silent stage with non-emergency, When should_remind=True, Then returns ignore."""
    from experiments.ablation.feedback_simulator import simulate_feedback

    with mock.patch(
        "experiments.ablation.feedback_simulator.get_fatigue_threshold",
        return_value=0.9,
    ):
        ctx = {"driver": {"fatigue_level": 0.0, "workload": "normal"}}
        rng = random.Random(1)
        assert (
            simulate_feedback(
                {"should_remind": True, "is_emergency": False},
                "silent",
                rng,
                driving_context=ctx,
            )
            == "ignore"
        )


def test_simulate_visual_detail_with_content_returns_accept():
    """Given visual-detail stage with display_text content, When feedback simulated, Then returns accept."""
    from experiments.ablation.feedback_simulator import simulate_feedback

    with mock.patch(
        "experiments.ablation.feedback_simulator.get_fatigue_threshold",
        return_value=0.9,
    ):
        ctx = {"driver": {"fatigue_level": 0.0, "workload": "normal"}}
        rng = random.Random(1)
        decision_with = {"reminder_content": {"display_text": "会议 · 15:00"}}
        assert (
            simulate_feedback(decision_with, "visual-detail", rng, driving_context=ctx)
            == "accept"
        )


def test_simulate_visual_detail_empty_returns_ignore():
    """Given visual-detail stage with empty decision, When feedback simulated, Then returns ignore."""
    from experiments.ablation.feedback_simulator import simulate_feedback

    with mock.patch(
        "experiments.ablation.feedback_simulator.get_fatigue_threshold",
        return_value=0.9,
    ):
        ctx = {"driver": {"fatigue_level": 0.0, "workload": "normal"}}
        rng = random.Random(1)
        assert (
            simulate_feedback({}, "visual-detail", rng, driving_context=ctx) == "ignore"
        )


def test_simulate_mixed_should_remind_returns_accept():
    """Given mixed stage with should_remind=True, alignment > 0.5, When feedback simulated, Then returns accept."""
    from experiments.ablation.feedback_simulator import simulate_feedback

    with mock.patch(
        "experiments.ablation.feedback_simulator.get_fatigue_threshold",
        return_value=0.9,
    ):
        ctx = {"driver": {"fatigue_level": 0.0, "workload": "normal"}}
        rng = random.Random(1)
        assert (
            simulate_feedback(
                {"should_remind": True}, "mixed", rng, driving_context=ctx
            )
            == "accept"
        )


def test_simulate_mixed_no_remind_returns_ignore():
    """Given mixed stage with should_remind=False, alignment < 0.5, When feedback simulated, Then returns ignore."""
    from experiments.ablation.feedback_simulator import simulate_feedback

    with mock.patch(
        "experiments.ablation.feedback_simulator.get_fatigue_threshold",
        return_value=0.9,
    ):
        ctx = {"driver": {"fatigue_level": 0.0, "workload": "normal"}}
        rng = random.Random(1)
        assert (
            simulate_feedback(
                {"should_remind": False}, "mixed", rng, driving_context=ctx
            )
            == "ignore"
        )


def test_simulate_noise_flip_returns_ignore():
    """Given alignment=1.0 but noise triggers, When feedback simulated, Then may return ignore (user error)."""
    from experiments.ablation.feedback_simulator import simulate_feedback

    with mock.patch(
        "experiments.ablation.feedback_simulator.get_fatigue_threshold",
        return_value=0.9,
    ):
        ctx = {"driver": {"fatigue_level": 1.0, "workload": "normal"}}
        rng = random.Random(7)
        expected = simulate_feedback(
            {"should_remind": True}, "high-freq", rng, driving_context=ctx
        )
        assert expected == "ignore", f"应因噪声翻转为 ignore，实际为 {expected}"


def test_simulate_noise_high_fatigue_changes_output():
    """Given high fatigue increases noise threshold, When same seed with diff fatigue, Then output differs."""
    from experiments.ablation.feedback_simulator import simulate_feedback

    with mock.patch(
        "experiments.ablation.feedback_simulator.get_fatigue_threshold",
        return_value=1.0,
    ):
        decision = {"should_remind": True}

        rng_low = random.Random(7)
        rng_high = random.Random(7)

        result_low = simulate_feedback(
            decision,
            "high-freq",
            rng_low,
            driving_context={"driver": {"fatigue_level": 0.0, "workload": "normal"}},
        )
        result_high = simulate_feedback(
            decision,
            "high-freq",
            rng_high,
            driving_context={"driver": {"fatigue_level": 1.0, "workload": "normal"}},
        )
        assert result_low != result_high, "不同疲劳度下的噪声阈值应导致不同输出"


def test_simulate_suppression_overloaded_returns_none():
    """Given overloaded reduces fb_prob, When feedback simulated, Then returns None."""
    from experiments.ablation.feedback_simulator import simulate_feedback

    with mock.patch(
        "experiments.ablation.feedback_simulator.get_fatigue_threshold",
        return_value=0.9,
    ):
        decision = {"should_remind": True}

        rng_normal = random.Random(6)
        rng_overloaded = random.Random(6)

        result_normal = simulate_feedback(
            decision,
            "high-freq",
            rng_normal,
            driving_context={"driver": {"fatigue_level": 0.0, "workload": "normal"}},
        )
        result_overloaded = simulate_feedback(
            decision,
            "high-freq",
            rng_overloaded,
            driving_context={
                "driver": {"fatigue_level": 0.0, "workload": "overloaded"}
            },
        )
        assert result_normal == "accept"
        assert result_overloaded is None


def test_simulate_suppression_high_fatigue_returns_none():
    """Given high fatigue reduces fb_prob, When feedback simulated, Then returns None."""
    from experiments.ablation.feedback_simulator import simulate_feedback

    with mock.patch(
        "experiments.ablation.feedback_simulator.get_fatigue_threshold",
        return_value=0.7,
    ):
        decision = {"should_remind": True}

        rng_low = random.Random(6)
        rng_high = random.Random(6)

        result_low = simulate_feedback(
            decision,
            "high-freq",
            rng_low,
            driving_context={"driver": {"fatigue_level": 0.0, "workload": "normal"}},
        )
        result_high = simulate_feedback(
            decision,
            "high-freq",
            rng_high,
            driving_context={"driver": {"fatigue_level": 0.8, "workload": "normal"}},
        )
        assert result_low == "accept"
        assert result_high is None


def test_simulate_no_driving_context_returns_valid_choice():
    """Given driving_context=None, When feedback simulated, Then returns valid choice without exception."""
    from experiments.ablation.feedback_simulator import simulate_feedback

    rng = random.Random(0)
    result = simulate_feedback({"should_remind": True}, "high-freq", rng)
    assert result in ("accept", "ignore", None)


# ── _adaptive_delta 自适应步长 ──


async def test_adaptive_delta_convergence():
    """同向 3 次 → 步长 0.15，反向 → 0.075。不同 user_id+task_type 隔离。"""
    from experiments.ablation.feedback_simulator import (
        _adaptive_delta,
        _current_delta,
        _recent_feedback,
    )

    _current_delta.clear()
    _recent_feedback.clear()

    d1 = _adaptive_delta("user1", "meeting", "accept")
    assert d1 == 0.1, f"info不足应 0.1, got {d1}"

    d2 = _adaptive_delta("user1", "meeting", "accept")
    assert d2 == 0.1, f"信息不足应 0.1, got {d2}"

    d3 = _adaptive_delta("user1", "meeting", "accept")
    assert d3 == pytest.approx(0.15), f"同向 3 次应 0.15, got {d3}"

    d4 = _adaptive_delta("user1", "meeting", "ignore")
    assert d4 == pytest.approx(0.075), f"反向应 0.075, got {d4}"

    # 不同 user_id + task_type 隔离
    _current_delta.clear()
    _recent_feedback.clear()
    d = _adaptive_delta("user2", "shopping", "ignore")
    assert d == 0.1

    # 同一 task_type 不同 user_id 隔离
    d_user2 = _adaptive_delta("user2", "meeting", "accept")
    assert d_user2 == 0.1  # user2 的 meeting 历史为空

    _current_delta.clear()
    _recent_feedback.clear()
