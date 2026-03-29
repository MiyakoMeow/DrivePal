"""记忆库后端，基于遗忘曲线的记忆存储、聚合与摘要功能."""


from app.memory.components import EventStorage, FeedbackManager, MemoryBankEngine
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.storage.json_store import JSONStore


class MemoryBankStore:
    """记忆库后端，支持遗忘曲线、记忆强化与自动摘要."""

    store_name = "memorybank"
    requires_embedding = True
    requires_chat = True
    supports_interaction = True

    def __init__(
        self,
        data_dir: str,
        embedding_model=None,
        chat_model=None,
        **kwargs,
    ):
        self._storage = EventStorage(data_dir)
        self._engine = MemoryBankEngine(
            data_dir, self._storage, embedding_model, chat_model
        )
        self._feedback = FeedbackManager(data_dir)
        self.embedding_model = embedding_model
        self.chat_model = chat_model

    @property
    def events_store(self) -> JSONStore:
        return self._storage._store

    @property
    def strategies_store(self) -> JSONStore:
        return self._feedback._strategies_store

    @property
    def summaries_store(self) -> JSONStore:
        return self._engine._summaries_store

    @property
    def interactions_store(self) -> JSONStore:
        return self._engine._interactions_store

    def write(self, event: MemoryEvent) -> str:
        return self._engine.write(event)

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        return self._engine.search(query, top_k)

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        events = self._storage.read_events()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        self._feedback.update_feedback(event_id, feedback)

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        return self._engine.write_interaction(query, response, event_type)
