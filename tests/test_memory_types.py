"""MemoryMode 枚举测试."""

from app.memory.types import MemoryMode


def test_str_enum_compat():
    assert MemoryMode.KEYWORD == "keyword"
    assert MemoryMode.KEYWORD in ["keyword", "llm_only"]


def test_all_values():
    assert set(MemoryMode) == {
        MemoryMode.KEYWORD,
        MemoryMode.LLM_ONLY,
        MemoryMode.EMBEDDINGS,
        MemoryMode.MEMORY_BANK,
    }
