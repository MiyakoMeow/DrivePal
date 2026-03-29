"""基于嵌入向量的记忆适配器."""

from adapters.memory_adapters.common import StoreClient, history_to_interaction_records
from adapters.model_config import get_store_embedding_model
from app.memory.stores.embedding_store import EmbeddingMemoryStore


class EmbeddingsAdapter:
    """使用嵌入向量进行语义搜索的适配器."""

    TAG = "embeddings"

    def __init__(self, data_dir: str):
        """使用数据目录初始化."""
        self.data_dir = data_dir

    def add(self, history_text: str) -> EmbeddingMemoryStore:
        """将历史文本添加到嵌入向量存储."""
        embedding_model = get_store_embedding_model()
        store = EmbeddingMemoryStore(
            data_dir=self.data_dir, embedding_model=embedding_model
        )
        for record in history_to_interaction_records(history_text):
            store.write(record)
        return store

    def get_search_client(self, store) -> StoreClient:
        """获取存储的搜索客户端."""
        return StoreClient(store)

    def init_state(self):
        """初始化状态（此适配器无需操作）."""
        return None

    def close_state(self, state):
        """关闭状态（此适配器无需操作）."""
        pass
