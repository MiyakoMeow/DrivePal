"""不同存储策略的记忆适配器实现."""

from .memory_bank_adapter import (
    MemoryBankAdapter,
)

ADAPTERS = {
    "memory_bank": MemoryBankAdapter,
}
