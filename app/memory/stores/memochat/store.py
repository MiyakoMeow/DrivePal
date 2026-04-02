"""MemoChat 记忆存储后端."""

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from app.memory.components import EventStorage, FeedbackManager
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.memory.stores.memochat.engine import MemoChatEngine
from app.memory.stores.memochat.retriever import RetrievalMode
from app.storage.toml_store import TOMLStore

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel


class MemoChatStore:
    """MemoChat 记忆存储后端，基于三阶段 pipeline."""

    store_name = "memochat"
    requires_embedding = False
    requires_chat = True
    supports_interaction = True

    def __init__(
        self,
        data_dir: Path,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model: Optional["ChatModel"] = None,
        retrieval_mode: RetrievalMode = RetrievalMode.FULL_LLM,
    ) -> None:
        """初始化 MemoChat 存储."""
        self._storage = EventStorage(data_dir)
        self._engine = MemoChatEngine(
            data_dir, chat_model, embedding_model, retrieval_mode
        )
        self._feedback = FeedbackManager(data_dir)
        self.embedding_model = embedding_model
        self.chat_model = chat_model
        self._write_lock = asyncio.Lock()

    @property
    def events_store(self) -> TOMLStore:
        """事件存储."""
        return self._storage.store

    @property
    def strategies_store(self) -> TOMLStore:
        """策略存储."""
        return self._feedback.strategies_store

    async def _locked_write(self, event: MemoryEvent) -> str:
        """写入事件，创建 memo 条目（受锁保护）."""
        now = datetime.now(timezone.utc)
        memo_entry = {
            "id": self._storage.generate_id(),
            "summary": event.content,
            "dialogs": [],
            "created_at": now.isoformat(),
            "memory_strength": 1,
            "last_recall_date": now.isoformat(),
        }
        topic = event.type or "general"
        async with self._write_lock:
            await self._engine.append_memo(topic, memo_entry)
            event_copy = event.model_copy(deep=True)
            event_copy.id = memo_entry["id"]
            event_copy.created_at = memo_entry["created_at"]
            await self._storage.append_raw(event_copy.model_dump())
        return memo_entry["id"]

    async def write(self, event: MemoryEvent) -> str:
        """写入事件，创建 memo 条目."""
        return await self._locked_write(event)

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """搜索记忆."""
        return await self._engine.search(query, top_k)

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取历史事件."""
        memos = await self._engine.read_memos()
        all_entries: list[tuple[str, dict]] = [
            (topic, entry)
            for topic, entries in memos.items()
            for entry in entries
            if entry.get("id") and entry.get("created_at")
        ]
        all_entries.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)
        results = []
        for topic, entry in all_entries[:limit]:
            results.append(
                MemoryEvent(
                    id=entry.get("id", ""),
                    content=f"{topic}: {entry.get('summary', '')}",
                    type="memochat_memo",
                    description=" ### ".join(entry.get("dialogs", [])),
                    memory_strength=entry.get("memory_strength", 1),
                    last_recall_date=entry.get("last_recall_date", ""),
                    date_group=entry.get("created_at", "")[:10]
                    if entry.get("created_at")
                    else datetime.now(timezone.utc).date().isoformat(),
                    created_at=entry.get("created_at", ""),
                )
            )
        return results

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """更新反馈."""
        await self._feedback.update_feedback(event_id, feedback)

    async def _locked_write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录（受锁保护）."""
        now = datetime.now(timezone.utc)
        interaction_id = f"{now.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        interaction = {
            "id": interaction_id,
            "event_id": "",
            "query": query,
            "response": response,
            "timestamp": now.isoformat(),
            "event_type": event_type,
        }
        async with self._write_lock:
            await self._engine.append_interaction(interaction)
            await self._engine.append_recent_dialog(f"user: {query}")
            await self._engine.append_recent_dialog(f"bot: {response}")
            await self._engine.trigger_summarization()
        return interaction_id

    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录."""
        return await self._locked_write_interaction(query, response, event_type)
