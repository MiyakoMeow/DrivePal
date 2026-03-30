"""仅使用LLM的记忆适配器."""

from adapters.memory_adapters.common import StoreClient, history_to_interaction_records
from adapters.model_config import get_store_chat_model
from app.memory.interfaces import MemoryStore
from app.memory.stores.llm_store import LLMOnlyMemoryStore


class LLMOnlyAdapter:
    """使用LLM判断相关性的适配器."""

    TAG = "llm_only"

    def __init__(self, data_dir: str) -> None:
        """使用数据目录初始化."""
        self.data_dir = data_dir

    def add(self, history_text: str) -> LLMOnlyMemoryStore:
        """将历史文本添加到LLM存储."""
        chat_model = get_store_chat_model()
        store = LLMOnlyMemoryStore(data_dir=self.data_dir, chat_model=chat_model)
        for record in history_to_interaction_records(history_text):
            store.write(record)
        return store

    def get_search_client(self, store: MemoryStore) -> StoreClient:
        """获取存储的搜索客户端."""
        return StoreClient(store)
