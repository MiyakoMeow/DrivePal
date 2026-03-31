"""不同存储策略的记忆适配器实现."""

from adapters.memory_adapters.gold_adapter import GoldAdapter
from adapters.memory_adapters.kv_adapter import KVAdapter
from adapters.memory_adapters.memory_bank_adapter import MemoryBankAdapter
from adapters.memory_adapters.none_adapter import NoneAdapter
from adapters.memory_adapters.summary_adapter import SummaryAdapter

ADAPTERS = {
    "memory_bank": MemoryBankAdapter,
    "none": NoneAdapter,
    "gold": GoldAdapter,
    "summary": SummaryAdapter,
    "kv": KVAdapter,
}
