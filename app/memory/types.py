"""记忆模式枚举定义."""

from enum import StrEnum


class MemoryMode(StrEnum):
    """记忆检索模式."""

    KEYWORD = "keyword"
    LLM_ONLY = "llm_only"
    EMBEDDINGS = "embeddings"
    MEMORY_BANK = "memorybank"
