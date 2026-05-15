"""测试架构组实验."""

from experiments.ablation.architecture_group import (
    classify_complexity,
    compute_quality_metrics,
    make_architecture_config,
)
from experiments.ablation.types import JudgeScores, Variant, VariantResult


class TestClassifyComplexity:
    def test_highway_is_complex(self):
        assert classify_complexity(
            {"scenario": "highway", "fatigue_level": 0.3, "workload": "normal"}
        )

    def test_high_fatigue_is_complex(self, monkeypatch):
        monkeypatch.setattr(
            "experiments.ablation._io.get_fatigue_threshold", lambda: 0.7
        )
        assert classify_complexity(
            {"scenario": "urban", "fatigue_level": 0.8, "workload": "normal"}
        )

    def test_overloaded_is_complex(self):
        assert classify_complexity(
            {"scenario": "urban", "fatigue_level": 0.3, "workload": "overloaded"}
        )

    def test_simple_scenario(self):
        assert not classify_complexity(
            {"scenario": "urban", "fatigue_level": 0.3, "workload": "normal"}
        )

    def test_empty_dims(self):
        assert not classify_complexity({})

    def test_missing_keys_fallback_gracefully(self):
        assert classify_complexity({"scenario": "highway"})
        assert not classify_complexity({"scenario": "urban"})

    def test_boundary_fatigue_threshold(self, monkeypatch):
        monkeypatch.setattr(
            "experiments.ablation._io.get_fatigue_threshold", lambda: 0.7
        )
        assert not classify_complexity(
            {"scenario": "urban", "fatigue_level": 0.7, "workload": "normal"}
        )
        assert classify_complexity(
            {"scenario": "urban", "fatigue_level": 0.71, "workload": "normal"}
        )


