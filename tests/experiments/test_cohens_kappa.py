"""测试 Cohen's κ 计算."""

from experiments.ablation.judge import compute_cohens_kappa
from experiments.ablation.types import JudgeScores, Variant


def test_perfect_agreement_kappa_is_1():
    """给定 Judge 与人工评分完全一致，当计算 κ，则应为 1.0。"""
    judge = [
        JudgeScores("s1", Variant.FULL, 5, 5, 5, [], ""),
        JudgeScores("s2", Variant.FULL, 3, 3, 3, [], ""),
    ]
    human = {"s1": {"overall_score": 5}, "s2": {"overall_score": 3}}
    kappa = compute_cohens_kappa(judge, human)
    assert kappa == 1.0


def test_max_disagreement_kappa_le_0():
    """给定 Judge 评 5 但人工评 1，当计算 κ，则应为负或零。"""
    judge = [
        JudgeScores("s1", Variant.FULL, 5, 5, 5, [], ""),
        JudgeScores("s2", Variant.FULL, 5, 5, 5, [], ""),
    ]
    human = {"s1": {"overall_score": 1}, "s2": {"overall_score": 1}}
    kappa = compute_cohens_kappa(judge, human)
    assert kappa <= 0.0


def test_empty_input_kappa_is_0():
    """给定空输入，当计算 κ，则应返回 0.0（无有效样本无法评估一致性）。"""
    kappa = compute_cohens_kappa([], {})
    assert kappa == 0.0
