"""报告生成测试."""

from experiments.ablation.report import _score_distribution
from experiments.ablation.types import JudgeScores, Variant


class TestScoreDistribution:
    """分数分布分析."""

    def test_basic_distribution(self):
        scores = [
            JudgeScores("s1", Variant.FULL, 4, 4, 4, [], ""),
            JudgeScores("s1", Variant.NO_RULES, 3, 3, 3, [], ""),
            JudgeScores("s2", Variant.FULL, 5, 5, 5, [], ""),
            JudgeScores("s2", Variant.NO_RULES, 2, 2, 2, [], ""),
        ]
        dist = _score_distribution(scores)
        assert "full" in dist
        assert "no-rules" in dist
        assert dist["full"]["mean"] == 4.5
        assert dist["full"]["distribution"]["4"] == 0.5
        assert dist["full"]["distribution"]["5"] == 0.5

    def test_empty_scores(self):
        dist = _score_distribution([])
        assert dist == {}
