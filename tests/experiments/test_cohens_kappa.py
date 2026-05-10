"""测试 Cohen's κ 计算."""

from experiments.ablation.judge import compute_cohens_kappa
from experiments.ablation.types import JudgeScores, Variant


def test_perfect_agreement():
    """Given Judge and human scores identical, κ should be 1.0."""
    judge = [
        JudgeScores("s1", Variant.FULL, 5, 5, 5, [], ""),
        JudgeScores("s2", Variant.FULL, 3, 3, 3, [], ""),
    ]
    human = {"s1": {"overall_score": 5}, "s2": {"overall_score": 3}}
    kappa = compute_cohens_kappa(judge, human)
    assert kappa == 1.0


def test_large_disagreement():
    """Given Judge always 5 but human always 1, κ should be negative or zero."""
    judge = [
        JudgeScores("s1", Variant.FULL, 5, 5, 5, [], ""),
        JudgeScores("s2", Variant.FULL, 5, 5, 5, [], ""),
    ]
    human = {"s1": {"overall_score": 1}, "s2": {"overall_score": 1}}
    kappa = compute_cohens_kappa(judge, human)
    assert kappa <= 0.0


def test_empty_inputs():
    """Given empty inputs, κ should be 1.0."""
    kappa = compute_cohens_kappa([], {})
    assert kappa == 1.0
