"""MemoChat 检索模式定义."""

from enum import StrEnum


class RetrievalMode(StrEnum):
    """检索模式枚举."""

    FULL_LLM = "full_llm"
    HYBRID = "hybrid"
