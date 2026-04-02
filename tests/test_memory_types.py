"""MemoryMode 枚举测试."""

from app.memory.types import MemoryMode


def test_str_enum_compat() -> None:
    assert MemoryMode.MEMORY_BANK == "memory_bank"
    assert MemoryMode.MEMORY_BANK in ["memory_bank"]


def test_memochat_str_enum_compat() -> None:
    assert MemoryMode.MEMOCHAT == "memochat"
    assert MemoryMode.MEMOCHAT in ["memochat"]


def test_all_values() -> None:
    assert set(MemoryMode) == {MemoryMode.MEMORY_BANK, MemoryMode.MEMOCHAT}
