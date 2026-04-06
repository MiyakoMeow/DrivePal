"""结合嵌入向量和LLM的记忆库适配器."""

from vendor.VehicleMemBenchAdapter.memory_adapters.common import (
    StoreClient,
    history_to_interaction_records,
)
from vendor.VehicleMemBenchAdapter.model_config import (
    get_store_chat_model,
    get_store_embedding_model,
)
from app.memory.stores.memory_bank import MemoryBankStore
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.memory.interfaces import MemoryStore
    from pathlib import Path


class MemoryBankAdapter:
    """结合嵌入向量和LLM进行记忆搜索的适配器."""

    TAG = "memory_bank"

    def __init__(self, data_dir: Path) -> None:
        """使用数据目录初始化."""
        self.data_dir = data_dir

    async def add(self, history_text: str) -> MemoryBankStore:
        """将历史文本添加到记忆库存储."""
        chat_model = get_store_chat_model()
        embedding_model = get_store_embedding_model()
        store = MemoryBankStore(
            data_dir=self.data_dir,
            chat_model=chat_model,
            embedding_model=embedding_model,
        )
        for record in history_to_interaction_records(history_text):
            await store.write(record)
        return store

    def get_search_client(self, store: MemoryStore) -> StoreClient:
        """获取存储的搜索客户端."""
        return StoreClient(store)
