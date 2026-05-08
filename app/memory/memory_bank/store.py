"""MemoryBankStore Facade，MemoryStore Protocol 实现。"""

import logging
from typing import TYPE_CHECKING

from app.memory.embedding_client import EmbeddingClient
from app.memory.schemas import (
    FeedbackData,
    InteractionResult,
    MemoryEvent,
    SearchResult,
)

from .bg_tasks import BackgroundTaskRunner
from .config import MemoryBankConfig
from .forget import ForgettingCurve
from .index import FaissIndex
from .lifecycle import MemoryLifecycle
from .llm import LlmClient
from .retrieval import RetrievalPipeline
from .summarizer import GENERATION_EMPTY, Summarizer

if TYPE_CHECKING:
    from pathlib import Path

    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)


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
        """初始化 MemoryBankStore，组装所有子组件。

        Args:
            data_dir: 持久化目录。
            embedding_model: 嵌入模型（可选）。
            chat_model: 聊天模型（可选）。

        """
        self._config = MemoryBankConfig()
        embed_client = EmbeddingClient(embedding_model) if embedding_model else None
        llm = LlmClient(chat_model) if chat_model else None
        self._index = FaissIndex(data_dir, self._config.embedding_dim)
        self._bg = BackgroundTaskRunner(self._config)
        summarizer = Summarizer(llm, self._index, self._config) if llm else None
        if embed_client is None:
            msg = "embedding_model required"
            raise RuntimeError(msg)
        self._lifecycle = MemoryLifecycle(
            self._index,
            embed_client,
            ForgettingCurve(self._config),
            summarizer,
            self._config,
            self._bg,
        )
        self._retrieval = (
            RetrievalPipeline(self._index, embed_client, self._config)
            if embed_client
            else None
        )

    # ── 委托方法 ──

    async def write(self, event: MemoryEvent) -> str:
        return await self._lifecycle.write(event)

    async def write_interaction(
        self,
        query: str,
        response: str,
        event_type: str = "reminder",
        **kwargs: object,
    ) -> InteractionResult:
        return await self._lifecycle.write_interaction(
            query,
            response,
            event_type,
            **kwargs,
        )

    async def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """搜索记忆."""
        await self._index.load()
        if self._index.total == 0 or not self._retrieval:
            return []
        if self._config.enable_forgetting and await self._lifecycle.purge_forgotten(
            self._index.get_metadata()
        ):
            await self._index.save()
        results = await self._retrieval.search(
            query,
            top_k,
            reference_date=self._config.reference_date,
        )
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

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        return await self._lifecycle.get_history(limit)

    async def get_event_type(self, event_id: str) -> str | None:
        return await self._lifecycle.get_event_type(event_id)

    async def update_feedback(
        self,
        event_id: str,
        feedback: FeedbackData,
    ) -> None:
        pass  # 保持当前 no-op 行为

    async def close(self) -> None:
        await self._bg.shutdown()
