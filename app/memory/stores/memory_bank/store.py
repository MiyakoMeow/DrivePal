"""记忆库后端，基于遗忘曲线的记忆存储、聚合与摘要功能."""

import logging
from typing import TYPE_CHECKING

from pydantic import ValidationError

from app.memory.components import EventStorage, FeedbackManager
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.memory.stores.memory_bank.engine import MemoryBankEngine

logger = logging.getLogger(__name__)

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
    def interactions_store(self) -> TOMLStore:
        """交互存储."""
        return self._engine.interactions_store

    async def write(self, event: MemoryEvent) -> str:
        """写入事件."""
        return await self._engine.write(event)

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """搜索记忆."""
        return await self._engine.search(query, top_k)

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取最近的 N 条有效历史事件.

        注意：如果存储中存在格式错误的事件，实际返回数量可能少于 limit。
        """
        events = await self._storage.read_events()
        if limit <= 0:
            return []
        result = []
        for e in events[-limit:]:
            try:
                result.append(MemoryEvent(**e))
            except ValidationError as exc:
                logger.warning(
                    "[warn] skipping malformed event fields=%s error_locs=%s",
                    sorted(e.keys()) if isinstance(e, dict) else [],
                    [err.get("loc") for err in exc.errors()],
                )
        return result

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """更新反馈."""
        await self._feedback.update_feedback(event_id, feedback)

    async def write_interaction(
        self,
        query: str,
        response: str,
        event_type: str = "reminder",
    ) -> str:
        """写入交互记录."""
        return await self._engine.write_interaction(query, response, event_type)
