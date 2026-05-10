"""MemoryBank 可观测性指标收集，低开销（仅计数/累加）。"""

from collections import deque
from dataclasses import dataclass, field
from typing import Any


def _p50(values: list[float] | deque) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def _p90(values: list[float] | deque) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = (len(s) * 9) // 10
    return s[min(idx, len(s) - 1)]


@dataclass
class MemoryBankMetrics:
    """MemoryBank 可观测性指标，低开销计数与延迟采样。"""

    search_count: int = 0
    search_empty_index_count: int = 0  # 索引为空
    search_empty_count: int = 0  # 结果为空（含过滤后空）
    search_latency_ms: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    forget_count: int = 0
    forget_removed_count: int = 0
    write_count: int = 0
    write_latency_ms: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    embedding_latency_ms: deque[float] = field(
        default_factory=lambda: deque(maxlen=1000)
    )
    background_task_failures: int = 0
    index_load_warnings: deque[str] = field(default_factory=lambda: deque(maxlen=100))

    def snapshot(self) -> dict[str, Any]:
        """返回当前指标快照。"""
        return {
            "search_count": self.search_count,
            "search_empty_ratio": (
                self.search_empty_count / self.search_count
                if self.search_count > 0
                else 0.0
            ),
            "search_empty_index_count": self.search_empty_index_count,
            "search_latency_p50_ms": _p50(self.search_latency_ms),
            "search_latency_p90_ms": _p90(self.search_latency_ms),
            "forget_count": self.forget_count,
            "forget_removed_count": self.forget_removed_count,
            "write_count": self.write_count,
            "write_latency_p50_ms": _p50(self.write_latency_ms),
            "write_latency_p90_ms": _p90(self.write_latency_ms),
            "embedding_latency_p50_ms": _p50(self.embedding_latency_ms),
            "embedding_latency_p90_ms": _p90(self.embedding_latency_ms),
            "background_task_failures": self.background_task_failures,
            "index_load_warnings": list(self.index_load_warnings),
        }

    def reset(self) -> None:
        """重置所有指标。"""
        self.search_count = 0
        self.search_empty_count = 0
        self.search_empty_index_count = 0
        self.search_latency_ms.clear()
        self.forget_count = 0
        self.forget_removed_count = 0
        self.write_count = 0
        self.write_latency_ms.clear()
        self.embedding_latency_ms.clear()
        self.background_task_failures = 0
        self.index_load_warnings.clear()
