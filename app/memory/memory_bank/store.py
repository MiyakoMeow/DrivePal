"""MemoryBankStore Facade，MemoryStore Protocol 实现。"""

import logging
import time
from collections import defaultdict
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
from .observability import MemoryBankMetrics
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
        user_id: str = "default",
        **_kwargs: object,
    ) -> None:
        self._config = MemoryBankConfig()
        embed_client = EmbeddingClient(embedding_model) if embedding_model else None
        if embed_client is None:
            msg = "embedding_model required"
            raise RuntimeError(msg)

        user_dir = data_dir / f"user_{user_id}"
        self._index = FaissIndex(user_dir, self._config.embedding_dim)
        self._metrics = MemoryBankMetrics()
        self._bg = BackgroundTaskRunner(self._config)

        llm = LlmClient(chat_model, self._config) if chat_model else None
        summarizer = Summarizer(llm, self._index, self._config) if llm else None

        self._lifecycle = MemoryLifecycle(
            self._index,
            embed_client,
            ForgettingCurve(self._config),
            summarizer,
            self._config,
            self._bg,
            metrics=self._metrics,
        )
        self._retrieval = RetrievalPipeline(self._index, embed_client, self._config)
        self._last_save_time: float = time.monotonic()

    async def _ensure_loaded(self) -> None:
        """加载索引，消费 LoadResult 告警。"""
        result = await self._index.load()
        if not result.ok:
            logger.error(
                "FaissIndex load failed — index file corrupted and deleted. "
                "Re-ingest data to recover."
            )
        if result.warnings:
            self._metrics.index_load_warnings.extend(result.warnings)
            for w in result.warnings:
                logger.warning("FaissIndex load warning: %s", w)
        if result.recovery_actions:
            for a in result.recovery_actions:
                logger.info("FaissIndex recovery: %s", a)

    async def _maybe_save(self) -> None:
        """持久化节流：距上次保存 < save_interval_seconds 则跳过。"""
        now = time.monotonic()
        if now - self._last_save_time >= self._config.save_interval_seconds:
            await self._index.save()
            self._last_save_time = now

    # ── 委托方法 ──

    async def write(self, event: MemoryEvent) -> str:
        await self._ensure_loaded()
        return await self._lifecycle.write(event)

    async def write_interaction(
        self,
        query: str,
        response: str,
        event_type: str = "reminder",
        **kwargs: object,
    ) -> InteractionResult:
        await self._ensure_loaded()
        return await self._lifecycle.write_interaction(
            query,
            response,
            event_type,
            **kwargs,
        )

    async def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """搜索记忆。"""
        await self._ensure_loaded()
        self._metrics.search_count += 1
        if self._index.total == 0:
            self._metrics.search_empty_index_count += 1
            return []
        if self._config.enable_forgetting and await self._lifecycle.purge_forgotten(
            self._index.get_metadata()
        ):
            await self._index.save()
        t0 = time.monotonic()
        results, updated = await self._retrieval.search(
            query,
            top_k,
            reference_date=self._config.reference_date,
        )
        elapsed = (time.monotonic() - t0) * 1000
        self._metrics.search_latency_ms.append(elapsed)
        if not results:
            self._metrics.search_empty_count += 1

        if updated:
            await self._maybe_save()
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
        actual_limit = max(0, top_k - len(prepend))
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
            for r in results[:actual_limit]
            if not r.get("corrupted")
        )
        return out

    async def format_search_results(self, query: str, top_k: int = 5) -> str:
        """返回人类可读的检索结果文本，用于 LLM prompt 注入。

        按 source 分组，标注 memory_strength 和日期。
        """
        results = await self.search(query, top_k)
        if not results:
            return ""

        # 分离整体上下文和实际结果
        overall = [r for r in results if r.source == "overall"]
        regular = [r for r in results if r.source != "overall"]

        parts: list[str] = []
        for r in overall:
            content = r.event.get("content", "")
            if content:
                parts.append(content)

        # 按 source 分组
        groups: dict[str, list[SearchResult]] = defaultdict(list)
        group_order: list[str] = []
        for r in regular:
            gk = r.source
            if gk not in groups:
                group_order.append(gk)
            groups[gk].append(r)

        idx = len(parts) + 1
        for gk in group_order:
            items = groups[gk]
            max_strength = max(
                (it.event.get("memory_strength", 1) for it in items), default=1
            )
            texts = [it.event.get("content", "") for it in items]
            combined = "; ".join(filter(None, texts))
            display_date = f" [date={gk}]" if gk and gk != "event" else ""
            parts.append(
                f"{idx}. [memory_strength={max_strength}]{display_date} {combined}"
            )
            idx += 1

        return "\n\n".join(parts)

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        await self._ensure_loaded()
        return await self._lifecycle.get_history(limit)

    async def get_event_type(self, event_id: str) -> str | None:
        await self._ensure_loaded()
        return await self._lifecycle.get_event_type(event_id)

    async def update_feedback(
        self,
        event_id: str,
        feedback: FeedbackData,
    ) -> None:
        logger.debug(
            "update_feedback not implemented: event_id=%s action=%s",
            event_id,
            feedback.action,
        )

    @property
    def metrics(self) -> MemoryBankMetrics:
        return self._metrics

    async def close(self) -> None:
        try:
            await self._index.save()
        except Exception:
            logger.warning("Failed to save index during close", exc_info=True)
        finally:
            await self._bg.shutdown()
