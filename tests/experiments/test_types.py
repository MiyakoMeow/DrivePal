"""测试数据类型定义."""

from experiments.ablation.types import (
    BatchResult,
    GroupResult,
    JudgeScores,
    Scenario,
    Variant,
    VariantResult,
)


def test_variant_enum_values():
    assert Variant.FULL == "full"
    assert Variant.NO_RULES == "no-rules"
    assert Variant.NO_PROB == "no-prob"
    assert Variant.NO_SAFETY == "no-safety"
    assert Variant.SINGLE_LLM == "single-llm"
    assert Variant.NO_FEEDBACK == "no-feedback"


def test_scenario_creation():
    s = Scenario(
        id="test-1",
        driving_context={"scenario": "highway"},
        user_query="测试",
        expected_decision={"should_remind": True, "channel": "audio"},
        expected_task_type="meeting",
        safety_relevant=True,
        scenario_type="highway",
    )
    assert s.id == "test-1"
    assert s.safety_relevant


def test_variant_result_default_modifications():
    r = VariantResult(
        scenario_id="1",
        variant=Variant.FULL,
        decision={},
        result_text="",
        event_id=None,
        stages={},
        latency_ms=0.0,
    )
    assert r.modifications == []


def test_judge_scores_creation():
    js = JudgeScores(
        scenario_id="1",
        variant=Variant.FULL,
        safety_score=4,
        reasonableness_score=5,
        overall_score=4,
        violation_flags=[],
        explanation="合理",
    )
    assert js.safety_score == 4


class TestBatchResult:
    """批量运行结果."""

    def test_construction_with_defaults(self):
        """给定结果列表，当构造 BatchResult，则 failures 为 expected - actual."""
        results = [
            VariantResult("s1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("s2", Variant.FULL, {}, "", None, {}, 200),
        ]
        batch = BatchResult(results=results, expected=3)
        assert batch.actual == 2
        assert batch.failures == 1

    def test_all_succeeded(self):
        """给定 expected == actual，当构造 BatchResult，则 failures 为 0."""
        results = [
            VariantResult("s1", Variant.FULL, {}, "", None, {}, 100),
        ]
        batch = BatchResult(results=results, expected=1)
        assert batch.failures == 0


class TestGroupResultBatchStats:
    """GroupResult.batch_stats 字段."""

    def test_default_batch_stats_is_empty(self):
        """给定无 batch_stats，当构造 GroupResult，则 batch_stats 为空字典."""
        gr = GroupResult(
            group="test",
            variant_results=[],
            judge_scores=[],
            metrics={},
        )
        assert gr.batch_stats == {}
