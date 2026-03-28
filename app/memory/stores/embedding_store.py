"""向量相似度检索 store."""

import math
from datetime import date
from typing import Optional, TYPE_CHECKING

from app.memory.schemas import SearchResult
from app.memory.stores.base import BaseMemoryStore
from app.memory.utils import cosine_similarity

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel


def forgetting_curve(days_elapsed: int, strength: int) -> float:
    """根据艾宾浩斯遗忘曲线计算记忆保留率."""
    if days_elapsed <= 0:
        return 1.0
    return math.exp(-days_elapsed / (5 * strength))


class EmbeddingMemoryStore(BaseMemoryStore):
    """向量相似度检索 store."""

    requires_embedding: bool = True

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model=None,
    ) -> None:
        """初始化向量检索 store."""
        super().__init__(data_dir)
        self.embedding_model = embedding_model

    @property
    def store_name(self) -> str:
        """返回存储名称."""
        return "embeddings"

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """使用向量相似度进行记忆检索."""
        if self.embedding_model is None:
            return self._search_by_keyword(query, top_k)

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
                results.append(SearchResult(event=dict(event), score=similarity))

        return results[:top_k]

    def _search_by_keyword(self, query: str, top_k: int) -> list[SearchResult]:
        """基于关键词匹配检索记忆事件，应用遗忘曲线评分."""
        query_lower = query.lower()
        today = date.today()
        results = []
        events = self.events_store.read()
        for event in events:
            content = event.get("content", "").lower()
            description = event.get("description", "").lower()
            if query_lower in content or query_lower in description:
                strength = event.get("memory_strength", 1)
                last_recall = event.get("last_recall_date", today.isoformat())
                try:
                    last_date = date.fromisoformat(last_recall)
                    days_elapsed = (today - last_date).days
                except (ValueError, TypeError):
                    days_elapsed = 0
                retention = forgetting_curve(days_elapsed, strength)
                results.append(SearchResult(event=dict(event), score=retention))
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]
