"""向量相似度检索 store."""

from typing import Optional, TYPE_CHECKING

from app.memory.schemas import SearchResult
from app.memory.stores.base import BaseMemoryStore
from app.memory.utils import cosine_similarity

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel


class EmbeddingMemoryStore(BaseMemoryStore):
    requires_embedding: bool = True

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model=None,
    ):
        super().__init__(data_dir)
        self.embedding_model = embedding_model

    @property
    def store_name(self) -> str:
        return "embeddings"

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        if self.embedding_model is None:
            return super().search(query, top_k=top_k)

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
