"""消融实验方法论优化测试."""

from experiments.ablation.metrics import bootstrap_ci, wilcoxon_test
from experiments.ablation.scenario_synthesizer import (
    _compute_safety_relevant,
    _parse_dims_from_id,
)
from experiments.ablation.types import JudgeScores, Scenario, Variant


class TestComputeSafetyRelevant:
    """合成维度安全分类."""

    def test_highway_always_safety(self):
        assert _compute_safety_relevant(
            {"scenario": "highway", "fatigue_level": 0.1, "workload": "low"}
        )

    def test_city_driving_normal_not_safety(self):
        assert not _compute_safety_relevant(
            {"scenario": "city_driving", "fatigue_level": 0.1, "workload": "normal"}
        )

    def test_high_fatigue_is_safety(self):
        assert _compute_safety_relevant(
            {"scenario": "city_driving", "fatigue_level": 0.9, "workload": "normal"}
        )

    def test_overloaded_is_safety(self):
        assert _compute_safety_relevant(
            {"scenario": "traffic_jam", "fatigue_level": 0.1, "workload": "overloaded"}
        )

    def test_parked_low_fatigue_not_safety(self):
        assert not _compute_safety_relevant(
            {"scenario": "parked", "fatigue_level": 0.1, "workload": "low"}
        )


class TestParseDimsFromId:
    """从场景 id 解析合成维度."""

    def test_highway_id(self):
        result = _parse_dims_from_id("highway_0.1_low_meeting_true")
        assert result["scenario"] == "highway"
        assert result["fatigue_level"] == 0.1

    def test_city_driving_id_with_underscore(self):
        result = _parse_dims_from_id("city_driving_0.5_normal_travel_false")
        assert result["scenario"] == "city_driving"
        assert result["workload"] == "normal"

    def test_unknown_prefix_returns_empty(self):
        assert _parse_dims_from_id("unknown_0.1_low_meeting_true") == {}


class TestBootstrapCI:
    """Bootstrap 置信区间."""

    def test_significant_difference(self):
        group_a = [4.0, 5.0, 4.0, 5.0, 4.0]
        group_b = [2.0, 1.0, 2.0, 1.0, 2.0]
        result = bootstrap_ci(group_a, group_b)
        assert result["significant"]
        assert result["ci_lower"] > 0

    def test_no_difference(self):
        group = [3.0, 3.0, 3.0, 3.0, 3.0]
        result = bootstrap_ci(group, group)
        assert not result["significant"]

    def test_empty_groups(self):
        result = bootstrap_ci([], [])
        assert not result["significant"]


class TestWilcoxonTest:
    """Wilcoxon signed-rank test."""

    def _make_scores(
        self,
        baseline_scores: list[int],
        variant_scores: list[int],
        variant_name: str,
    ) -> list[JudgeScores]:
        scores = []
        for i, s in enumerate(baseline_scores):
            scores.append(
                JudgeScores(
                    scenario_id=f"s{i}",
                    variant=Variant.FULL,
                    safety_score=3,
                    reasonableness_score=3,
                    overall_score=s,
                    violation_flags=[],
                    explanation="",
                )
            )
        for i, s in enumerate(variant_scores):
            scores.append(
                JudgeScores(
                    scenario_id=f"s{i}",
                    variant=Variant(variant_name),
                    safety_score=3,
                    reasonableness_score=3,
                    overall_score=s,
                    violation_flags=[],
                    explanation="",
                )
            )
        return scores

    def test_paired_comparison(self):
        baseline = [4, 5, 4, 5, 4]
        variant = [2, 3, 2, 3, 2]
        scores = self._make_scores(baseline, variant, "no-rules")
        result = wilcoxon_test(scores)
        assert "no-rules" in result
        assert result["no-rules"]["n_pairs"] == 5


class TestStratumFunctions:
    """分层键使用合成维度."""

    def test_safety_stratum_with_dims(self):
        from experiments.ablation.safety_group import safety_stratum

        s = Scenario(
            id="highway_0.9_low_meeting_true",
            driving_context={},
            user_query="",
            expected_decision={},
            expected_task_type="meeting",
            safety_relevant=True,
            scenario_type="highway",
            synthesis_dims={
                "scenario": "highway",
                "fatigue_level": 0.9,
                "workload": "low",
                "task_type": "meeting",
                "has_passengers": "true",
            },
        )
        key = safety_stratum(s)
        assert "highway" in key

    def test_arch_stratum_with_dims(self):
        from experiments.ablation.architecture_group import arch_stratum

        s = Scenario(
            id="parked_0.1_normal_shopping_false",
            driving_context={},
            user_query="",
            expected_decision={},
            expected_task_type="shopping",
            safety_relevant=False,
            scenario_type="parked",
            synthesis_dims={
                "scenario": "parked",
                "fatigue_level": 0.1,
                "workload": "normal",
                "task_type": "shopping",
                "has_passengers": "false",
            },
        )
        assert arch_stratum(s) == "parked:shopping"

    def test_is_arch_scenario_excludes_highway(self):
        from experiments.ablation.architecture_group import is_arch_scenario

        s = Scenario(
            id="highway_0.1_low_meeting_true",
            driving_context={},
            user_query="",
            expected_decision={},
            expected_task_type="meeting",
            safety_relevant=True,
            scenario_type="highway",
            synthesis_dims={
                "scenario": "highway",
                "fatigue_level": 0.1,
                "workload": "low",
                "task_type": "meeting",
                "has_passengers": "true",
            },
        )
        assert not is_arch_scenario(s)

    def test_no_dims_fallback(self):
        from experiments.ablation.safety_group import safety_stratum

        s = Scenario(
            id="unknown",
            driving_context={},
            user_query="",
            expected_decision={},
            expected_task_type="meeting",
            safety_relevant=True,
            scenario_type="highway",
        )
        assert safety_stratum(s) == "highway"


class TestBuildStages:
    """个性化组动态轮数截断."""

    def test_full_32_produces_4_equal_stages(self):
        from experiments.ablation.personalization_group import _build_stages

        stages, available = _build_stages(32)
        assert available == 32
        assert len(stages) == 4
        assert stages[-1][2] == 32

    def test_less_than_32_truncates(self):
        from experiments.ablation.personalization_group import _build_stages

        stages, available = _build_stages(20)
        assert available == 20
        assert stages[-1][2] == 20

    def test_minimum_4_scenarios(self):
        from experiments.ablation.personalization_group import _build_stages

        stages, available = _build_stages(4)
        assert available == 4
        assert len(stages) == 4

    def test_below_minimum_raises(self):
        import pytest

        from experiments.ablation.personalization_group import _build_stages

        with pytest.raises(ValueError, match="≥4"):
            _build_stages(3)


class TestFormatRulesForJudge:
    """Judge 规则动态生成."""

    def test_generates_rule_descriptions(self):
        from app.agents.rules import SAFETY_RULES
        from experiments.ablation.judge import format_rules_for_judge

        text = format_rules_for_judge(SAFETY_RULES)
        assert "规则1" in text
        assert "priority=" in text
        assert "fatigue" in text.lower()
        assert "highway" in text.lower()

    def test_empty_rules_returns_empty(self):
        from experiments.ablation.judge import format_rules_for_judge

        assert format_rules_for_judge([]) == ""

    def test_rule_count_matches_safety_rules(self):
        from app.agents.rules import SAFETY_RULES
        from experiments.ablation.judge import format_rules_for_judge

        text = format_rules_for_judge(SAFETY_RULES)
        assert text.count("规则") == len(SAFETY_RULES)
