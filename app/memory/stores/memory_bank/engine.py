"""MemoryBankEngine: 记忆库引擎，支持遗忘曲线、记忆强化与自动摘要."""

import asyncio
import logging
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.memory.components import EventStorage, forgetting_curve
from app.memory.schemas import InteractionResult, MemoryEvent, SearchResult
from app.memory.stores.memory_bank.personality import PersonalityManager
from app.memory.stores.memory_bank.summarization import SummaryManager
from app.memory.utils import cosine_similarity
from app.storage.toml_store import TOMLStore

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)


class EmbeddingModelRequiredError(RuntimeError):
    """向量搜索需要 embedding_model."""

    def __init__(self) -> None:
        """初始化错误."""
        super().__init__("embedding_model is required for vector search")


AGGREGATION_SIMILARITY_THRESHOLD = 0.8
OVERLAP_RATIO_THRESHOLD = 0.45
TOP_K = 3
SOFT_FORGET_THRESHOLD = 0.15
SOFT_FORGET_STRENGTH = 0


class MemoryBankEngine:
    """记忆库引擎，支持遗忘曲线、记忆强化与自动摘要."""

    EMBEDDING_MIN_SIMILARITY = 0.3

    def __init__(
        self,
        data_dir: Path,
        storage: EventStorage,
        embedding_model: EmbeddingModel | None = None,
        chat_model: ChatModel | None = None,
    ) -> None:
        """初始化记忆库引擎."""
        self.data_dir = data_dir
        self._storage = storage
        self.embedding_model = embedding_model
        self.chat_model = chat_model
        self._interactions_store = TOMLStore(data_dir, Path("interactions.toml"), list)
        self._lock = asyncio.Lock()
        self._personality_mgr = PersonalityManager(data_dir)
        self._summary_mgr = SummaryManager(data_dir)

    @property
    def summaries_store(self) -> TOMLStore:
        """摘要存储."""
        return self._summary_mgr.summaries_store

    @property
    def personality_store(self) -> TOMLStore:
        """人格存储."""
        return self._personality_mgr.personality_store

    @property
    def interactions_store(self) -> TOMLStore:
        """交互存储."""
        return self._interactions_store

    async def write(self, event: MemoryEvent) -> str:
        """写入事件并触发摘要."""
        event = event.model_copy(deep=True)
        event.id = self._storage.generate_id()
        event.created_at = datetime.now(UTC).isoformat()
        today = datetime.now(UTC).date().isoformat()
        event.memory_strength = 1
        event.last_recall_date = today
        event.date_group = today
        await self._storage.append_raw(event.model_dump())
        events = await self._storage.read_events()
        group_events = [e for e in events if e.get("date_group") == today]
        await self._summary_mgr.maybe_summarize(today, group_events, self.chat_model)
        return event.id

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """搜索记忆事件与摘要."""
        if not query.strip():
            return []
        events = await self._storage.read_events()
        summaries = await self.summaries_store.read()
        daily_summaries = summaries.get("daily_summaries", {})
        personality_data = await self.personality_store.read()
        daily_personality = personality_data.get("daily_personality", {})
        if not events and not daily_summaries and not daily_personality:
            return []
        if self.embedding_model is None:
            event_results = await self._search_by_keyword(query, events, top_k)
        else:
            event_results = await self._safe_embedding_search(query, events, top_k)
            if event_results is None or len(event_results) == 0:
                event_results = await self._search_by_keyword(query, events, top_k)
        summary_results = await self._summary_mgr.search_summaries(
            query,
            daily_summaries,
            top_k=1,
        )
        personality_results = await self._personality_mgr.search(query, top_k=1)
        all_results = event_results + summary_results + personality_results
        all_results.sort(key=lambda x: x.score, reverse=True)
        top_results = all_results[:top_k]

        event_ids = {
            r.event["id"]
            for r in top_results
            if r.source == "event" and "id" in r.event
        }
        summary_keys: list[str] = list(
            {
                r.event["date_group"]
                for r in top_results
                if r.source == "daily_summary" and "date_group" in r.event
            },
        )
        personality_keys: list[str] = list(
            {
                r.event["date_group"]
                for r in top_results
                if r.source == "personality" and "date_group" in r.event
            },
        )

        if event_ids:
            await self._strengthen_matched(event_ids)
        if summary_keys:
            await self._summary_mgr.strengthen_summaries(summary_keys)
        if personality_keys:
            await self._personality_mgr.strengthen(personality_keys)

        return await self._expand_event_interactions(top_results)

    def _get_searchable_text(self, event: dict) -> str:
        parts = [event.get("content", ""), event.get("description", "")]
        return "\n".join(p for p in parts if p)

    async def _search_by_keyword(
        self,
        query: str,
        events: list[dict],
        top_k: int,
    ) -> list[SearchResult]:
        query_lower = query.lower()
        today = datetime.now(UTC).date()
        results = []
        for event in events:
            searchable_text = self._get_searchable_text(event).lower()
            if query_lower not in searchable_text:
                continue
            strength = event.get("memory_strength", 1)
            last_recall = event.get("last_recall_date", today.isoformat())
            try:
                last_date = date.fromisoformat(last_recall)
                days_elapsed = (today - last_date).days
            except ValueError, TypeError:
                days_elapsed = 0
            retention = forgetting_curve(days_elapsed, strength)
            if retention <= 0:
                continue
            results.append(
                SearchResult(event=dict(event), score=retention, source="event"),
            )
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    async def _safe_embedding_search(
        self,
        query: str,
        events: list[dict],
        top_k: int,
    ) -> list[SearchResult] | None:
        """尝试向量搜索，失败时返回 None 以触发关键字回退."""
        try:
            return await self._search_by_embedding(query, events, top_k)
        except (OSError, RuntimeError) as e:
            logger.warning("Embedding search failed, fallback to keyword: %s", e)
            return None

    async def _search_by_embedding(
        self,
        query: str,
        events: list[dict],
        top_k: int,
    ) -> list[SearchResult]:
        if self.embedding_model is None:
            raise EmbeddingModelRequiredError
        query_vector = await self.embedding_model.encode(query)
        event_text_pairs = [
            (event, text)
            for event in events
            if (text := self._get_searchable_text(event)).strip()
        ]
        if not event_text_pairs:
            return []
        all_event_vectors = await self.embedding_model.batch_encode(
            [text for _, text in event_text_pairs]
        )
        today = datetime.now(UTC).date()
        results = []
        for (event, _text), event_vector in zip(
            event_text_pairs, all_event_vectors, strict=True
        ):
            similarity = cosine_similarity(query_vector, event_vector)
            strength = event.get("memory_strength", 1)
            last_recall = event.get("last_recall_date", today.isoformat())
            try:
                last_date = date.fromisoformat(last_recall)
                days_elapsed = (today - last_date).days
            except ValueError, TypeError:
                days_elapsed = 0
            retention = forgetting_curve(days_elapsed, strength)
            score = similarity * retention
            if similarity >= self.EMBEDDING_MIN_SIMILARITY and score > 0:
                results.append(
                    SearchResult(event=dict(event), score=score, source="event"),
                )
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    async def _expand_event_interactions(
        self,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        interactions = await self._interactions_store.read()
        interaction_by_event: dict[str, list[dict]] = {}
        for i in interactions:
            eid = i.get("event_id", "")
            if eid:
                interaction_by_event.setdefault(eid, []).append(i)
        for result in results:
            eid = result.event.get("id", "")
            result.interactions = interaction_by_event.get(eid, [])
        return results

    async def _strengthen_matched(self, matched_ids: set[str]) -> None:
        """强化匹配事件的记忆强度（不含遗忘逻辑）."""
        if not matched_ids:
            return
        today = datetime.now(UTC).date().isoformat()
        async with self._lock:
            all_events = await self._storage.read_events()
            updated = False
            for event in all_events:
                if event.get("id") in matched_ids:
                    event["memory_strength"] = event.get("memory_strength", 1) + 1
                    event["last_recall_date"] = today
                    updated = True
            if updated:
                await self._storage.write_events(all_events)

            all_interactions = await self._interactions_store.read()
            updated = False
            for interaction in all_interactions:
                if interaction.get("event_id") in matched_ids:
                    interaction["memory_strength"] = (
                        interaction.get("memory_strength", 1) + 1
                    )
                    interaction["last_recall_date"] = today
                    updated = True
            if updated:
                await self._interactions_store.write(all_interactions)

    async def forget_expired(self) -> None:
        """遗忘过期事件（独立于搜索流程，由外部按需调用）."""
        today_date = datetime.now(UTC).date()
        async with self._lock:
            all_events = await self._storage.read_events()
            updated = False
            for event in all_events:
                if event.get("forgotten"):
                    continue
                strength = event.get("memory_strength", 1)
                last_recall = event.get("last_recall_date", today_date.isoformat())
                try:
                    last_date = date.fromisoformat(last_recall)
                    days_elapsed = (today_date - last_date).days
                except ValueError, TypeError:
                    days_elapsed = 0
                retention = forgetting_curve(days_elapsed, strength)
                if retention < SOFT_FORGET_THRESHOLD:
                    event["memory_strength"] = SOFT_FORGET_STRENGTH
                    event["forgotten"] = True
                    updated = True
            if updated:
                await self._storage.write_events(all_events)

    async def write_interaction(
        self,
        query: str,
        response: str,
        event_type: str = "reminder",
    ) -> InteractionResult:
        """写入交互记录并关联事件."""
        interaction_id = (
            f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        )
        today = datetime.now(UTC).date().isoformat()
        interaction = {
            "id": interaction_id,
            "event_id": "",
            "query": query,
            "response": response,
            "timestamp": datetime.now(UTC).isoformat(),
            "memory_strength": 1,
            "last_recall_date": today,
        }

        async with self._lock:
            append_event_id = await self._should_append_to_event(interaction)
            event = None
            resolved_event_id = ""
            if append_event_id:
                interaction["event_id"] = append_event_id
                resolved_event_id = append_event_id
            else:
                new_event_id = f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
                now_iso = datetime.now(UTC).isoformat()
                event = {
                    "id": new_event_id,
                    "content": query,
                    "type": event_type,
                    "interaction_ids": [interaction_id],
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "memory_strength": 1,
                    "last_recall_date": today,
                    "date_group": today,
                }
                interaction["event_id"] = new_event_id
                resolved_event_id = new_event_id

            await self._interactions_store.append(interaction)

            if append_event_id:
                all_events = await self._storage.read_events()
                for ev in all_events:
                    if ev.get("id") == append_event_id:
                        ev.setdefault("interaction_ids", []).append(interaction_id)
                        ev["updated_at"] = datetime.now(UTC).isoformat()
                        break
                await self._storage.write_events(all_events)
            elif event is not None:
                await self._storage.append_raw(event)

        if append_event_id:
            await self._update_event_summary(append_event_id)

        events = await self._storage.read_events()
        group_events = [e for e in events if e.get("date_group") == today]
        await self._summary_mgr.maybe_summarize(today, group_events, self.chat_model)
        interactions = await self._interactions_store.read()
        await self._personality_mgr.maybe_summarize(
            today,
            events,
            interactions,
            self.chat_model,
        )
        return InteractionResult(
            event_id=resolved_event_id,
            interaction_id=interaction_id,
        )

    async def _should_append_to_event(self, interaction: dict) -> str | None:
        """判断交互是否应追加到当日某条已有事件（扫描全部当日事件，取最高相似度）."""
        events = await self._storage.read_events()
        if not events:
            return None
        today = datetime.now(UTC).date().isoformat()
        today_events = [e for e in events if e.get("date_group") == today]
        if not today_events:
            return None
        if self.embedding_model:
            query_vec = await self.embedding_model.encode(interaction["query"])
            best_id = None
            best_sim = AGGREGATION_SIMILARITY_THRESHOLD
            for event in today_events:
                event_vec = await self.embedding_model.encode(event.get("content", ""))
                similarity = cosine_similarity(query_vec, event_vec)
                if similarity >= best_sim:
                    best_sim = similarity
                    best_id = event["id"]
            return best_id
        query_lower = interaction["query"].lower()
        query_chars = list(set(query_lower))
        if not query_chars:
            return None
        best_id = None
        best_overlap = OVERLAP_RATIO_THRESHOLD
        for event in today_events:
            content_lower = event.get("content", "").lower()
            overlap = sum(1 for c in query_chars if c in content_lower) / len(
                query_chars,
            )
            if overlap >= best_overlap:
                best_overlap = overlap
                best_id = event["id"]
        return best_id

    async def _update_event_summary(self, event_id: str) -> None:
        if not self.chat_model:
            return
        interactions = await self._interactions_store.read()
        child_interactions = [i for i in interactions if i.get("event_id") == event_id]
        if not child_interactions:
            return
        combined = "\n".join(
            f"用户: {i.get('query', '')}\n系统: {i.get('response', '')}"
            for i in child_interactions
        )
        prompt = f"请简洁总结以下交互记录（一句话）：\n{combined}"
        try:
            summary_text = await self.chat_model.generate(prompt)
        except OSError, ValueError, RuntimeError:
            return
        async with self._lock:
            all_events = await self._storage.read_events()
            for event in all_events:
                if event.get("id") == event_id:
                    event["content"] = summary_text
                    event["updated_at"] = datetime.now(UTC).isoformat()
                    break
            await self._storage.write_events(all_events)
