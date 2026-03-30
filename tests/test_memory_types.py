"""MemoryMode 枚举测试."""

from app.memory.types import MemoryMode


def test_str_enum_compat() -> None:
    """验证 StrEnum 与 str 的隐式兼容性."""
    assert MemoryMode.KEYWORD == "keyword"
    assert MemoryMode.KEYWORD in ["keyword", "llm_only"]


def test_all_values() -> None:
    """验证枚举包含所有四种模式."""
    assert set(MemoryMode) == {
        MemoryMode.KEYWORD,
        MemoryMode.LLM_ONLY,
        MemoryMode.EMBEDDINGS,
        MemoryMode.MEMORY_BANK,
    }
