"""不同存储策略的记忆适配器实现."""

from adapters.memory_adapters.common import MemoryType
from adapters.memory_adapters.gold_adapter import GoldAdapter
from adapters.memory_adapters.kv_adapter import KVAdapter
from adapters.memory_adapters.memory_bank_adapter import MemoryBankAdapter
from adapters.memory_adapters.none_adapter import NoneAdapter
from adapters.memory_adapters.summary_adapter import SummaryAdapter

ADAPTERS: dict[MemoryType, type] = {
    MemoryType.MEMORY_BANK: MemoryBankAdapter,
    MemoryType.NONE: NoneAdapter,
    MemoryType.GOLD: GoldAdapter,
    MemoryType.SUMMARY: SummaryAdapter,
    MemoryType.KV: KVAdapter,
}
