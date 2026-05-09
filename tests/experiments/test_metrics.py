"""测试指标计算."""

from experiments.ablation.metrics import cohens_d, compute_comparison
from experiments.ablation.types import JudgeScores, Variant


def test_cohens_d_large_effect():
    a = [5.0, 5.0, 5.0, 5.0, 5.0]
    b = [1.0, 1.0, 1.0, 1.0, 1.0]
    d = cohens_d(a, b)
    # 两组合并方差为零但均值不等 → 返回 inf（无组内变异，效应无限大）
    assert d == float("inf")


def test_cohens_d_no_difference():
    a = [3.0, 3.0, 3.0]
    b = [3.0, 3.0, 3.0]
    d = cohens_d(a, b)
    assert d == 0.0


def test_cohens_d_empty():
    assert cohens_d([], []) == 0.0
    assert cohens_d([1.0], []) == 0.0


def test_compute_comparison():
    scores = [
        JudgeScores("1", Variant.FULL, 5, 5, 5, [], ""),
        JudgeScores("2", Variant.FULL, 4, 4, 4, [], ""),
        JudgeScores("1", Variant.NO_RULES, 3, 3, 3, ["channel_violation"], ""),
        JudgeScores("2", Variant.NO_RULES, 2, 2, 2, ["channel_violation"], ""),
    ]
    comparison = compute_comparison(scores)
    assert "no-rules" in comparison
    assert comparison["no-rules"]["mean_score"] == 2.5
    assert comparison["no-rules"]["mean_diff"] == -2.0  # 2.5 - 4.5
