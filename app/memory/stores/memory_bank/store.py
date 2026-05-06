"""基于 FAISS 的记忆存储，MemoryStore Protocol 实现。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.memory.components import FeedbackManager
from app.memory.enricher import OverallContextEnricher
from app.memory.schemas import (
    FeedbackData,
    InteractionResult,
    MemoryEvent,
    SearchResult,
)
from app.memory.stores.memory_bank.faiss_index import FaissIndex
from app.memory.stores.memory_bank.forget import ForgettingCurve
from app.memory.stores.memory_bank.llm import LlmClient
from app.memory.stores.memory_bank.retrieval import RetrievalPipeline
from app.memory.stores.memory_bank.summarizer import Summarizer
from app.memory.worker import BackgroundWorker

if TYPE_CHECKING:
    from pathlib import Path

    from app.memory.interfaces import (
        FeedbackHandler,
        ForgettingStrategy,
        RetrievalStrategy,
        SearchEnricher,
        VectorIndex,
    )
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)


@dataclass
class MemoryBankStoreConfig:
    """MemoryBankStore 依赖注入参数对象。"""

    index: VectorIndex
    retrieval: RetrievalStrategy
    embedding_model: EmbeddingModel
    enricher: SearchEnricher | None = None
    forgetting: ForgettingStrategy | None = None
    feedback: FeedbackHandler | None = None
    background: BackgroundWorker | None = None
    forgetting_enabled: bool = False


class MemoryBankStore:
    """基于 FAISS 的记忆存储，MemoryStore Protocol 实现。"""

    store_name = "memory_bank"
    requires_embedding = True
    requires_chat = True

    @classmethod
    def create_default_config(
        cls,
        data_dir: Path,
        embedding_model: EmbeddingModel | None,
        chat_model: ChatModel | None,
    ) -> MemoryBankStoreConfig:
        """构造默认 MemoryBankStoreConfig。"""
        index: FaissIndex = FaissIndex(data_dir)
        if embedding_model is None:
            msg = f"{cls.store_name} requires embedding_model"
            raise RuntimeError(msg)
        retrieval = RetrievalPipeline(index, embedding_model)
        forgetting = ForgettingCurve()
        feedback = FeedbackManager(data_dir)
        summarizer_svc = None
        background = None
        if chat_model is not None:
            llm = LlmClient(chat_model)
            summarizer_svc = Summarizer(llm, index)
            background = BackgroundWorker(index, summarizer_svc, embedding_model)
        enricher = OverallContextEnricher()
        forgetting_enabled = os.getenv("MEMORYBANK_ENABLE_FORGETTING", "0").lower() in (
            "1",
            "true",
            "yes",
        )
        return MemoryBankStoreConfig(
            index=index,
            retrieval=retrieval,
            embedding_model=embedding_model,
            enricher=enricher,
            forgetting=forgetting,
            feedback=feedback,
            background=background,
            forgetting_enabled=forgetting_enabled,
        )

    def __init__(self, config: MemoryBankStoreConfig) -> None:
        """初始化记忆库存储，接收参数对象。"""
        self._index = config.index
        self._retrieval = config.retrieval
        self._embedding_model = config.embedding_model
        self._enricher = config.enricher
        self._forgetting = config.forgetting
        self._feedback = config.feedback
        self._background = config.background
        self._forgetting_enabled = config.forgetting_enabled

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
            await self._background.schedule_summarize(date_key)
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
            await self._background.schedule_summarize(date_key)
        return str(fid)

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取历史事件."""
        await self._index.load()
        entries = [
            m for m in self._index.get_metadata() if m.get("type") != "daily_summary"
        ]
        return [
            MemoryEvent(
                id=str(m.get("faiss_id", "")),
                content=m.get("raw_content") or m.get("text", ""),
                type=m.get("event_type", "reminder"),
                memory_strength=int(m.get("memory_strength", 1)),
            )
            for m in entries[-limit:]
        ]

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """更新反馈."""
        if not self._feedback:
            msg = f"FeedbackHandler 未配置，无法更新 event_id={event_id} 的反馈"
            raise RuntimeError(msg)
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
