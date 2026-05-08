"""基于 FAISS 的记忆存储，MemoryStore Protocol 实现。"""

import asyncio
import contextlib
import logging
import os
import random
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.memory.components import FeedbackManager
from app.memory.embedding_client import EmbeddingClient
from app.memory.schemas import (
    FeedbackData,
    InteractionResult,
    MemoryEvent,
    SearchResult,
)

from .faiss_index import FaissIndex
from .forget import (
    ForgetMode,
    compute_forget_ids,
    compute_reference_date,
)
from .llm import LlmClient
from .retrieval import (
    apply_speaker_filter,
    clean_search_result,
    deduplicate_overlaps,
    get_effective_chunk_size,
    merge_neighbors,
    update_memory_strengths,
)
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
        **kwargs: object,
    ) -> None:
        seed_raw = os.getenv("MEMORYBANK_SEED")
        seed = None
        if seed_raw is not None:
            try:
                seed = int(seed_raw)
            except ValueError:
                logger.warning("MEMORYBANK_SEED=%r 无法解析为整数", seed_raw)

        self._index = FaissIndex(data_dir)
        self._embedding = EmbeddingClient(embedding_model) if embedding_model else None
        self._llm = LlmClient(chat_model) if chat_model else None
        self._summarizer = Summarizer(self._llm, self._index) if self._llm else None
        self._feedback = FeedbackManager(data_dir)
        self._forgetting_enabled = os.getenv(
            "MEMORYBANK_ENABLE_FORGETTING", "0"
        ).lower() in (
            "1",
            "true",
            "yes",
        )
        self._rng = random.Random(seed)
        self._reference_date = kwargs.get("reference_date")
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        if not self._loaded:
            await self._index.load()
            self._loaded = True

    def _forget_mode(self) -> ForgetMode:
        return ForgetMode.DETERMINISTIC

    async def _apply_forget(self, user_id: str) -> None:
        if not self._forgetting_enabled:
            return
        metadata = self._index.get_metadata(user_id)
        if not metadata:
            return
        ref = self._reference_date or compute_reference_date(metadata)
        ids = compute_forget_ids(metadata, ref, mode=self._forget_mode(), rng=self._rng)
        if ids:
            await self._index.remove_vectors(user_id, ids)
            await self._index.save(user_id)

    async def write_interaction(
        self,
        query: str,
        response: str,
        event_type: str = "reminder",
        *,
        user_id: str = "default",
        **kwargs: object,
    ) -> InteractionResult:
        if not self._embedding:
            msg = "embedding_client required"
            raise RuntimeError(msg)
        await self._ensure_loaded()

        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        ts = datetime.now(UTC).isoformat()
        user_name = kwargs.get("user_name") or "User"
        ai_name = kwargs.get("ai_name") or "AI"
        text = (
            f"Conversation content on {date_key}:"
            f"[|{user_name}|]: {query}; [|{ai_name}|]: {response}"
        )

        emb = await self._embedding.encode(text)
        fid = await self._index.add_vector(
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

        if self._forgetting_enabled:
            metadata = self._index.get_metadata(user_id)
            ref = self._reference_date or compute_reference_date(metadata)
            ids = compute_forget_ids(
                metadata, ref, mode=self._forget_mode(), rng=self._rng
            )
            if ids:
                await self._index.remove_vectors(user_id, ids)
                await self._index.save(user_id)

        await self._index.save(user_id)

        if self._summarizer and self._embedding:
            task = asyncio.create_task(self._background_summarize(user_id, date_key))
            _background_tasks.add(task)
            task.add_done_callback(_finalize_task)

        return InteractionResult(event_id=str(fid))

    async def _background_summarize(self, user_id: str, date_key: str) -> None:
        if not self._summarizer or not self._embedding:
            return
        try:
            text = await self._summarizer.generate_daily_summary(user_id, date_key)
            if text:
                emb = await self._embedding.encode(text)
                await self._index.add_vector(
                    user_id,
                    text,
                    emb,
                    f"{date_key}T00:00:00",
                    {"type": "daily_summary", "source": f"summary_{date_key}"},
                )
                await self._index.save(user_id)

            overall = await self._summarizer.generate_overall_summary(user_id)
            if overall:
                emb = await self._embedding.encode(overall)
                await self._index.add_vector(
                    user_id,
                    overall,
                    emb,
                    f"{date_key}T00:00:00",
                    {"type": "overall_summary", "source": f"summary_{date_key}"},
                )
                await self._index.save(user_id)

            dp = await self._summarizer.generate_daily_personality(user_id, date_key)
            if dp:
                extra = dict(self._index.get_extra(user_id))
                daily_p = dict(extra.get("daily_personalities", {}))
                daily_p[date_key] = dp
                extra["daily_personalities"] = daily_p
                self._index.set_extra(user_id, extra)
                await self._index.save(user_id)

            op = await self._summarizer.generate_overall_personality(user_id)
            if op:
                extra = dict(self._index.get_extra(user_id))
                extra["overall_personality"] = op
                self._index.set_extra(user_id, extra)
                await self._index.save(user_id)

            overall_text = await self._summarizer.generate_overall_summary(user_id)
            if overall_text:
                extra = dict(self._index.get_extra(user_id))
                extra["overall_summary"] = overall_text
                self._index.set_extra(user_id, extra)
                await self._index.save(user_id)

        except Exception:
            logger.exception("background summarization failed")

    async def search(
        self,
        query: str,
        top_k: int = 10,
        *,
        user_id: str = "default",
    ) -> list[SearchResult]:
        if not self._embedding:
            return []
        await self._ensure_loaded()

        if self._index.total(user_id) == 0:
            return []

        await self._apply_forget(user_id)

        query_emb = await self._embedding.encode(query)
        raw = await self._index.search(user_id, query_emb, top_k * 4)

        metadata = self._index.get_metadata(user_id)
        chunk_size = get_effective_chunk_size(metadata)
        merged = merge_neighbors(raw, metadata, chunk_size)
        merged = deduplicate_overlaps(merged)
        merged = apply_speaker_filter(
            merged, query, self._index.get_all_speakers(user_id)
        )
        merged.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        merged = merged[:top_k]

        if update_memory_strengths(merged, metadata, self._reference_date):
            await self._index.save(user_id)

        for r in merged:
            clean_search_result(r)

        extra = self._index.get_extra(user_id)
        prepend_parts: list[str] = []
        for key, label in [
            ("overall_summary", "Overall summary of past memories"),
            ("overall_personality", "User vehicle preferences and habits"),
        ]:
            val = extra.get(key, "")
            if val and val != GENERATION_EMPTY:
                prepend_parts.append(f"{label}: {val}")

        out: list[SearchResult] = []
        if prepend_parts:
            out.append(
                SearchResult(
                    event={
                        "content": "\n".join(prepend_parts),
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
            for r in merged[: max(0, top_k - len(prepend_parts))]
        )
        return out

    async def write(
        self,
        event: MemoryEvent,
        *,
        user_id: str = "default",
    ) -> str:
        if not self._embedding:
            msg = "embedding_client required"
            raise RuntimeError(msg)
        await self._ensure_loaded()

        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        ts = datetime.now(UTC).isoformat()

        lines = [line.strip() for line in event.content.split("\n") if line.strip()]
        parsed_pairs: list[tuple[str | None, str]] = [
            FaissIndex.parse_speaker_line(ln) for ln in lines
        ]
        has_speakers = any(spk is not None for spk, _ in parsed_pairs)

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
                emb = await self._embedding.encode(conv_text)
                fid = await self._index.add_vector(
                    user_id,
                    conv_text,
                    emb,
                    ts,
                    {
                        "source": date_key,
                        "speakers": sorted({s for s in speakers if s is not None}),
                        "raw_content": conv_text,
                        "event_type": event.type,
                    },
                )
        else:
            spk = event.speaker or "System"
            conv_text = f"Conversation content on {date_key}:[|{spk}|]: {event.content}"
            emb = await self._embedding.encode(conv_text)
            fid = await self._index.add_vector(
                user_id,
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
            metadata = self._index.get_metadata(user_id)
            ref = self._reference_date or compute_reference_date(metadata)
            ids = compute_forget_ids(
                metadata, ref, mode=self._forget_mode(), rng=self._rng
            )
            if ids:
                await self._index.remove_vectors(user_id, ids)
                await self._index.save(user_id)

        await self._index.save(user_id)

        if self._summarizer and self._embedding:
            task = asyncio.create_task(self._background_summarize(user_id, date_key))
            _background_tasks.add(task)
            task.add_done_callback(_finalize_task)

        return str(fid)

    async def get_history(
        self,
        limit: int = 10,
        *,
        user_id: str = "default",
    ) -> list[MemoryEvent]:
        await self._ensure_loaded()
        entries = [
            m
            for m in self._index.get_metadata(user_id)
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

    async def update_feedback(
        self,
        event_id: str,
        feedback: FeedbackData,
    ) -> None:
        await self._feedback.update_feedback(event_id, feedback)

    async def get_event_type(
        self,
        event_id: str,
        *,
        user_id: str = "default",
    ) -> str | None:
        await self._ensure_loaded()
        try:
            fid = int(event_id)
        except ValueError, TypeError:
            return None
        m = self._index.get_metadata_by_id(user_id, fid)
        if m is not None:
            return m.get("event_type") or "reminder"
        return None
