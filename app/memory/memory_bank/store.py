"""MemoryBankStore Facade，MemoryStore Protocol 实现。"""

import json
import logging
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.memory.embedding_client import EmbeddingClient
from app.memory.schemas import (
    FeedbackData,
    InteractionResult,
    MemoryEvent,
    SearchResult,
)
from app.storage.jsonl_store import JSONLinesStore

from .config import MemoryBankConfig, resolve_reference_date
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

    _SOURCE_INDEX_FILENAME = "source_event_index.json"

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
        """初始化 MemoryBankStore。

        Args:
            data_dir: per-user 数据根目录。
            embedding_model: 嵌入模型。
            chat_model: 聊天模型。
            user_id: 用户标识（Protocol 接口兼容）。
            _kwargs: 额外参数（接口兼容）。

        """
        self._config = MemoryBankConfig()
        embed_client = (
            EmbeddingClient(
                embedding_model, batch_size=self._config.embedding_batch_size
            )
            if embedding_model
            else None
        )
        if embed_client is None:
            msg = "embedding_model required"
            raise RuntimeError(msg)

        user_dir = data_dir / "memorybank"  # FAISS 存储在 memorybank 子目录
        self._user_root = data_dir  # per-user 根目录
        self._user_dir = user_dir
        self._feedback_store: JSONLinesStore | None = None
        self._index = FaissIndex(
            user_dir,
            self._config.embedding_dim,
            index_type=self._config.index_type,
            ivf_nlist=self._config.ivf_nlist,
        )
        self._metrics = MemoryBankMetrics()
        self._interaction_map: dict[
            str, list[str]
        ] = {}  # event_faiss_id → [interaction_faiss_id, ...]
        self._source_event_index: dict[
            str, list[str]
        ] = {}  # date_key → [event_faiss_id, ...]

        llm = LlmClient(chat_model, self._config) if chat_model else None
        summarizer = Summarizer(llm, self._index, self._config) if llm else None

        self._lifecycle = MemoryLifecycle(
            self._index,
            embed_client,
            ForgettingCurve(self._config),
            summarizer,
            self._config,
            metrics=self._metrics,
        )
        self._retrieval = RetrievalPipeline(self._index, embed_client, self._config)
        self._source_index_dirty = False
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
        self._load_source_index()

    def _load_source_index(self) -> None:
        """从磁盘加载 source_event_index，损坏时回退空 dict。"""
        path = self._user_dir / self._SOURCE_INDEX_FILENAME
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                self._source_event_index = data
        except json.JSONDecodeError, OSError:
            pass

    def _save_source_index(self) -> None:
        """持久化 source_event_index 到磁盘。"""
        if not self._source_index_dirty:
            return
        path = self._user_dir / self._SOURCE_INDEX_FILENAME
        path.write_text(
            json.dumps(self._source_event_index, ensure_ascii=False, default=str)
        )
        self._source_index_dirty = False

    def _get_reference_date(self) -> str:
        return resolve_reference_date(self._config, self._index)

    async def _maybe_save(self) -> None:
        """持久化节流：距上次保存 < save_interval_seconds 则跳过。"""
        now = time.monotonic()
        if now - self._last_save_time >= self._config.save_interval_seconds:
            await self._index.save()
            self._last_save_time = now
            self._save_source_index()  # 仅 FAISS 落盘时同步持久化

    # ── 委托方法 ──

    async def write(self, event: MemoryEvent) -> str:
        """写入事件元数据到索引。"""
        await self._ensure_loaded()
        fid = await self._lifecycle.write(event)
        self._retrieval.invalidate_bm25()
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        self._source_event_index.setdefault(date_key, []).append(fid)
        self._source_index_dirty = True
        return fid

    async def write_batch(self, events: list[MemoryEvent]) -> list[str]:
        """批量写入，返回 faiss_id 列表。不触发摘要/遗忘。"""
        await self._ensure_loaded()
        fids = await self._lifecycle.write_batch(events)
        self._retrieval.invalidate_bm25()
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        self._source_event_index.setdefault(date_key, []).extend(fids)
        self._source_index_dirty = True
        return fids

    async def write_interaction(
        self,
        query: str,
        response: str,
        event_type: str = "reminder",
        **kwargs: object,
    ) -> InteractionResult:
        """写入交互记录并关联到当日事件。"""
        await self._ensure_loaded()
        result = await self._lifecycle.write_interaction(
            query,
            response,
            event_type,
            **kwargs,
        )
        self._retrieval.invalidate_bm25()
        # 将 interaction 关联到同 source（同 date_key）的所有事件条目
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        event_ids = self._source_event_index.get(date_key)
        if event_ids is None:
            # 回退：进程启动后当日尚无 write()，全量扫描 metadata
            event_ids = []
            for m in self._index.get_metadata():
                if m.get("source") == date_key and m.get("type") != "daily_summary":
                    fid = m.get("faiss_id")
                    if fid is not None:
                        event_ids.append(str(fid))
            self._source_event_index[date_key] = event_ids
        for eid in event_ids:
            if eid not in self._interaction_map:
                self._interaction_map[eid] = []
            if result.event_id not in self._interaction_map[eid]:
                self._interaction_map[eid].append(result.event_id)
        return result

    async def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """搜索记忆。"""
        await self._ensure_loaded()
        self._metrics.search_count += 1
        if self._index.total == 0:
            self._metrics.search_empty_index_count += 1
            return []
        if self._config.enable_forgetting:
            await self._lifecycle.purge_forgotten(self._index.get_metadata())
        t0 = time.perf_counter()
        results, _updated = await self._retrieval.search(
            query,
            top_k,
            reference_date=self._get_reference_date(),
        )
        elapsed = (time.perf_counter() - t0) * 1000
        self._metrics.search_latency_ms.append(elapsed)
        if not results:
            self._metrics.search_empty_count += 1

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
        触发完整检索管道（索引加载、遗忘判断、metrics 记录）。
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
        """获取最近历史事件列表。"""
        await self._ensure_loaded()
        events = await self._lifecycle.get_history(limit)
        for ev in events:
            faiss_id = ev.id or ""
            if faiss_id in self._interaction_map:
                ev.interaction_ids = self._interaction_map[faiss_id]
        return events

    async def get_event_type(self, event_id: str) -> str | None:
        """按 event_id 查找事件类型。"""
        await self._ensure_loaded()
        return await self._lifecycle.get_event_type(event_id)

    async def update_feedback(
        self,
        event_id: str,
        feedback: FeedbackData,
    ) -> None:
        """记录用户反馈并更新记忆强度。"""
        if self._feedback_store is None:
            self._feedback_store = JSONLinesStore(
                user_dir=self._user_root,
                filename="feedback.jsonl",
            )
        record = {
            "event_id": event_id,
            "action": feedback.action,
            "type": feedback.type,
            "modified_content": feedback.modified_content,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        await self._feedback_store.append(record)
        logger.info(
            "Feedback recorded: event_id=%s action=%s",
            event_id,
            feedback.action,
        )
        await self._lifecycle.update_feedback(event_id, feedback)

    async def finalize_ingestion(self) -> None:
        """摘要 + 遗忘 + 持久化。应在批量写入完成后调用。"""
        await self._ensure_loaded()
        await self._lifecycle.finalize()

    @property
    def metrics(self) -> MemoryBankMetrics:
        """返回可观测性指标实例。"""
        return self._metrics

    async def close(self) -> None:
        """持久化后关闭索引。"""
        self._save_source_index()
        try:
            await self.finalize_ingestion()
        except Exception:
            logger.warning("Failed to finalize ingestion during close", exc_info=True)
            try:
                await self._index.save()
            except Exception:
                logger.warning("Fallback save also failed during close", exc_info=True)
