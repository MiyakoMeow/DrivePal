"""策略模块测试."""

import asyncio
import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from benchmark.VehicleMemBench import BenchMemoryMode
from benchmark.VehicleMemBench.strategies import STRATEGIES
from benchmark.VehicleMemBench.strategies.key_value import KeyValueMemoryStrategy
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


def test_key_value_prepare_calls_per_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """key_value prepare 应逐日调用 build_memory_kv_for_day，每次获取信号量."""
    strategy = KeyValueMemoryStrategy()
    semaphore = asyncio.Semaphore(2)
    agent_client = MagicMock()

    daily = {"2024-01-15": ["msg1"], "2024-01-16": ["msg2"]}

    call_log: list[str] = []
    mock_store = MagicMock()
    mock_store.to_dict.return_value = {}

    def fake_split(_text: str) -> dict[str, list[str]]:
        return daily

    def fake_build_kv_day(
        _client, date, _conversations, _memory_store, _reflect_num=10
    ):
        call_log.append(date)
        return [{"name": "mock", "args": {}, "result": {}}]

    monkeypatch.setattr(
        "benchmark.VehicleMemBench.strategies.key_value.split_history_by_day",
        fake_split,
    )
    monkeypatch.setattr(
        "benchmark.VehicleMemBench.strategies.key_value.build_memory_kv_for_day",
        fake_build_kv_day,
    )
    monkeypatch.setattr(
        "benchmark.VehicleMemBench.strategies.key_value.VMBMemoryStore",
        lambda: mock_store,
    )

    result = asyncio.run(strategy.prepare("history", tmp_path, agent_client, semaphore))

    assert call_log == ["2024-01-15", "2024-01-16"]
    assert result is not None
    assert result["type"] == BenchMemoryMode.KEY_VALUE


def test_summary_prepare_checkpoint_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Summary prepare 应能从 partial 文件恢复."""
    strategy = SummaryMemoryStrategy()
    semaphore = asyncio.Semaphore(2)
    agent_client = MagicMock()

    daily = {"2024-01-15": ["msg1"], "2024-01-16": ["msg2"], "2024-01-17": ["msg3"]}
    call_log: list[str] = []

    def fake_split(_text: str) -> dict[str, list[str]]:
        return daily

    def fake_summarize_day(_client, _date, _conversations, _previous_memory=""):  # type: ignore[misc]
        call_log.append(_date)
        return f"memory_{_date}", True, None

    monkeypatch.setattr(
        "benchmark.VehicleMemBench.strategies.summary.split_history_by_day",
        fake_split,
    )
    monkeypatch.setattr(
        "benchmark.VehicleMemBench.strategies.summary.summarize_day_with_previous_memory",
        fake_summarize_day,
    )

    partial_file = tmp_path / "prep.partial.json"
    partial_file.write_text(
        json.dumps(
            {
                "type": "summary",
                "memory": "memory_2024-01-15",
                "_processed_dates": ["2024-01-15"],
                "_daily_snapshots": {"2024-01-15": "memory_2024-01-15"},
            }
        ),
        encoding="utf-8",
    )

    result = asyncio.run(strategy.prepare("history", tmp_path, agent_client, semaphore))

    assert call_log == ["2024-01-16", "2024-01-17"]
    assert result is not None
    assert result["memory"] == "memory_2024-01-17"
    assert not partial_file.exists()


def test_key_value_prepare_checkpoint_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """key_value prepare 应能从 partial 文件恢复并重建 MemoryStore."""
    strategy = KeyValueMemoryStrategy()
    semaphore = asyncio.Semaphore(2)
    agent_client = MagicMock()

    daily = {"2024-01-15": ["msg1"], "2024-01-16": ["msg2"], "2024-01-17": ["msg3"]}
    call_log: list[str] = []
    mock_store = MagicMock()
    mock_store.to_dict.return_value = {"k1": "v1"}
    mock_store.store = {}

    def fake_split(_text: str) -> dict[str, list[str]]:
        return daily

    def fake_build_kv_day(
        _client, _date, _conversations, _memory_store, _reflect_num=10
    ):  # type: ignore[misc]
        call_log.append(_date)
        return []

    monkeypatch.setattr(
        "benchmark.VehicleMemBench.strategies.key_value.split_history_by_day",
        fake_split,
    )
    monkeypatch.setattr(
        "benchmark.VehicleMemBench.strategies.key_value.build_memory_kv_for_day",
        fake_build_kv_day,
    )
    monkeypatch.setattr(
        "benchmark.VehicleMemBench.strategies.key_value.VMBMemoryStore",
        lambda: mock_store,
    )

    partial_file = tmp_path / "prep.partial.json"
    partial_file.write_text(
        json.dumps(
            {
                "type": "key_value",
                "store": {"existing_key": "existing_val"},
                "_processed_dates": ["2024-01-15"],
                "_daily_snapshots": {"2024-01-15": "snapshot"},
            }
        ),
        encoding="utf-8",
    )

    result = asyncio.run(strategy.prepare("history", tmp_path, agent_client, semaphore))

    assert call_log == ["2024-01-16", "2024-01-17"]
    assert result is not None
    assert result["type"] == BenchMemoryMode.KEY_VALUE
    assert not partial_file.exists()
