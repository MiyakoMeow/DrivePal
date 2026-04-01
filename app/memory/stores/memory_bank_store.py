"""记忆库后端，基于遗忘曲线的记忆存储、聚合与摘要功能."""

from pathlib import Path
from typing import Optional, TYPE_CHECKING

from app.memory.components import EventStorage, FeedbackManager, MemoryBankEngine
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.storage.json_store import JSONStore

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel


class MemoryBankStore:
    """记忆库后端，支持遗忘曲线、记忆强化与自动摘要."""

    store_name = "memory_bank"
    requires_embedding = True
    requires_chat = True
    supports_interaction = True

    def __init__(
        self,
        data_dir: Path,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model: Optional["ChatModel"] = None,
        **kwargs: dict,
    ) -> None:
        """初始化记忆库存储."""
        self._storage = EventStorage(data_dir)
        self._engine = MemoryBankEngine(
            data_dir, self._storage, embedding_model, chat_model
        )
        self._feedback = FeedbackManager(data_dir)
        self.embedding_model = embedding_model
        self.chat_model = chat_model

    @property
    def events_store(self) -> JSONStore:
        """事件存储."""
        return self._storage._store

    @property
    def strategies_store(self) -> JSONStore:
        """策略存储."""
        return self._feedback._strategies_store

    @property
    def summaries_store(self) -> JSONStore:
        """摘要存储."""
        return self._engine._summaries_store

    @property
    def interactions_store(self) -> JSONStore:
        """交互存储."""
        return self._engine._interactions_store

    async def write(self, event: MemoryEvent) -> str:
        """写入事件."""
        return await self._engine.write(event)

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """搜索记忆."""
        return await self._engine.search(query, top_k)

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取历史事件."""
        events = await self._storage.read_events()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """更新反馈."""
        await self._feedback.update_feedback(event_id, feedback)

    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录."""
        return await self._engine.write_interaction(query, response, event_type)
