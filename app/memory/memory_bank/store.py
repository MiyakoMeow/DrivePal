"""基于 FAISS 的记忆存储，多用户 MemoryBankStore。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from app.memory.embedding_client import EmbeddingClient
from app.memory.schemas import (
    FeedbackData,
    InteractionResult,
    MemoryEvent,
    SearchResult,
)

from .faiss_index import FaissIndexManager
from .forget import (
    ForgetMode,
    compute_ingestion_forget_ids,
)
from .llm import LlmClient
from .retrieval import RetrievalPipeline
from .summarizer import GENERATION_EMPTY, Summarizer

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
    """基于 FAISS 的多用户记忆存储。

    所有方法接受 user_id 参数实现 per-user 索引隔离。
    """

    store_name = "memory_bank"
    requires_embedding = True
    requires_chat = True

    def __init__(
        self,
        data_dir: Path,
        embedding_model: EmbeddingModel,
        chat_model: ChatModel,
        seed: int | None = None,
        reference_date: str | None = None,
    ) -> None:
        """初始化多用户记忆库存储。

        Args:
            data_dir: 数据目录（内建 user_{user_id}/ 子目录）。
            embedding_model: 嵌入模型（必需）。
            chat_model: 聊天模型（必需）。
            seed: 随机种子（可选）。
            reference_date: 遗忘参考日期（可选，默认从 metadata 自动计算）。

        """
        self._data_dir = data_dir
        if seed is None:
            raw = os.getenv("MEMORYBANK_SEED")
            if raw is not None:
                try:
                    seed = int(raw)
                except ValueError:
                    logger.warning("MEMORYBANK_SEED=%r 无法解析为整数", raw)
        self._rng = random.Random(seed)
        self._seed_provided = seed is not None
        self._index_manager = FaissIndexManager(data_dir)
        self._embedding_client = EmbeddingClient(embedding_model)
        self._llm = LlmClient(chat_model, rng=self._rng)
        self._retrieval = RetrievalPipeline(self._index_manager, self._embedding_client)
        self._summarizer = Summarizer(self._llm, self._index_manager)
        self._reference_date = reference_date
        self._forgetting_enabled = os.getenv(
            "MEMORYBANK_ENABLE_FORGETTING", "0"
        ).lower() in ("1", "true", "yes")

    # ── 参考日期 ──

    def _get_reference_date(self, user_id: str) -> str | None:
        """优先构造器 reference_date，未设置则从 metadata 最新 timestamp +1 天推导。"""
        if self._reference_date:
            return self._reference_date
        metadata = self._index_manager.get_metadata(user_id)
        if not metadata:
            return None
        timestamps = [
            m.get("timestamp", "")[:10] for m in metadata if m.get("timestamp")
        ]
        if not timestamps:
            return None
        max_ts = max(timestamps)
        ref = date.fromisoformat(max_ts) + timedelta(days=1)
        return ref.strftime("%Y-%m-%d")

    # ── 遗忘 ──

    async def _forget_at_ingestion(self, user_id: str) -> None:
        """摄入时遗忘：删除 retention < threshold 的旧条目。"""
        if not self._forgetting_enabled:
            return
        ref_date = self._get_reference_date(user_id)
        if not ref_date:
            return
        metadata = self._index_manager.get_metadata(user_id)
        ids = compute_ingestion_forget_ids(
            metadata,
            ref_date,
            rng=self._rng,
            mode=ForgetMode.PROBABILISTIC
            if self._seed_provided
            else ForgetMode.DETERMINISTIC,
        )
        if ids:
            await self._index_manager.remove_vectors(user_id, ids)

    # ── 后台摘要 ──

    async def _background_summarize(self, user_id: str, date_key: str) -> None:
        try:
            text = await self._summarizer.get_daily_summary(user_id, date_key)
            if text:
                emb = await self._embedding_client.encode(text)
                await self._index_manager.add_vector(
                    user_id,
                    text,
                    emb,
                    f"{date_key}T00:00:00",
                    {"type": "daily_summary", "source": f"summary_{date_key}"},
                )
                await self._index_manager.save(user_id)
            await self._summarizer.get_overall_summary(user_id)
            await self._summarizer.get_daily_personality(user_id, date_key)
            await self._summarizer.get_overall_personality(user_id)
            await self._index_manager.save(user_id)
        except Exception:
            logger.exception("background summarization failed for user=%s", user_id)

    # ── 核心 API ──

    async def write(self, user_id: str, event: MemoryEvent) -> str:
        """写入事件。支持多行 "Speaker: content" 格式的多说话人解析。"""
        await self._index_manager.load(user_id)
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        ts = datetime.now(UTC).isoformat()

        lines = [line.strip() for line in event.content.split("\n") if line.strip()]
        parsed_pairs: list[tuple[str | None, str]] = [
            FaissIndexManager.parse_speaker_line(ln) for ln in lines
        ]
        has_speakers = any(spk is not None for spk, _ in parsed_pairs)

        all_pair_texts: list[str] = []
        all_pair_metas: list[dict] = []
        fid: int | None = None

        if has_speakers:
            for i in range(0, len(parsed_pairs), 2):
                speaker_a, text_a = parsed_pairs[i]
                label_a = speaker_a if speaker_a is not None else "Unknown"
                if i + 1 < len(parsed_pairs):
                    speaker_b, text_b = parsed_pairs[i + 1]
                    label_b = speaker_b if speaker_b is not None else "Unknown"
                    speakers = [speaker_a, speaker_b]
                    conv_text = (
                        f"Conversation content on {date_key}:"
                        f"[|{label_a}|]: {text_a}; [|{label_b}|]: {text_b}"
                    )
                else:
                    speakers = [speaker_a]
                    conv_text = (
                        f"Conversation content on {date_key}:[|{label_a}|]: {text_a}"
                    )
                all_pair_texts.append(conv_text)
                all_pair_metas.append(
                    {
                        "source": date_key,
                        "speakers": sorted({s for s in speakers if s is not None}),
                        "raw_content": conv_text,
                        "event_type": event.type,
                    }
                )
        else:
            spk = event.speaker or "System"
            conv_text = f"Conversation content on {date_key}:[|{spk}|]: {event.content}"
            all_pair_texts.append(conv_text)
            all_pair_metas.append(
                {
                    "source": date_key,
                    "speakers": [spk],
                    "raw_content": event.content,
                    "event_type": event.type,
                }
            )

        # 批量嵌入
        embeddings = await self._embedding_client.encode_batch(all_pair_texts)
        for conv_text, emb, meta in zip(
            all_pair_texts, embeddings, all_pair_metas, strict=True
        ):
            fid = await self._index_manager.add_vector(
                user_id, conv_text, emb, ts, meta
            )

        await self._forget_at_ingestion(user_id)
        await self._index_manager.save(user_id)
        if self._summarizer:
            task = asyncio.create_task(self._background_summarize(user_id, date_key))
            _background_tasks.add(task)
            task.add_done_callback(_finalize_task)
        return str(fid)

    async def write_interaction(
        self,
        user_id: str,
        query: str,
        response: str,
        event_type: str = "reminder",
        *,
        user_name: str = "User",
        ai_name: str = "AI",
    ) -> InteractionResult:
        """记录一次交互到记忆库。"""
        await self._index_manager.load(user_id)
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        ts = datetime.now(UTC).isoformat()
        text = (
            f"Conversation content on {date_key}:"
            f"[|{user_name}|]: {query}; [|{ai_name}|]: {response}"
        )
        emb = await self._embedding_client.encode(text)
        fid = await self._index_manager.add_vector(
            user_id,
            text,
            emb,
            ts,
            {
                "source": date_key,
                "speakers": [user_name, ai_name],
                "raw_content": query,
                "event_type": event_type,
            },
        )
        await self._forget_at_ingestion(user_id)
        await self._index_manager.save(user_id)
        if self._summarizer:
            task = asyncio.create_task(self._background_summarize(user_id, date_key))
            _background_tasks.add(task)
            task.add_done_callback(_finalize_task)
        return InteractionResult(event_id=str(fid))

    async def search(
        self, user_id: str, query: str, top_k: int = 5
    ) -> list[SearchResult]:
        """搜索记忆。"""
        await self._index_manager.load(user_id)
        total = await self._index_manager.total(user_id)
        if total == 0:
            return []

        ref_date = self._get_reference_date(user_id)
        results, strength_updates = await self._retrieval.search(
            user_id, query, top_k, reference_date=ref_date
        )
        if strength_updates:
            await self._index_manager.batch_update_metadata(user_id, strength_updates)
            await self._index_manager.save(user_id)

        extra = self._index_manager.get_extra(user_id)
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
                    event={
                        "content": "\n".join(prepend),
                        "type": "overall_context",
                    },
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

    async def get_history(self, user_id: str, limit: int = 10) -> list[MemoryEvent]:
        """获取历史事件。"""
        await self._index_manager.load(user_id)
        entries = [
            m
            for m in self._index_manager.get_metadata(user_id)
            if m.get("type") != "daily_summary"
        ]
        return [
            MemoryEvent(
                content=m.get("raw_content") or m.get("text", ""),
                type=m.get("event_type", "reminder"),
                memory_strength=int(m.get("memory_strength", 1)),
            )
            for m in entries[-limit:]
        ]

    async def get_event_type(self, user_id: str, event_id: str) -> str | None:
        """按 event_id 查找事件类型。"""
        await self._index_manager.load(user_id)
        try:
            fid = int(event_id)
        except ValueError, TypeError:
            return None
        m = self._index_manager.get_metadata_by_id(user_id, fid)
        if m is not None:
            return m.get("event_type") or "reminder"
        return None

    async def update_feedback(
        self, user_id: str, event_id: str, feedback: FeedbackData
    ) -> None:
        """反馈功能已移除，静默忽略。"""
