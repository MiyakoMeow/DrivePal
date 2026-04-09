"""VehicleMemBench 适配器模块."""

from enum import StrEnum


class BenchMemoryMode(StrEnum):
    """基准测试记忆模式."""

    NONE = "none"
    GOLD = "gold"
    KV = "kv"
    MEMORY_BANK = "memory_bank"
