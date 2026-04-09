"""不同存储策略的记忆适配器实现."""

from app.memory.types import MemoryMode

from .memory_bank_adapter import (
    MemoryBankAdapter,
)

ADAPTERS: dict[MemoryMode, type] = {
    MemoryMode.MEMORY_BANK: MemoryBankAdapter,
}
