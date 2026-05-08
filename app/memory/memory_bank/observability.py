"""MemoryBank 可观测性指标收集，零性能开销（仅计数/累加）。"""

from dataclasses import dataclass, field
from typing import Any


def _p50(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return s[mid]


def _p90(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = (len(s) * 9) // 10
    return s[min(idx, len(s) - 1)]


@dataclass
class MemoryBankMetrics:
    search_count: int = 0
    search_empty_count: int = 0
    search_latency_ms: list[float] = field(default_factory=list)
    embedding_latency_ms: list[float] = field(default_factory=list)
    forget_count: int = 0
    forget_removed_count: int = 0
    background_task_failures: int = 0
    index_load_warnings: list[str] = field(default_factory=list)
    store_instance_count: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "search_count": self.search_count,
            "search_empty_ratio": (
                self.search_empty_count / self.search_count
                if self.search_count > 0
                else 0
            ),
            "search_latency_p50_ms": _p50(self.search_latency_ms),
            "search_latency_p90_ms": _p90(self.search_latency_ms),
            "forget_count": self.forget_count,
            "forget_removed_count": self.forget_removed_count,
            "background_task_failures": self.background_task_failures,
            "index_load_warnings": self.index_load_warnings[-10:],
            "store_instance_count": self.store_instance_count,
        }

    def reset(self) -> None:
        self.search_count = 0
        self.search_empty_count = 0
        self.forget_count = 0
        self.forget_removed_count = 0
        self.background_task_failures = 0
        self.index_load_warnings.clear()
