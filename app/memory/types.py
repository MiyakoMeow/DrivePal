"""记忆模式枚举定义."""

from enum import StrEnum


class MemoryMode(StrEnum):
    """记忆检索模式."""

    MEMORY_BANK = "memory_bank"
    SUMMARY = "summary"
    KEY_VALUE = "key_value"
