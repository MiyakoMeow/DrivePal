"""测试数据类型定义."""

from experiments.ablation.types import (
    GroupResult,
    JudgeScores,
    TestScenario,
    Variant,
    VariantResult,
)


def test_variant_enum_values():
    assert Variant.FULL == "full"
    assert Variant.NO_RULES == "no-rules"
    assert Variant.NO_PROB == "no-prob"
    assert Variant.SINGLE_LLM == "single-llm"
    assert Variant.NO_FEEDBACK == "no-feedback"


def test_test_scenario_creation():
    s = TestScenario(
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
