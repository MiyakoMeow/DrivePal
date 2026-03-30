"""关键词匹配检索 store."""

from pathlib import Path

from app.memory.components import (
    EventStorage,
    FeedbackManager,
    KeywordSearch,
    SimpleInteractionWriter,
)
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.storage.json_store import JSONStore


class KeywordMemoryStore:
    """关键词匹配检索 store."""

    store_name = "keyword"
    requires_embedding = False
    requires_chat = False
    supports_interaction = True

    def __init__(self, data_dir: Path, **kwargs: dict) -> None:
        """初始化关键词存储."""
        self._storage = EventStorage(data_dir)
        self._search = KeywordSearch()
        self._feedback = FeedbackManager(data_dir)
        self._interaction = SimpleInteractionWriter(self._storage)

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

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """关键词搜索."""
        events = self._storage.read_events()
        return self._search.search(query, events, top_k)

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
