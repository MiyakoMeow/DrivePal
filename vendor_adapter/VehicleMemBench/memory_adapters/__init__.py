"""不同存储策略的记忆适配器实现."""

from .. import BenchMemoryMode
from .memory_bank_adapter import MemoryBankAdapter

ADAPTERS: dict[BenchMemoryMode, type[MemoryBankAdapter]] = {
    BenchMemoryMode.MEMORY_BANK: MemoryBankAdapter,
}
