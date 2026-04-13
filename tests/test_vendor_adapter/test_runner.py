"""runner 模块测试."""

import asyncio
import importlib.util
import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

if TYPE_CHECKING:
    import pytest

from vendor_adapter.VehicleMemBench import BenchMemoryMode
from vendor_adapter.VehicleMemBench.runner import (
    BENCHMARK_DIR,
    OUTPUT_DIR,
    VENDOR_DIR,
    file_output_dir,
    parse_file_range,
    prep_path,
    prepare,
    query_result_path,
    report,
    run,
    setup_vehiclemembench_path,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_setup_vehiclemembench_path() -> None:
    """测试 setup_vehiclemembench_path 将 vendor 添加到 sys.path."""
    setup_vehiclemembench_path()

    spec = importlib.util.find_spec("environment.vehicleworld")
    assert spec is not None


def test_parse_file_range() -> None:
    """测试解析文件范围字符串."""
    assert parse_file_range("1-5") == [1, 2, 3, 4, 5]
    assert parse_file_range("1,3,5") == [1, 3, 5]
    assert parse_file_range("1-3,7") == [1, 2, 3, 7]


def test_parse_file_range_dedup_and_sort() -> None:
    """测试 parse_file_range 去重和排序结果."""
    assert parse_file_range("5,3,3,1") == [1, 3, 5]
    assert parse_file_range("3-1") == [1, 2, 3]


def test_paths_exist() -> None:
    """测试 vendor 路径存在."""
    assert VENDOR_DIR.exists()
    assert (BENCHMARK_DIR / "qa_data").exists()
    assert OUTPUT_DIR.name == "benchmark"


def test_file_output_dir() -> None:
    """测试 file_output_dir 生成正确的输出路径."""
    d = file_output_dir(BenchMemoryMode.MEMORY_BANK, 3)
    assert d == OUTPUT_DIR / "memory_bank" / "file_3"


def test_prep_path() -> None:
    """测试 prep_path 生成正确的 prep.json 路径."""
    p = prep_path(BenchMemoryMode.KV, 7)
    assert p == OUTPUT_DIR / "kv" / "file_7" / "prep.json"


def test_query_result_path() -> None:
    """测试 query_result_path 生成正确的查询结果路径."""
    p = query_result_path(BenchMemoryMode.KV, 12, 4)
    assert p == OUTPUT_DIR / "kv" / "file_12" / "query_4.json"


def test_prepare_gold_creates_dir_and_skips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 gold 类型 prepare 创建目录并支持重复调用."""
    monkeypatch.setattr("vendor_adapter.VehicleMemBench.paths.OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        "vendor_adapter.VehicleMemBench.runner._get_agent_client",
        MagicMock,
    )

    asyncio.run(prepare(file_range="1", memory_types="gold"))
    gold_dir = tmp_path / "gold" / "file_1"
    assert gold_dir.is_dir()

    asyncio.run(prepare(file_range="1", memory_types="gold"))
    assert gold_dir.is_dir()

    asyncio.run(prepare(file_range="1", memory_types="gold"))
    assert gold_dir.is_dir()


def test_prepare_none_creates_dir_and_skips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 none 类型 prepare 创建目录并支持重复调用."""
    monkeypatch.setattr("vendor_adapter.VehicleMemBench.paths.OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        "vendor_adapter.VehicleMemBench.runner._get_agent_client",
        MagicMock,
    )

    asyncio.run(prepare(file_range="1", memory_types="none"))
    none_dir = tmp_path / "none" / "file_1"
    assert none_dir.is_dir()

    asyncio.run(prepare(file_range="1", memory_types="none"))
    assert none_dir.is_dir()


def test_run_skips_existing_query_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 run 跳过已存在的查询文件."""
    monkeypatch.setattr("vendor_adapter.VehicleMemBench.paths.OUTPUT_DIR", tmp_path)

    mtype = BenchMemoryMode.GOLD
    fnum = 99
    fdir = tmp_path / mtype / f"file_{fnum}"
    fdir.mkdir(parents=True)

    events = [
        {
            "query": "q0",
            "new_answer": [],
            "reasoning_type": "simple",
            "gold_memory": "",
        },
        {
            "query": "q1",
            "new_answer": [],
            "reasoning_type": "simple",
            "gold_memory": "",
        },
    ]
    for i in range(len(events)):
        qp = query_result_path(mtype, fnum, i)
        qp.write_text(
            json.dumps({"query": f"q{i}", "exact_match": True}),
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "vendor_adapter.VehicleMemBench.loader.load_qa",
        AsyncMock(return_value={"related_to_vehicle_preference": events}),
    )
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(
        return_value={"query": "mocked", "exact_match": True}
    )
    mock_strategy = MagicMock()
    mock_strategy.create_evaluator = AsyncMock(return_value=mock_evaluator)
    monkeypatch.setitem(
        __import__(
            "vendor_adapter.VehicleMemBench.strategies",
            fromlist=["STRATEGIES"],
        ).STRATEGIES,
        mtype,
        mock_strategy,
    )
    monkeypatch.setattr(
        "vendor_adapter.VehicleMemBench.runner._get_agent_client",
        MagicMock,
    )

    asyncio.run(run(file_range="99", memory_types="gold"))

    mock_evaluator.evaluate.assert_not_called()


def test_report_reads_hierarchical_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 report 读取分层查询结果."""
    monkeypatch.setattr("vendor_adapter.VehicleMemBench.paths.OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        "vendor_adapter.VehicleMemBench.reporter.get_benchmark_config",
        type("Cfg", (), {"model": "test-model"}),
    )

    mb_dir = tmp_path / "memory_bank" / "file_1"
    mb_dir.mkdir(parents=True)
    q0 = mb_dir / "query_0.json"
    q0.write_text(
        json.dumps(
            {
                "query": "test",
                "reasoning_type": "simple",
                "pred_calls": [],
                "ref_calls": [],
                "state_score": {
                    "f1_positive": 1.0,
                    "f1_negative": 1.0,
                    "acc_positive": 1.0,
                    "precision_positive": 1.0,
                    "f1_change": 1.0,
                    "acc_negative": 1.0,
                    "precision_change": 1.0,
                    "change_accuracy": 1.0,
                    "differences": [],
                    "FP": 0,
                    "negative_FP": 0,
                },
                "exact_match": True,
                "skipped": False,
                "num_pred_calls": 0,
                "num_ref_calls": 0,
                "output_token": 10,
                "input_token": 50,
                "source_file": 1,
                "event_index": 0,
                "memory_type": "memory_bank",
            },
        ),
        encoding="utf-8",
    )

    report(output_path=tmp_path / "report.json")
    report_file = tmp_path / "report.json"
    assert report_file.exists()
    data = json.loads(report_file.read_text(encoding="utf-8"))
    assert "memory_bank" in data
    assert data["memory_bank"]["completed_tasks"] == 1


def test_imports_available() -> None:
    """测试 vendor 导入可用."""
