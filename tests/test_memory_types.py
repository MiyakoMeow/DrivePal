"""MemoryMode 枚举测试."""

from app.memory.types import MemoryMode


def test_str_enum_compat() -> None:
    """验证 MemoryMode 枚举与字符串兼容."""
    assert MemoryMode.MEMORY_BANK == "memory_bank"
    assert MemoryMode.MEMORY_BANK in ["memory_bank"]


def test_all_values() -> None:
    """验证 MemoryMode 包含所有枚举值."""
    assert set(MemoryMode) == {MemoryMode.MEMORY_BANK}
