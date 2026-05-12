"""实验基准存储测试."""

import pytest
import tomli_w


def test_read_benchmark_empty(tmp_path, monkeypatch):
    """文件不存在时返回空 dict."""
    monkeypatch.setattr(
        "app.storage.experiment_store._BENCHMARK_FILE",
        tmp_path / "nonexistent.toml",
    )
    from app.storage.experiment_store import read_benchmark

    assert read_benchmark() == {}


def test_read_benchmark_parses(tmp_path, monkeypatch):
    """读取五策略对比数据."""
    data = {
        "strategies": {
            "memory_bank": {"exact_match": 0.5, "field_f1": 0.7, "value_f1": 0.6},
            "none": {"exact_match": 0.0, "field_f1": 0.0, "value_f1": 0.0},
        }
    }
    fp = tmp_path / "experiment_benchmark.toml"
    with fp.open("wb") as f:
        tomli_w.dump(data, f)
    monkeypatch.setattr("app.storage.experiment_store._BENCHMARK_FILE", fp)
    from app.storage.experiment_store import read_benchmark

    result = read_benchmark()
    assert result["strategies"]["memory_bank"]["exact_match"] == 0.5
    assert result["strategies"]["none"]["field_f1"] == 0.0
