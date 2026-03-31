"""不同存储策略的记忆适配器实现."""

from adapters.memory_adapters.common import VMBMode
from adapters.memory_adapters.gold_adapter import GoldAdapter
from adapters.memory_adapters.kv_adapter import KVAdapter
from adapters.memory_adapters.memory_bank_adapter import MemoryBankAdapter
from adapters.memory_adapters.none_adapter import NoneAdapter
from adapters.memory_adapters.summary_adapter import SummaryAdapter

ADAPTERS: dict[VMBMode, type] = {
    VMBMode.MEMORY_BANK: MemoryBankAdapter,
    VMBMode.NONE: NoneAdapter,
    VMBMode.GOLD: GoldAdapter,
    VMBMode.SUMMARY: SummaryAdapter,
    VMBMode.KV: KVAdapter,
}
