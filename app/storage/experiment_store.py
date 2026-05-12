"""实验基准数据只读存储."""

import tomllib
from typing import Any

from app.config import DATA_ROOT

_BENCHMARK_FILE = DATA_ROOT / "experiment_benchmark.toml"


def read_benchmark() -> dict[str, Any]:
    """读取 experiment_benchmark.toml，不存在返回空 dict."""
    if not _BENCHMARK_FILE.exists():
        return {}
    with _BENCHMARK_FILE.open("rb") as f:
        return tomllib.load(f)
