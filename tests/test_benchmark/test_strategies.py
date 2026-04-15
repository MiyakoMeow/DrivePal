"""策略模块测试."""

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from benchmark.VehicleMemBench import BenchMemoryMode
from benchmark.VehicleMemBench.strategies import STRATEGIES
from benchmark.VehicleMemBench.strategies.summary import SummaryMemoryStrategy

if TYPE_CHECKING:
    from pathlib import Path


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


def test_summary_prepare_calls_per_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Summary prepare 应逐日调用 summarize_day_with_previous_memory，每次获取信号量."""
    strategy = SummaryMemoryStrategy()
    semaphore = asyncio.Semaphore(2)
    agent_client = MagicMock()

    daily = {"2024-01-15": ["msg1"], "2024-01-16": ["msg2"]}

    call_log: list[str] = []

    def fake_split(_text: str) -> dict[str, list[str]]:
        return daily

    def fake_summarize_day(_client, date, _conversations, _previous_memory=""):
        call_log.append(date)
        return f"memory_after_{date}", date == "2024-01-16", None

    monkeypatch.setattr(
        "benchmark.VehicleMemBench.strategies.summary.split_history_by_day",
        fake_split,
    )
    monkeypatch.setattr(
        "benchmark.VehicleMemBench.strategies.summary.summarize_day_with_previous_memory",
        fake_summarize_day,
    )

    result = asyncio.run(strategy.prepare("history", tmp_path, agent_client, semaphore))

    assert call_log == ["2024-01-15", "2024-01-16"]
    assert result is not None
    assert result["type"] == BenchMemoryMode.SUMMARY
    assert result["memory"] == "memory_after_2024-01-16"
