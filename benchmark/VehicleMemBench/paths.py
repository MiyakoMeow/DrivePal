"""路径常量与 sys.path 初始化."""

import sys
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from benchmark.VehicleMemBench import BenchMemoryMode

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VENDOR_DIR = PROJECT_ROOT / "vendor" / "VehicleMemBench"
BENCHMARK_DIR = VENDOR_DIR / "benchmark"
OUTPUT_DIR = PROJECT_ROOT / "data" / "benchmark"


@lru_cache(maxsize=1)
def setup_vehiclemembench_path() -> None:
    """将 VehicleMemBench 路径添加到 sys.path（幂等操作）."""
    for d in [VENDOR_DIR, VENDOR_DIR / "evaluation"]:
        d_str = str(d)
        if not any(Path(p).resolve() == Path(d_str).resolve() for p in sys.path):
            sys.path.insert(0, d_str)


setup_vehiclemembench_path()


def ensure_output_dir() -> Path:
    """确保输出目录存在并返回路径."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def file_output_dir(memory_type: BenchMemoryMode, file_num: int) -> Path:
    """返回指定记忆类型和文件编号的输出目录路径."""
    return OUTPUT_DIR / memory_type / f"file_{file_num}"


def prep_path(memory_type: BenchMemoryMode, file_num: int) -> Path:
    """返回指定记忆类型和文件编号的 prep 数据路径."""
    return file_output_dir(memory_type, file_num) / "prep.json"


def query_result_path(
    memory_type: BenchMemoryMode, file_num: int, event_index: int
) -> Path:
    """返回指定记忆类型、文件编号和事件索引的查询结果路径."""
    return file_output_dir(memory_type, file_num) / f"query_{event_index}.json"
