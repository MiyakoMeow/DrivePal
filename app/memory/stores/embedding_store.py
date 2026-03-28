"""向量相似度检索 store."""

from typing import Optional, TYPE_CHECKING

from app.memory.schemas import SearchResult
from app.memory.stores.base import BaseMemoryStore
from app.memory.utils import cosine_similarity

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel


class EmbeddingMemoryStore(BaseMemoryStore):
    """向量相似度检索 store."""

    requires_embedding: bool = True
    SIMILARITY_THRESHOLD = 0.4

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

    def search(
        self, query: str, top_k: int = 10, min_results: int = 1
    ) -> list[SearchResult]:
        """使用向量相似度进行记忆检索."""
        events = self.events_store.read()
        if not events:
            return []

        results = []
        if self.embedding_model:
            query_vector = self.embedding_model.encode(query)
            event_texts = [event.get("content", "") for event in events]
            all_embeddings = self.embedding_model.batch_encode(event_texts)

            seen_ids = set()
            scored = []
            for event, emb in zip(events, all_embeddings):
                sim = cosine_similarity(query_vector, emb)
                if sim > self.SIMILARITY_THRESHOLD:
                    scored.append((sim, event))

            scored.sort(key=lambda x: x[0], reverse=True)
            for sim, event in scored[:top_k]:
                seen_ids.add(event.get("id", ""))
                results.append(SearchResult(event=dict(event), score=sim))

            if len(results) < min_results:
                keyword_results = self._keyword_search(query, events)
                for event in keyword_results:
                    if event.get("id", "") not in seen_ids and len(results) < top_k:
                        seen_ids.add(event.get("id", ""))
                        results.append(SearchResult(event=dict(event), score=0.0))
        else:
            matched = self._keyword_search(query, events)
            results = [SearchResult(event=dict(e)) for e in matched[:top_k]]

        return results[:top_k]
