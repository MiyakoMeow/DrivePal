"""测试公共编排协议."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from experiments.ablation.protocol import GroupConfig, run_group
from experiments.ablation.types import (
    BatchResult,
    GroupResult,
    JudgeScores,
    Scenario,
    Variant,
    VariantResult,
)


def _make_scenario(sid: str, safety: bool = True) -> Scenario:
    return Scenario(
        id=sid,
        driving_context={},
        user_query="test",
        expected_decision={},
        expected_task_type="meeting",
        safety_relevant=safety,
        scenario_type="city_driving",
    )


@pytest.fixture
def mock_runner():
    runner = MagicMock()
    batch = BatchResult(
        results=[
            VariantResult("s1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("s1", Variant.NO_RULES, {}, "", None, {}, 100),
        ],
        expected=2,
    )
    runner.run_batch = AsyncMock(return_value=batch)
    return runner


@pytest.fixture
def mock_judge():
    judge = MagicMock()
    judge.score_batch = AsyncMock(
        return_value=[
            JudgeScores("s1", Variant.FULL, 5, 5, 5, [], "ok"),
            JudgeScores("s1", Variant.NO_RULES, 3, 3, 3, [], "ok"),
        ]
    )
    return judge


async def test_run_group_filters_scenarios(mock_runner, mock_judge, tmp_path):
    """给定场景过滤器，当 run_group，则仅传入过滤后的场景."""
    scenarios = [_make_scenario("s1", safety=True), _make_scenario("s2", safety=False)]
    config = GroupConfig(
        group_name="safety",
        variants=[Variant.FULL, Variant.NO_RULES],
        scenario_filter=lambda s: s.safety_relevant,
        metrics_computer=lambda _scores, _results: {},
    )
    output = tmp_path / "results.jsonl"
    result = await run_group(mock_runner, mock_judge, scenarios, config, output)

    assert result.group == "safety"
    assert result.batch_stats["expected"] == 2
    called_scenarios = mock_runner.run_batch.call_args[0][0]
    assert len(called_scenarios) == 1
    assert called_scenarios[0].id == "s1"


async def test_run_group_with_post_hook(mock_runner, mock_judge, tmp_path):
    """给定 post_hook，当 run_group，则 post_hook 被调用并可修改 GroupResult."""

    async def add_tag(gr: GroupResult, _judge, _scenarios) -> GroupResult:
        gr.metrics["tagged"] = True
        return gr

    scenarios = [_make_scenario("s1")]
    config = GroupConfig(
        group_name="test",
        variants=[Variant.FULL],
        scenario_filter=lambda _s: True,
        metrics_computer=lambda _scores, _results: {},
        post_hook=add_tag,
    )
    result = await run_group(
        mock_runner, mock_judge, scenarios, config, tmp_path / "results.jsonl"
    )
    assert result.metrics["tagged"] is True
