"""记忆库后端，基于遗忘曲线的记忆存储、聚合与摘要功能."""

from collections.abc import Callable  # noqa: TC003
from typing import TYPE_CHECKING

from app.memory.components import EventStorage, FeedbackManager
from app.memory.schemas import (
    FeedbackData,
    InteractionResult,
    MemoryEvent,
    SearchResult,
)
from app.memory.stores.memory_bank.engine import MemoryBankEngine

if TYPE_CHECKING:
    from pathlib import Path

    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel
    from app.storage.toml_store import TOMLStore


class MemoryBankStore:
    """记忆库后端，支持遗忘曲线、记忆强化与自动摘要."""

    store_name = "memory_bank"
    requires_embedding = True
    requires_chat = True
    supports_interaction = True

    def __init__(
        self,
        data_dir: Path,
        embedding_model: EmbeddingModel | None = None,
        chat_model: ChatModel | None = None,
        **_kwargs: dict,
    ) -> None:
        """初始化记忆库存储."""
        self._storage = EventStorage(data_dir)
        self._engine = MemoryBankEngine(
            data_dir,
            self._storage,
            embedding_model,
            chat_model,
        )
        self._feedback = FeedbackManager(data_dir)
        self.embedding_model = embedding_model
        self.chat_model = chat_model

    @property
    def events_store(self) -> TOMLStore:
        """事件存储."""
        return self._storage.store

    @property
    def strategies_store(self) -> TOMLStore:
        """策略存储."""
        return self._feedback.strategies_store

    @property
    def summaries_store(self) -> TOMLStore:
        """摘要存储."""
        return self._engine.summaries_store

    @property
    def personality_store(self) -> TOMLStore:
        """人格存储."""
        return self._engine.personality_store

    @property
    def interactions_store(self) -> TOMLStore:
        """交互存储."""
        return self._engine.interactions_store

    async def write(self, event: MemoryEvent) -> str:
        """写入事件."""
        return await self._engine.write(event)

    async def write_batch(
        self,
        events: list[MemoryEvent],
        progress_fn: Callable[[int, int], None] | None = None,
    ) -> list[str]:
        """批量写入事件."""
        return await self._engine.write_batch(events, progress_fn=progress_fn)

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

    async def get_event_type(self, event_id: str) -> str | None:
        """按 event_id 查找事件类型."""
        event = await self._storage.find_event_by_id(event_id)
        if event is None:
            return None
        return event.get("type")

    async def write_interaction(
        self,
        query: str,
        response: str,
        event_type: str = "reminder",
    ) -> InteractionResult:
        """写入交互记录."""
        return await self._engine.write_interaction(query, response, event_type)

    async def reset_forgetting_state(self) -> None:
        """重置遗忘状态."""
        await self._engine.reset_forgetting_state()
