"""基于 FAISS 的记忆存储，MemoryStore Protocol 实现。"""

import asyncio
import contextlib
import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.memory.components import FeedbackManager
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
from app.memory.stores.memory_bank.summarizer import GENERATION_EMPTY, Summarizer

if TYPE_CHECKING:
    from pathlib import Path

    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[None]] = set()


def _finalize_task(task: asyncio.Task[None]) -> None:
    _background_tasks.discard(task)
    with contextlib.suppress(asyncio.CancelledError):
        exc = task.exception()
        if exc is not None:
            logger.warning("Background task failed: %s", exc)


class MemoryBankStore:
    """基于 FAISS 的记忆存储，MemoryStore Protocol 实现。"""

    store_name = "memory_bank"
    requires_embedding = True
    requires_chat = True
    supports_interaction = True

    def __init__(
        self,
        data_dir: Path,
        embedding_model: EmbeddingModel | None = None,
        chat_model: ChatModel | None = None,
        **_kwargs: object,
    ) -> None:
        """初始化记忆库存储."""
        self._data_dir = data_dir
        self._index = FaissIndex(data_dir)
        self._forget = ForgettingCurve()
        self._feedback = FeedbackManager(data_dir)
        self._embedding_model = embedding_model
        self._chat_model = chat_model
        self._retrieval = (
            RetrievalPipeline(self._index, embedding_model) if embedding_model else None
        )
        self._llm = LlmClient(chat_model) if chat_model else None
        self._summarizer = Summarizer(self._llm, self._index) if self._llm else None
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
            forgotten_ids = self._forget.maybe_forget(self._index.get_metadata())
            if forgotten_ids:
                await self._index.remove_vectors(forgotten_ids)
        await self._index.save()
        if self._summarizer:
            task = asyncio.create_task(self._background_summarize(date_key))
            _background_tasks.add(task)
            task.add_done_callback(_finalize_task)
        return InteractionResult(event_id=str(fid))

    async def _background_summarize(self, date_key: str) -> None:
        if not self._summarizer or not self._embedding_model:
            return
        try:
            text = await self._summarizer.get_daily_summary(date_key)
            if text:
                emb = await self._embedding_model.encode(text)
                await self._index.add_vector(
                    text,
                    emb,
                    f"{date_key}T00:00:00",
                    {"type": "daily_summary", "source": f"summary_{date_key}"},
                )
                await self._index.save()  # 尽早持久化日摘要
            await self._summarizer.get_overall_summary()
            await self._summarizer.get_daily_personality(date_key)
            await self._summarizer.get_overall_personality()
            await self._index.save()
        except Exception:
            logger.exception("background summarization failed")

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """搜索记忆."""
        await self._index.load()
        if self._index.total == 0 or not self._retrieval:
            return []
        if self._forgetting_enabled:
            forgotten_ids = self._forget.maybe_forget(self._index.get_metadata())
            if forgotten_ids:
                await self._index.remove_vectors(forgotten_ids)
            await self._index.save()
        results = await self._retrieval.search(query, top_k)
        extra = self._index.get_extra()
        prepend = []
        for key, label in [
            ("overall_summary", "Overall summary of past memories"),
            ("overall_personality", "User vehicle preferences and habits"),
        ]:
            val = extra.get(key, "")
            if val and val != GENERATION_EMPTY:
                prepend.append(f"{label}: {val}")
        out: list[SearchResult] = []
        if prepend:
            out.append(
                SearchResult(
                    event={"content": "\n".join(prepend), "type": "overall_context"},
                    score=float("inf"),
                    source="overall",
                )
            )
        out.extend(
            SearchResult(
                event={
                    "content": r.get("text", ""),
                    "source": r.get("source", ""),
                    "memory_strength": int(r.get("memory_strength", 1)),
                },
                score=float(r.get("score", 0.0)),
                source=r.get("source", "event"),
            )
            for r in results[: max(0, top_k - len(prepend))]
        )
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
            forgotten_ids = self._forget.maybe_forget(self._index.get_metadata())
            if forgotten_ids:
                await self._index.remove_vectors(forgotten_ids)
        await self._index.save()
        if self._summarizer:
            task = asyncio.create_task(self._background_summarize(date_key))
            _background_tasks.add(task)
            task.add_done_callback(_finalize_task)
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
