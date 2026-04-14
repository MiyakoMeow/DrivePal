"""策略模块测试."""

import pytest

from benchmark.VehicleMemBench import BenchMemoryMode
from benchmark.VehicleMemBench.strategies import STRATEGIES


def test_strategies_registry_has_all_modes() -> None:
    """测试注册表包含所有记忆模式."""
    assert set(STRATEGIES.keys()) == set(BenchMemoryMode)


@pytest.mark.parametrize(
    ("mode", "expected_needs_history", "expected_needs_agent"),
    [
        (BenchMemoryMode.NONE, False, False),
        (BenchMemoryMode.GOLD, False, False),
        (BenchMemoryMode.KEY_VALUE, True, True),
        (BenchMemoryMode.SUMMARY, True, True),
        (BenchMemoryMode.MEMORY_BANK, True, False),
    ],
)
def test_strategy_properties(
    mode: BenchMemoryMode,
    expected_needs_history: bool,  # noqa: FBT001
    expected_needs_agent: bool,  # noqa: FBT001
) -> None:
    """测试每个策略的属性."""
    strategy = STRATEGIES[mode]
    assert strategy.mode == mode
    assert strategy.needs_history() == expected_needs_history
    assert strategy.needs_agent_for_prep() == expected_needs_agent
