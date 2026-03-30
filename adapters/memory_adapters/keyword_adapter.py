"""基于关键词的记忆适配器."""

from adapters.memory_adapters.common import StoreClient, history_to_interaction_records
from app.memory.stores.keyword_store import KeywordMemoryStore


class KeywordAdapter:
    """使用基于关键词搜索的适配器."""

    TAG = "keyword"

    def __init__(self, data_dir: str):
        """使用数据目录初始化."""
        self.data_dir = data_dir

    def add(self, history_text: str) -> KeywordMemoryStore:
        """将历史文本添加到关键词存储."""
        store = KeywordMemoryStore(data_dir=self.data_dir)
        for record in history_to_interaction_records(history_text):
            store.write(record)
        return store

    def get_search_client(self, store) -> StoreClient:
        """获取存储的搜索客户端."""
        return StoreClient(store)
