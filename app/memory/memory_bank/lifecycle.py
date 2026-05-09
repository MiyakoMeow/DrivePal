"""记忆生命周期管理：写入、遗忘、摘要编排。"""

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.memory.exceptions import LLMCallFailed, SummarizationEmpty
from app.memory.schemas import InteractionResult, MemoryEvent

from .config import resolve_reference_date
from .forget import ForgettingCurve, compute_ingestion_forget_ids
from .index import FaissIndex

if TYPE_CHECKING:
    from app.memory.embedding_client import EmbeddingClient

    from .bg_tasks import BackgroundTaskRunner
    from .config import MemoryBankConfig
    from .observability import MemoryBankMetrics
    from .summarizer import Summarizer

logger = logging.getLogger(__name__)


class MemoryLifecycle:
    """写入、遗忘、摘要编排。不处理检索。"""

    def __init__(
        self,
        index: FaissIndex,
        embedding_client: EmbeddingClient,
        forget: ForgettingCurve,
        summarizer: Summarizer | None,
        config: MemoryBankConfig,
        bg: BackgroundTaskRunner,
        metrics: MemoryBankMetrics | None = None,
    ) -> None:
        self._index = index
        self._embedding_client = embedding_client
        self._forget = forget
        self._summarizer = summarizer
        self._config = config
        self._bg = bg
        self._metrics = metrics
        self._inflight_summaries: set[str] = set()
        self._inflight_lock = asyncio.Lock()

    async def purge_forgotten(self, metadata: list[dict]) -> bool:
        """对达到遗忘阈值的条目硬删除（从 FAISS 索引移除）。

        Returns:
            True 表示实际执行了删除；节流跳过时返回 False。

        """
        forgotten_ids = self._forget.maybe_forget(
            metadata,
            reference_date=self._resolve_reference_date(),
        )
        if forgotten_ids is None:
            return False  # 节流跳过
        if not forgotten_ids:
            forgotten_ids = [m["faiss_id"] for m in metadata if m.get("forgotten")]
        if forgotten_ids:
            if self._metrics:
                self._metrics.forget_count += 1
                self._metrics.forget_removed_count += len(forgotten_ids)
            await self._index.remove_vectors(forgotten_ids)
            return True
        return False

    def _resolve_reference_date(self) -> str:
        return resolve_reference_date(self._config, self._index)

    async def _forget_at_ingestion(self) -> None:
        """摄入时遗忘：对新数据写入后已有旧条目执行遗忘（对齐 VehicleMemBench）。"""
        today = self._resolve_reference_date()
        ids = compute_ingestion_forget_ids(
            self._index.get_metadata(),
            today,
            config=self._config,
            rng=self._forget.rng,
        )
        if ids:
            if self._metrics:
                self._metrics.forget_count += 1
                self._metrics.forget_removed_count += len(ids)
            await self._index.remove_vectors(ids)

    async def write(self, event: MemoryEvent) -> str:
        """写入事件。支持多行 "Speaker: content" 格式的多说话人解析。

        多说话人场景返回最后一条记录的 FAISS ID（对齐 VehicleMemBench）。
        嵌入编码使用批量 API 以降低往返延迟。

        索引加载由 store 层 _ensure_loaded() 负责，此处不再重复加载。
        """
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        ts = datetime.now(UTC).isoformat()

        lines = [line.strip() for line in event.content.split("\n") if line.strip()]
        parsed_pairs: list[tuple[str | None, str]] = [
            FaissIndex.parse_speaker_line(ln) for ln in lines
        ]
        has_speakers = any(spk is not None for spk, _ in parsed_pairs)

        # 收集阶段：先构建所有 pair texts，再批量编码
        pair_texts: list[str] = []
        pair_metas: list[dict] = []

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
                pair_texts.append(conv_text)
                pair_metas.append(
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
            pair_texts.append(conv_text)
            pair_metas.append(
                {
                    "source": date_key,
                    "speakers": [spk],
                    "raw_content": event.content,
                    "event_type": event.type,
                }
            )

        # 批量编码
        t0 = time.perf_counter()
        embeddings = await self._embedding_client.encode_batch(pair_texts)
        embed_elapsed = (time.perf_counter() - t0) * 1000
        fid: int | None = None
        for text_item, emb, meta in zip(
            pair_texts, embeddings, pair_metas, strict=True
        ):
            fid = await self._index.add_vector(text_item, emb, ts, meta)

        write_elapsed = (time.perf_counter() - t0) * 1000
        if self._metrics:
            self._metrics.write_count += 1
            self._metrics.write_latency_ms.append(write_elapsed)
            self._metrics.embedding_latency_ms.append(embed_elapsed)

        # 写入后仅持久化，不触发摘要/遗忘（遗忘归 finalize/purge_forgotten）
        await self._index.save()
        return str(fid) if fid is not None else ""

    async def write_interaction(
        self,
        query: str,
        response: str,
        event_type: str = "reminder",
        **kwargs: object,
    ) -> InteractionResult:
        """记录一次交互到记忆库。

        索引加载由 store 层 _ensure_loaded() 负责，此处不再重复加载。
        """
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        ts = datetime.now(UTC).isoformat()
        user_name = kwargs.get("user_name") or "User"
        ai_name = kwargs.get("ai_name") or "AI"
        text = (
            f"Conversation content on {date_key}:"
            f"[|{user_name}|]: {query}; [|{ai_name}|]: {response}"
        )
        emb = await self._embedding_client.encode(text)
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
        await self._index.save()
        return InteractionResult(event_id=str(fid))

    async def _trigger_background_summarize(self, date_key: str) -> None:
        """带 inflight 防护的后台摘要触发。同日期不重复提交。"""
        if not self._summarizer:
            return
        async with self._inflight_lock:
            if date_key in self._inflight_summaries:
                return
            self._inflight_summaries.add(date_key)
        self._bg.spawn(self._background_summarize(date_key))

    async def _background_summarize(self, date_key: str) -> None:
        try:
            if not self._summarizer:
                return
            text = await self._summarizer.get_daily_summary(date_key)
            if text:
                emb = await self._embedding_client.encode(text)
                await self._index.add_vector(
                    text,
                    emb,
                    f"{date_key}T00:00:00",
                    {"type": "daily_summary", "source": f"summary_{date_key}"},
                )
            await self._summarizer.get_overall_summary()
            await self._summarizer.get_daily_personality(date_key)
            await self._summarizer.get_overall_personality()
            await self._index.save()
        except SummarizationEmpty:
            logger.debug("background summarization empty for date=%s", date_key)
        except LLMCallFailed:
            if self._metrics:
                self._metrics.background_task_failures += 1
            logger.warning(
                "background summarization failed (LLM) for date=%s",
                date_key,
                exc_info=True,
            )
        except Exception:
            if self._metrics:
                self._metrics.background_task_failures += 1
            logger.warning(
                "background summarization failed for date=%s",
                date_key,
                exc_info=True,
            )
        finally:
            async with self._inflight_lock:
                self._inflight_summaries.discard(date_key)

    async def finalize(self) -> None:
        """遍历所有日期，串行生成缺失摘要/人格，执行摄入遗忘，保存。

        应在批量写入完成后调用（对应 VMB 一次性串行调用模式）。
        """
        if not self._summarizer:
            await self._index.save()
            return
        metadata = self._index.get_metadata()

        # 收集所有唯一 source（即 date_key）
        sources: set[str] = set()
        for m in metadata:
            src = m.get("source", "")
            if src and not src.startswith("summary_"):
                sources.add(src)

        # 串行调用摘要/人格生成（不经过后台任务，与 VMB 行为一致）
        for src in sorted(sources):
            try:
                text = await self._summarizer.get_daily_summary(src)
                if text:
                    emb = await self._embedding_client.encode(text)
                    await self._index.add_vector(
                        text,
                        emb,
                        f"{src}T00:00:00",
                        {"type": "daily_summary", "source": f"summary_{src}"},
                    )
                await self._summarizer.get_daily_personality(src)
            except SummarizationEmpty:
                continue
            except LLMCallFailed:
                logger.warning("finalize: LLM failed for date=%s", src)

        await self._summarizer.get_overall_summary()
        await self._summarizer.get_overall_personality()

        # 摄入遗忘
        await self._forget_at_ingestion()

        # 持久化
        await self._index.save()

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取历史事件。索引加载由 store 层 _ensure_loaded() 负责。"""
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

    async def get_event_type(self, event_id: str) -> str | None:
        """按 event_id 查找事件类型。索引加载由 store 层 _ensure_loaded() 负责。"""
        try:
            fid = int(event_id)
        except ValueError, TypeError:
            return None
        m = self._index.get_metadata_by_id(fid)
        if m is not None:
            return m.get("event_type") or "reminder"
        return None
