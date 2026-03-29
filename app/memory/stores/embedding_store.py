"""向量相似度检索 store."""

from typing import Optional, TYPE_CHECKING

from app.memory.components import (
    EventStorage,
    FeedbackManager,
    SimpleInteractionWriter,
)
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.memory.utils import cosine_similarity
from app.storage.json_store import JSONStore

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel


class EmbeddingMemoryStore:
    """向量相似度检索 store."""

    store_name = "embeddings"
    requires_embedding = True
    requires_chat = False
    supports_interaction = True
    SIMILARITY_THRESHOLD = 0.4

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model=None,
        **kwargs,
    ) -> None:
        """初始化向量存储."""
        self._storage = EventStorage(data_dir)
        self._feedback = FeedbackManager(data_dir)
        self._interaction = SimpleInteractionWriter(self._storage)
        self.embedding_model = embedding_model

    @property
    def events_store(self) -> JSONStore:
        """事件存储."""
        return self._storage._store

    @property
    def strategies_store(self) -> JSONStore:
        """策略存储."""
        return self._feedback._strategies_store

    def write(self, event: MemoryEvent) -> str:
        """写入事件."""
        return self._storage.append_event(event)

    def search(
        self, query: str, top_k: int = 10, min_results: int = 1
    ) -> list[SearchResult]:
        """向量相似度搜索."""
        events = self._storage.read_events()
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
                keyword_results = self._keyword_fallback(query, events)
                for event in keyword_results:
                    if event.get("id", "") not in seen_ids and len(results) < top_k:
                        seen_ids.add(event.get("id", ""))
                        results.append(SearchResult(event=dict(event), score=0.0))
        else:
            keyword_results = self._keyword_fallback(query, events)
            results = [SearchResult(event=dict(e)) for e in keyword_results[:top_k]]

        return results[:top_k]

    def _keyword_fallback(self, query: str, events: list[dict]) -> list[dict]:
        query_lower = query.lower()
        return [
            e
            for e in events
            if query_lower in e.get("content", "").lower()
            or query_lower in e.get("description", "").lower()
        ]

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取历史事件."""
        events = self._storage.read_events()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """更新反馈."""
        self._feedback.update_feedback(event_id, feedback)

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录."""
        return self._interaction.write_interaction(query, response, event_type)
