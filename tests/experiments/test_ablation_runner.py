"""ablation_runner SingleLLM 规则引擎测试."""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.probabilistic import (
    get_probabilistic_enabled,
    set_probabilistic_enabled,
)
from app.agents.rules import get_ablation_disable_rules, set_ablation_disable_rules
from experiments.ablation.ablation_runner import AblationRunner
from experiments.ablation.types import Scenario, Variant, VariantResult


@pytest.fixture
def highway_scenario() -> Scenario:
    """高速场景——规则引擎应约束 channel 为 audio。"""
    return Scenario(
        id="highway_0.1_low_meeting_true",
        driving_context={
            "scenario": "highway",
            "driver": {"fatigue_level": 0.1, "workload": "low"},
        },
        user_query="提醒我3点开会",
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


class TestSingleLLMRulesPostprocess:
    """SingleLLM 输出应经 postprocess_decision 处理。"""

    async def test_highway_decision_gets_rules_applied(self, highway_scenario):
        """高速场景下 SingleLLM 的 decision 应被规则引擎修改。"""
        runner = AblationRunner(base_user_id="test")

        mock_chat = AsyncMock()
        mock_chat.generate.return_value = (
            '{"context": {}, "task": {"type": "meeting"}, '
            '"decision": {"should_remind": true, "timing": "now", '
            '"reminder_content": {"speakable_text": "3点开会"}, '
            '"allowed_channels": ["visual"], "reason": "test"}}'
        )

        with (
            patch(
                "experiments.ablation.ablation_runner.get_chat_model",
                return_value=mock_chat,
            ),
        ):
            result = await runner.run_variant(
                highway_scenario, Variant.SINGLE_LLM, user_id="test-single-llm"
            )

        assert result.modifications, "SingleLLM 在高速场景下应有规则引擎修改记录"


async def test_no_safety_disables_both() -> None:
    """NO_SAFETY 变体应同时禁用 rules 和 probabilistic."""
    orig_rules = get_ablation_disable_rules()
    orig_prob = get_probabilistic_enabled()

    try:
        set_ablation_disable_rules(False)
        set_probabilistic_enabled(True)
        runner = AblationRunner(base_user_id="test-no-safety")

        scenario = Scenario(
            id="test_no_safety",
            driving_context={"driver": {"fatigue_level": 0.9}, "scenario": "highway"},
            user_query="测试",
            expected_decision={},
            expected_task_type="other",
            safety_relevant=True,
            scenario_type="highway",
            synthesis_dims={
                "scenario": "highway",
                "fatigue_level": 0.9,
                "workload": "overloaded",
                "task_type": "other",
                "has_passengers": "false",
            },
        )

        # 用 spy 在 _run_agent_workflow 内检查 ContextVar——不执行真实逻辑
        async def spy(
            scenario: Scenario,
            variant: Variant,
            user_id: str,
            t0: float,
        ) -> VariantResult:
            assert get_ablation_disable_rules() is True
            assert get_probabilistic_enabled() is False
            return VariantResult(
                scenario_id=scenario.id,
                variant=Variant.NO_SAFETY,
                decision={},
                result_text="",
                event_id=None,
                stages={},
                latency_ms=t0,
            )

        with patch.object(runner, "_run_agent_workflow", spy):
            await runner.run_variant(scenario, Variant.NO_SAFETY)
    finally:
        set_ablation_disable_rules(orig_rules)
        set_probabilistic_enabled(orig_prob)
