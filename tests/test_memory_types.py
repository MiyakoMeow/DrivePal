"""MemoryMode 枚举测试."""

from app.memory.types import MemoryMode


def test_str_enum_compat() -> None:
    """验证 StrEnum 与 str 的隐式兼容性."""
    assert MemoryMode.MEMORY_BANK == "memory_bank"
    assert MemoryMode.MEMORY_BANK in ["memory_bank"]


def test_all_values() -> None:
    """验证枚举只包含 memory_bank 模式."""
    assert set(MemoryMode) == {MemoryMode.MEMORY_BANK}
