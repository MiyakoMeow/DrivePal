"""测试个性化组指标."""

from experiments.ablation.preference_metrics import (
    _compute_decision_divergence,
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
    from experiments.ablation.feedback_simulator import _has_visual_content

    decision = {"should_remind": False, "reminder_content": ""}
    stages = {
        "decision": {
            "reminder_content": {
                "display_text": "会议 · 15:00",
                "detailed": "下午3点在公司3楼会议室",
            }
        }
    }
    assert _has_visual_content(decision, stages=stages)


def test_has_visual_content_falls_back_to_decision():
    """给定 stages 为空，当检测视觉内容，则应回退到 decision 检查。"""
    from experiments.ablation.feedback_simulator import _has_visual_content

    decision = {
        "reminder_content": {
            "display_text": "会议 · 15:00",
        }
    }
    assert _has_visual_content(decision, stages={})


def test_has_visual_content_no_visual_returns_false():
    """给定 stages 和 decision 均无视觉内容，当检测视觉内容，则应返回 False。"""
    from experiments.ablation.feedback_simulator import _has_visual_content

    assert not _has_visual_content({}, stages={})