class TestComputeQualityMetrics:
    def test_flat_structure_when_no_complexity_map(self):
        scores = [
            JudgeScores("1", Variant.FULL, 4, 4, 4, [], ""),
            JudgeScores("2", Variant.FULL, 5, 5, 5, [], ""),
            JudgeScores("1", Variant.SINGLE_LLM, 3, 3, 3, [], ""),
            JudgeScores("2", Variant.SINGLE_LLM, 2, 2, 2, [], ""),
        ]
        results = [
            VariantResult("1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("2", Variant.FULL, {}, "", None, {}, 150),
            VariantResult("1", Variant.SINGLE_LLM, {}, "", None, {}, 50),
            VariantResult("2", Variant.SINGLE_LLM, {}, "", None, {}, 80),
        ]
        metrics = compute_quality_metrics(scores, results)
        assert "full" in metrics
        assert "single-llm" in metrics
        assert "_comparison" in metrics
        assert "_judge_degradation" in metrics

    def test_flat_backward_compat_scores_match(self):
        scores = [
            JudgeScores("1", Variant.FULL, 4, 4, 4, [], ""),
            JudgeScores("1", Variant.SINGLE_LLM, 3, 3, 3, [], ""),
        ]
        results = [
            VariantResult("1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("1", Variant.SINGLE_LLM, {}, "", None, {}, 50),
        ]
        metrics = compute_quality_metrics(scores, results)
        assert metrics["full"]["avg_overall_score"] == 4.0
        assert metrics["single-llm"]["avg_overall_score"] == 3.0
        assert metrics["full"]["n"] == 1

    def test_two_layer_with_complexity_map(self):
        scores = [
            JudgeScores("1", Variant.FULL, 4, 4, 4, [], ""),
            JudgeScores("2", Variant.FULL, 5, 5, 5, [], ""),
            JudgeScores("1", Variant.SINGLE_LLM, 3, 3, 3, [], ""),
            JudgeScores("2", Variant.SINGLE_LLM, 2, 2, 2, [], ""),
        ]
        results = [
            VariantResult("1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("2", Variant.FULL, {}, "", None, {}, 150),
            VariantResult("1", Variant.SINGLE_LLM, {}, "", None, {}, 50),
            VariantResult("2", Variant.SINGLE_LLM, {}, "", None, {}, 80),
        ]
        complexity_map = {"1": True, "2": False}
        metrics = compute_quality_metrics(scores, results, complexity_map)
        assert "simple" in metrics
        assert "complex" in metrics
        assert "comparison_simple" in metrics
        assert "comparison_complex" in metrics
        assert "_judge_degradation" in metrics
        assert metrics["simple"]["full"]["n"] == 1
        assert metrics["simple"]["single-llm"]["n"] == 1
        assert metrics["complex"]["full"]["n"] == 1
        assert metrics["complex"]["single-llm"]["n"] == 1

    def test_two_layer_scores_correct(self):
        scores = [
            JudgeScores("1", Variant.FULL, 4, 4, 4, [], ""),
            JudgeScores("2", Variant.FULL, 5, 5, 5, [], ""),
            JudgeScores("1", Variant.SINGLE_LLM, 3, 3, 3, [], ""),
            JudgeScores("2", Variant.SINGLE_LLM, 2, 2, 2, [], ""),
        ]
        results = [
            VariantResult("1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("2", Variant.FULL, {}, "", None, {}, 150),
            VariantResult("1", Variant.SINGLE_LLM, {}, "", None, {}, 50),
            VariantResult("2", Variant.SINGLE_LLM, {}, "", None, {}, 80),
        ]
        complexity_map = {"1": True, "2": False}
        metrics = compute_quality_metrics(scores, results, complexity_map)
        assert metrics["simple"]["full"]["avg_overall_score"] == 5.0
        assert metrics["complex"]["full"]["avg_overall_score"] == 4.0
        assert metrics["simple"]["single-llm"]["avg_overall_score"] == 2.0
        assert metrics["complex"]["single-llm"]["avg_overall_score"] == 3.0

    def test_judge_degradation_at_top_level(self):
        scores = [
            JudgeScores("1", Variant.FULL, 4, 4, 4, [], ""),
            JudgeScores("2", Variant.FULL, 5, 5, 5, [], ""),
        ]
        results = [
            VariantResult("1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("2", Variant.FULL, {}, "", None, {}, 150),
        ]
        complexity_map = {"1": True, "2": False}
        metrics = compute_quality_metrics(scores, results, complexity_map)
        assert "_judge_degradation" in metrics
        assert "degraded" in metrics["_judge_degradation"]

    def test_empty_complexity_map_treated_as_flat(self):
        scores = [
            JudgeScores("1", Variant.FULL, 4, 4, 4, [], ""),
        ]
        results = [
            VariantResult("1", Variant.FULL, {}, "", None, {}, 100),
        ]
        metrics = compute_quality_metrics(scores, results, {})
        assert "full" in metrics
        assert "_comparison" in metrics


class TestMakeArchitectureConfig:
    def test_default_config_structure(self):
        config = make_architecture_config()
        assert config.group_name == "architecture"
        assert Variant.FULL in config.variants
        assert Variant.SINGLE_LLM in config.variants

    def test_scenario_filter_always_true(self):
        from experiments.ablation.types import Scenario

        dummy = Scenario(
            id="test",
            driving_context={},
            user_query="",
            expected_decision={},
            expected_task_type="",
            safety_relevant=False,
            scenario_type="",
        )
        config = make_architecture_config()
        assert config.scenario_filter(dummy) is True

    def test_metrics_computer_flat_without_map(self):
        config = make_architecture_config()
        scores = [
            JudgeScores("1", Variant.FULL, 4, 4, 4, [], ""),
            JudgeScores("1", Variant.SINGLE_LLM, 3, 3, 3, [], ""),
        ]
        results = [
            VariantResult("1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("1", Variant.SINGLE_LLM, {}, "", None, {}, 50),
        ]
        metrics = config.metrics_computer(scores, results)
        assert "full" in metrics
        assert "_comparison" in metrics

    def test_metrics_computer_with_map(self):
        config = make_architecture_config({"1": True})
        scores = [
            JudgeScores("1", Variant.FULL, 4, 4, 4, [], ""),
            JudgeScores("1", Variant.SINGLE_LLM, 3, 3, 3, [], ""),
        ]
        results = [
            VariantResult("1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("1", Variant.SINGLE_LLM, {}, "", None, {}, 50),
        ]
        metrics = config.metrics_computer(scores, results)
        assert "complex" in metrics
        assert "comparison_complex" in metrics
