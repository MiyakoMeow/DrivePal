"""向量相似度检索 store."""

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from app.memory.stores.base import BaseMemoryStore
from app.memory.utils import cosine_similarity

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel


class EmbeddingMemoryStore(BaseMemoryStore):
    """向量相似度检索 store."""

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model=None,
    ):
        """初始化 EmbeddingMemoryStore.

        Args:
            data_dir: 数据存储目录
            embedding_model: 向量嵌入模型
            chat_model: 聊天模型

        """
        super().__init__(data_dir)
        self.embedding_model = embedding_model

    @property
    def store_name(self) -> str:
        """返回 store 名称."""
        return "embeddings"

    def write(self, event: dict) -> str:
        """写入事件到 store.

        Args:
            event: 事件数据字典

        Returns:
            事件 ID

        """
        event = dict(event)
        event_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        event["id"] = event_id
        event["created_at"] = datetime.now().isoformat()
        self.events_store.append(event)
        return event_id

    def search(self, query: str) -> list[dict]:
        """使用向量相似度搜索事件.

        Args:
            query: 搜索查询字符串

        Returns:
            相似度超过阈值的事件列表

        """
        if self.embedding_model is None:
            return self._keyword_fallback(query)

        query_vector = self.embedding_model.encode(query)
        events = self.events_store.read()
        if not events:
            return []

        event_texts = [event.get("content", "") for event in events]
        all_embeddings = self.embedding_model.batch_encode(event_texts)

        results = []
        for event, event_vector in zip(events, all_embeddings):
            similarity = cosine_similarity(query_vector, event_vector)
            if similarity > 0.7:
                results.append(event)

        return results

    def _keyword_fallback(self, query: str) -> list[dict]:
        query_lower = query.lower()
        events = self.events_store.read()
        return [
            event for event in events if query_lower in event.get("content", "").lower()
        ]
