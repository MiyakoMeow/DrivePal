"""基于 FAISS 的记忆存储，MemoryStore Protocol 实现。"""

import asyncio
import contextlib
import logging
import os
import random
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
        seed: int | None = None,
        **_kwargs: object,
    ) -> None:
        """初始化记忆库存储.

        Args:
            data_dir: 持久化目录。
            embedding_model: 嵌入模型。
            chat_model: 聊天模型。
            seed: 随机种子。优先使用显式传入值；
                  未传入时从环境变量 MEMORYBANK_SEED 读取。

        """
        self._data_dir = data_dir
        # 从环境变量读取 seed（若未显式传入）
        if seed is None:
            raw = os.getenv("MEMORYBANK_SEED")
            if raw is not None:
                try:
                    seed = int(raw)
                except ValueError:
                    pass
        self._rng = random.Random(seed)
        self._index = FaissIndex(data_dir)
        self._forget = ForgettingCurve(rng=self._rng)
        self._feedback = FeedbackManager(data_dir)
        self._embedding_model = embedding_model
        self._chat_model = chat_model
        self._retrieval = (
            RetrievalPipeline(self._index, embedding_model) if embedding_model else None
        )
        self._llm = LlmClient(chat_model, rng=self._rng) if chat_model else None
        self._summarizer = Summarizer(self._llm, self._index) if self._llm else None
        self._forgetting_enabled = os.getenv(
            "MEMORYBANK_ENABLE_FORGETTING", "0"
        ).lower() in (
            "1",
            "true",
            "yes",
        )

    async def _purge_forgotten(self, metadata: list[dict]) -> bool:
        """对达到遗忘阈值的条目硬删除（从 FAISS 索引移除）。

        Returns:
            True 表示实际执行了删除；节流跳过时返回 False。

        """
        forgotten_ids = self._forget.maybe_forget(metadata)
        if forgotten_ids is None:
            return False  # 节流跳过
        if not forgotten_ids:
            forgotten_ids = [m["faiss_id"] for m in metadata if m.get("forgotten")]
        if forgotten_ids:
            await self._index.remove_vectors(forgotten_ids)
            return True
        return False

    async def write_interaction(
        self,
        query: str,
        response: str,
        event_type: str = "reminder",
        **kwargs: object,
    ) -> InteractionResult:
        """记录一次交互到记忆库。

        Args:
            query: 用户输入。
            response: AI 回复。
            event_type: 事件类型。
            **kwargs: 可选参数，支持 user_name（发言者姓名）和 ai_name。

        """
        if not self._embedding_model:
            msg = "embedding_model required"
            raise RuntimeError(msg)
        await self._index.load()
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        ts = datetime.now(UTC).isoformat()
        user_name = kwargs.get("user_name") or "User"
        ai_name = kwargs.get("ai_name") or "AI"
        text = (
            f"Conversation content on {date_key}:"
            f"[|{user_name}|]: {query}; [|{ai_name}|]: {response}"
        )
        emb = await self._embedding_model.encode(text)
        fid = await self._index.add_vector(
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
        if self._forgetting_enabled:
            await self._purge_forgotten(self._index.get_metadata())
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
        if self._forgetting_enabled and await self._purge_forgotten(
            self._index.get_metadata()
        ):
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
        """写入事件。支持多行 "Speaker: content" 格式的多说话人解析。"""
        if not self._embedding_model:
            msg = "embedding_model required"
            raise RuntimeError(msg)
        await self._index.load()
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        ts = datetime.now(UTC).isoformat()

        lines = [line.strip() for line in event.content.split("\n") if line.strip()]
        parsed_pairs: list[tuple[str | None, str]] = [
            FaissIndex.parse_speaker_line(ln) for ln in lines
        ]
        has_speakers = any(spk is not None for spk, _ in parsed_pairs)

        fid: int | None = None
        if has_speakers:
            # 配对模式：每 2 行结对为 1 条向量（对齐 VehicleMemBench 原版）
            for i in range(0, len(parsed_pairs), 2):
                speaker_a, text_a = parsed_pairs[i]
                if i + 1 < len(parsed_pairs):
                    speaker_b, text_b = parsed_pairs[i + 1]
                    speakers = [speaker_a, speaker_b]
                    conv_text = (
                        f"Conversation content on {date_key}:"
                        f"[|{speaker_a}|]: {text_a}; [|{speaker_b}|]: {text_b}"
                    )
                else:
                    speakers = [speaker_a]
                    conv_text = (
                        f"Conversation content on {date_key}:[|{speaker_a}|]: {text_a}"
                    )
                emb = await self._embedding_model.encode(conv_text)
                fid = await self._index.add_vector(
                    conv_text,
                    emb,
                    ts,
                    {
                        "source": date_key,
                        "speakers": sorted(set(speakers)),
                        "raw_content": conv_text,
                        "event_type": event.type,
                    },
                )
        else:
            # 单用户回退
            spk = event.speaker or "System"
            conv_text = f"Conversation content on {date_key}:[|{spk}|]: {event.content}"
            emb = await self._embedding_model.encode(conv_text)
            fid = await self._index.add_vector(
                conv_text,
                emb,
                ts,
                {
                    "source": date_key,
                    "speakers": [spk],
                    "raw_content": event.content,
                    "event_type": event.type,
                },
            )
        if self._forgetting_enabled:
            await self._purge_forgotten(self._index.get_metadata())
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
