"""记忆生命周期管理：写入、遗忘、摘要编排。"""

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.memory.exceptions import LLMCallFailed, SummarizationEmpty
from app.memory.schemas import FeedbackData, InteractionResult, MemoryEvent

from .config import resolve_reference_date
from .forget import ForgettingCurve, compute_ingestion_forget_ids
from .index import FaissIndex

if TYPE_CHECKING:
    from app.memory.embedding_client import EmbeddingClient

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
        metrics: MemoryBankMetrics | None = None,
    ) -> None:
        self._index = index
        self._embedding_client = embedding_client
        self._forget = forget
        self._summarizer = summarizer
        self._config = config
        self._metrics = metrics

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

    @staticmethod
    def _build_pair_texts(
        event: MemoryEvent, date_key: str
    ) -> tuple[list[str], list[dict]]:
        """解析事件内容，返回 (pair_texts, pair_metas)。"""
        lines = [line.strip() for line in event.content.split("\n") if line.strip()]
        parsed_pairs: list[tuple[str | None, str]] = [
            FaissIndex.parse_speaker_line(ln) for ln in lines
        ]
        has_speakers = any(spk is not None for spk, _ in parsed_pairs)
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
        return pair_texts, pair_metas

    async def write(self, event: MemoryEvent) -> str:
        """写入事件。支持多行 "Speaker: content" 格式的多说话人解析。

        多说话人场景返回最后一条记录的 FAISS ID（对齐 VehicleMemBench）。
        嵌入编码使用批量 API 以降低往返延迟。

        索引加载由 store 层 _ensure_loaded() 负责，此处不再重复加载。
        """
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        ts = datetime.now(UTC).isoformat()
        pair_texts, pair_metas = self._build_pair_texts(event, date_key)

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

    async def write_batch(self, events: list[MemoryEvent]) -> list[str]:
        """批量写入，返回 faiss_id 列表（每事件最后一条记录的 ID）。不触发摘要/遗忘。

        多说话人事件可能产生多条 pair_text，仅返回最后一条的 faiss_id（对齐 write() 行为）。
        """
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        ts = datetime.now(UTC).isoformat()
        all_pair_texts: list[str] = []
        all_pair_metas: list[dict] = []
        event_pair_counts: list[int] = []  # 每条 event 对应多少 pair_text

        for event in events:
            pts, pms = self._build_pair_texts(event, date_key)
            all_pair_texts.extend(pts)
            all_pair_metas.extend(pms)
            event_pair_counts.append(len(pts))

        # 一次批量编码
        t0 = time.perf_counter()
        embeddings = await self._embedding_client.encode_batch(all_pair_texts)
        if self._metrics:
            self._metrics.embedding_latency_ms.append((time.perf_counter() - t0) * 1000)

        # 逐条 add_vector，按 event 分组返回最后一条 fid
        fids: list[str] = []
        idx = 0
        for count in event_pair_counts:
            last_fid = ""
            for _ in range(count):
                fid = await self._index.add_vector(
                    all_pair_texts[idx], embeddings[idx], ts, all_pair_metas[idx]
                )
                last_fid = str(fid)
                idx += 1
            fids.append(last_fid)

        if self._metrics:
            self._metrics.write_count += len(events)
            self._metrics.write_latency_ms.append((time.perf_counter() - t0) * 1000)

        # 持久化（不触发摘要/遗忘）
        await self._index.save()
        return fids

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

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """根据用户反馈修改记忆强度。

        accept → memory_strength += 2（主动确认高于被动回忆 +1）
        ignore → memory_strength = max(1, strength - 1)
        两者均更新 last_recall_date 为当天。
        """
        try:
            fid = int(event_id)
        except ValueError, TypeError:
            logger.warning("update_feedback: invalid event_id=%r", event_id)
            return

        m = self._index.get_metadata_by_id(fid)
        if m is None:
            logger.warning("update_feedback: event_id=%r not found", event_id)
            return

        old_strength = float(m.get("memory_strength", 1))
        if feedback.action == "accept":
            m["memory_strength"] = old_strength + 2.0
        elif feedback.action == "ignore":
            m["memory_strength"] = max(1.0, old_strength - 1.0)
        else:
            logger.warning("update_feedback: unknown action=%r", feedback.action)
            return
        m["last_recall_date"] = datetime.now(UTC).strftime("%Y-%m-%d")
        await self._index.save()

    async def _finalize_date_summary(self, date_key: str) -> None:
        """为单个日期生成 daily_summary + daily_personality。"""
        if not self._summarizer:
            return
        try:
            text = await self._summarizer.get_daily_summary(date_key)
            if text:
                emb = await self._embedding_client.encode(text)
                await self._index.add_vector(
                    text,
                    emb,
                    f"{date_key}T00:00:00",
                    {"type": "daily_summary", "source": f"summary_{date_key}"},
                )
            await self._summarizer.get_daily_personality(date_key)
        except SummarizationEmpty:
            return
        except LLMCallFailed:
            logger.warning(
                "finalize: LLM failed for daily summary for date=%s",
                date_key,
                exc_info=True,
            )
        except Exception:
            logger.warning(
                "finalize: unexpected error for date=%s", date_key, exc_info=True
            )

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
            await self._finalize_date_summary(src)

        try:
            await self._summarizer.get_overall_summary()
            await self._summarizer.get_overall_personality()
        except LLMCallFailed:
            logger.warning(
                "finalize: LLM failed for overall summary/personality", exc_info=True
            )
        except Exception:
            logger.warning(
                "finalize: unexpected error for overall summary/personality",
                exc_info=True,
            )

        # 摄入遗忘
        if self._config.enable_forgetting:
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
                id=str(m.get("faiss_id", "")),
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
