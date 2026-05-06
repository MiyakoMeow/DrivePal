"""基于 FAISS 的记忆存储，MemoryStore Protocol 实现。"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.memory.schemas import (
    FeedbackData,
    InteractionResult,
    MemoryEvent,
    SearchResult,
)

if TYPE_CHECKING:
    from app.memory.interfaces import (
        FeedbackHandler,
        ForgettingStrategy,
        RetrievalStrategy,
        SearchEnricher,
        VectorIndex,
    )
    from app.memory.worker import BackgroundWorker
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)


class MemoryBankStore:
    """基于 FAISS 的记忆存储，MemoryStore Protocol 实现。"""

    store_name = "memory_bank"
    requires_embedding = True
    requires_chat = True

    def __init__(
        self,
        index: VectorIndex,
        retrieval: RetrievalStrategy,
        embedding_model: EmbeddingModel,
        enricher: SearchEnricher | None = None,
        forgetting: ForgettingStrategy | None = None,
        feedback: FeedbackHandler | None = None,
        background: BackgroundWorker | None = None,
    ) -> None:
        """初始化记忆库存储，依赖注入子组件。"""
        self._index = index
        self._retrieval = retrieval
        self._embedding_model = embedding_model
        self._enricher = enricher
        self._forgetting = forgetting
        self._feedback = feedback
        self._background = background
        self._forgetting_enabled = os.getenv(
            "MEMORYBANK_ENABLE_FORGETTING", "0"
        ).lower() in (
            "1",
            "true",
            "yes",
        )

    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> InteractionResult:
        """记录一次交互到记忆库."""
        if not self._embedding_model:
            msg = "embedding_model required"
            raise RuntimeError(msg)
        await self._index.load()
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        ts = datetime.now(UTC).isoformat()
        text = (
            f"Conversation content on {date_key}:[|User|]: {query}; [|AI|]: {response}"
        )
        emb = await self._embedding_model.encode(text)
        fid = await self._index.add_vector(
            text,
            emb,
            ts,
            {
                "source": date_key,
                "speakers": ["User", "AI"],
                "raw_content": query,
                "event_type": event_type,
            },
        )
        if self._forgetting_enabled:
            forgotten_ids = (
                self._forgetting.maybe_forget(self._index.get_metadata())
                if self._forgetting
                else None
            )
            if forgotten_ids:
                await self._index.remove_vectors(forgotten_ids)
        await self._index.save()
        if self._background:
            self._background.schedule_summarize(date_key)
        return InteractionResult(event_id=str(fid))

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """搜索记忆."""
        await self._index.load()
        if self._index.total == 0 or not self._retrieval:
            return []
        if self._forgetting_enabled:
            forgotten_ids = (
                self._forgetting.maybe_forget(self._index.get_metadata())
                if self._forgetting
                else None
            )
            if forgotten_ids is not None:
                if forgotten_ids:
                    await self._index.remove_vectors(forgotten_ids)
                await self._index.save()
        results = await self._retrieval.search(query, top_k)
        out = [
            SearchResult(
                event={
                    "content": r.get("text", ""),
                    "source": r.get("source", ""),
                    "memory_strength": int(r.get("memory_strength", 1)),
                },
                score=float(r.get("score", 0.0)),
                source=r.get("source", "event"),
            )
            for r in results
        ]
        if self._enricher:
            out = await self._enricher.enrich(out, self._index.get_extra())
        return out

    async def write(self, event: MemoryEvent) -> str:
        """写入事件."""
        if not self._embedding_model:
            msg = "embedding_model required"
            raise RuntimeError(msg)
        await self._index.load()
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        ts = datetime.now(UTC).isoformat()
        text = f"Conversation content on {date_key}:[|System|]: {event.content}"
        emb = await self._embedding_model.encode(text)
        fid = await self._index.add_vector(
            text,
            emb,
            ts,
            {
                "source": date_key,
                "speakers": ["System"],
                "raw_content": event.content,
                "event_type": event.type,
            },
        )
        if self._forgetting_enabled:
            forgotten_ids = (
                self._forgetting.maybe_forget(self._index.get_metadata())
                if self._forgetting
                else None
            )
            if forgotten_ids:
                await self._index.remove_vectors(forgotten_ids)
        await self._index.save()
        if self._background:
            self._background.schedule_summarize(date_key)
        return str(fid)

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取历史事件."""
        await self._index.load()
        entries = [
            m for m in self._index.get_metadata() if m.get("type") != "daily_summary"
        ]
        return [
            MemoryEvent(
                content=m.get("raw_content") or m.get("text", ""),
                type=m.get("event_type", "reminder"),
                memory_strength=int(m.get("memory_strength", 1)),
            )
            for m in entries[-limit:]
        ]

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """更新反馈."""
        if self._feedback:
            await self._feedback.update_feedback(event_id, feedback)

    async def get_event_type(self, event_id: str) -> str | None:
        """按 event_id 查找事件类型."""
        await self._index.load()
        try:
            fid = int(event_id)
        except ValueError, TypeError:
            return None
        m = self._index.get_metadata_by_id(fid)
        if m is not None:
            return m.get("event_type") or "reminder"
        return None
