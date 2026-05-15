"""实验基准数据只读存储。"""

import tomllib
from typing import Any

import aiofiles

from app.config import DATA_ROOT

_BENCHMARK_FILE = DATA_ROOT / "experiment_benchmark.toml"


async def read_benchmark() -> dict[str, Any]:
    """读取 experiment_benchmark.toml，不存在返回空 dict。"""
    if not _BENCHMARK_FILE.exists():
        return {}
    async with aiofiles.open(_BENCHMARK_FILE, "rb") as f:
        content = await f.read()
    return tomllib.loads(content.decode("utf-8"))
