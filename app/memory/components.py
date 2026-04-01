"""MemoryStore 可组合组件."""

import asyncio
import logging
import math
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.memory.utils import cosine_similarity
from app.models.chat import ChatModel
from app.models.embedding import EmbeddingModel
from app.storage.toml_store import TOMLStore

AGGREGATION_SIMILARITY_THRESHOLD = 0.8
DAILY_SUMMARY_THRESHOLD = 2
OVERALL_SUMMARY_THRESHOLD = 3
SUMMARY_WEIGHT = 0.8
TOP_K = 3

PERSONALITY_SUMMARY_THRESHOLD = 2
OVERALL_PERSONALITY_THRESHOLD = 3

logger = logging.getLogger(__name__)


def forgetting_curve(days_elapsed: int, strength: int) -> float:
    """遗忘曲线衰减函数."""
    if days_elapsed <= 0:
        return 1.0
    if strength <= 0:
        return 0.0
    return math.exp(-days_elapsed / (5 * strength))


SOFT_FORGET_THRESHOLD = 0.15
SOFT_FORGET_STRENGTH = 0


class EventStorage:
    """事件 JSON 文件 CRUD + ID 生成."""

    def __init__(self, data_dir: Path) -> None:
        """初始化事件存储."""
        self._store = TOMLStore(data_dir, Path("events.toml"), list)
        self.data_dir = data_dir

    def generate_id(self) -> str:
        """生成唯一事件 ID."""
        return f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    async def read_events(self) -> list[dict]:
        """读取所有事件."""
        return await self._store.read()

    async def write_events(self, events: list[dict]) -> None:
        """覆写全部事件."""
        await self._store.write(events)

    async def append_event(self, event: MemoryEvent) -> str:
        """追加事件并返回 ID."""
        event = event.model_copy(deep=True)
        event.id = self.generate_id()
        event.created_at = datetime.now(timezone.utc).isoformat()
        await self._store.append(event.model_dump())
        return event.id


class KeywordSearch:
    """关键词大小写不敏感搜索."""

    def search(
        self, query: str, events: list[dict], top_k: int = 10
    ) -> list[SearchResult]:
        """关键词搜索事件."""
        query_lower = query.lower()
        matched = [
            e
            for e in events
            if query_lower in e.get("content", "").lower()
            or query_lower in e.get("description", "").lower()
        ]
        return [SearchResult(event=e) for e in matched[:top_k]]


_strategy_locks: dict[str, asyncio.Lock] = {}
_strategy_locks_lock = asyncio.Lock()


class FeedbackManager:
    """反馈更新 + 策略权重管理."""

    def __init__(self, data_dir: Path) -> None:
        """初始化反馈管理器."""
        self._strategies_store = TOMLStore(data_dir, Path("strategies.toml"), dict)
        self.data_dir = data_dir

    async def _get_lock(self) -> asyncio.Lock:
        async with _strategy_locks_lock:
            if str(self.data_dir) not in _strategy_locks:
                _strategy_locks[str(self.data_dir)] = asyncio.Lock()
            return _strategy_locks[str(self.data_dir)]

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """记录反馈并更新策略权重."""
        feedback.event_id = event_id
        feedback.timestamp = datetime.now(timezone.utc).isoformat()
        feedback_store = TOMLStore(self.data_dir, Path("feedback.toml"), list)
        await feedback_store.append(feedback.model_dump())
        await self._update_strategy(event_id, feedback.model_dump())

    async def _update_strategy(self, event_id: str, feedback: dict) -> None:
        lock = await self._get_lock()
        async with lock:
            strategies = await self._strategies_store.read()
            action = feedback.get("action")
            event_type = feedback.get("type", "default")

            if "reminder_weights" not in strategies:
                strategies["reminder_weights"] = {}

            if action == "accept":
                strategies["reminder_weights"][event_type] = min(
                    strategies["reminder_weights"].get(event_type, 0.5) + 0.1, 1.0
                )
            elif action == "ignore":
                strategies["reminder_weights"][event_type] = max(
                    strategies["reminder_weights"].get(event_type, 0.5) - 0.1, 0.1
                )

            await self._strategies_store.write(strategies)


class SimpleInteractionWriter:
    """简单交互写入（创建 MemoryEvent 写入 EventStorage）."""

    def __init__(self, storage: EventStorage) -> None:
        """初始化交互写入器."""
        self._storage = storage

    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录."""
        event = MemoryEvent(
            content=query,
            type=event_type,
            description=response,
        )
        return await self._storage.append_event(event)


class MemoryBankEngine:
    """记忆库引擎，支持遗忘曲线、记忆强化与自动摘要."""

    EMBEDDING_MIN_SIMILARITY = 0.3

    def __init__(
        self,
        data_dir: Path,
        storage: EventStorage,
        embedding_model: Optional[EmbeddingModel] = None,
        chat_model: Optional[ChatModel] = None,
    ) -> None:
        """初始化记忆库引擎."""
        self.data_dir = data_dir
        self._storage = storage
        self.embedding_model = embedding_model
        self.chat_model = chat_model
        self._interactions_store = TOMLStore(data_dir, Path("interactions.toml"), list)
        self._lock = asyncio.Lock()
        self._default_summaries = {"daily_summaries": {}, "overall_summary": ""}
        self._summaries_store = TOMLStore(
            data_dir,
            Path("memorybank_summaries.toml"),
            lambda: dict(self._default_summaries),
        )
        self._personality_store = TOMLStore(
            data_dir,
            Path("memorybank_personality.toml"),
            lambda: {"daily_personality": {}, "overall_personality": ""},
        )
        self._personality_lock = asyncio.Lock()

    async def write(self, event: MemoryEvent) -> str:
        """写入事件并触发摘要."""
        event = event.model_copy(deep=True)
        event.id = self._storage.generate_id()
        event.created_at = datetime.now(timezone.utc).isoformat()
        today = datetime.now(timezone.utc).date().isoformat()
        event.memory_strength = 1
        event.last_recall_date = today
        event.date_group = today
        await self._storage._store.append(event.model_dump())
        await self._maybe_summarize(today)
        return event.id

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """搜索记忆事件与摘要."""
        if not query.strip():
            return []
        events = await self._storage.read_events()
        summaries = await self._summaries_store.read()
        daily_summaries = summaries.get("daily_summaries", {})
        personality_data = await self._personality_store.read()
        daily_personality = personality_data.get("daily_personality", {})
        if not events and not daily_summaries and not daily_personality:
            return []
        if self.embedding_model is None:
            event_results = await self._search_by_keyword(query, events, top_k)
        else:
            event_results = await self._search_by_embedding(query, events, top_k)
            if not event_results:
                event_results = await self._search_by_keyword(query, events, top_k)
        summary_results = await self._search_summaries(query, daily_summaries, top_k=1)
        personality_results = await self._search_personality(query, top_k=1)
        all_results = event_results + summary_results + personality_results
        all_results.sort(key=lambda x: x.score, reverse=True)
        top_results = all_results[:top_k]
        return await self._expand_event_interactions(top_results)

    def _get_searchable_text(self, event: dict) -> str:
        parts = [event.get("content", ""), event.get("description", "")]
        return "\n".join(p for p in parts if p)

    async def _search_by_keyword(
        self, query: str, events: list[dict], top_k: int
    ) -> list[SearchResult]:
        query_lower = query.lower()
        today = datetime.now(timezone.utc).date()
        results = []
        for event in events:
            searchable_text = self._get_searchable_text(event).lower()
            if query_lower in searchable_text:
                strength = event.get("memory_strength", 1)
                last_recall = event.get("last_recall_date", today.isoformat())
                try:
                    last_date = date.fromisoformat(last_recall)
                    days_elapsed = (today - last_date).days
                except (ValueError, TypeError):
                    days_elapsed = 0
                retention = forgetting_curve(days_elapsed, strength)
                results.append(
                    SearchResult(event=dict(event), score=retention, source="event")
                )
        results.sort(key=lambda x: x.score, reverse=True)
        top_results = results[:top_k]
        await self._strengthen_events([r.event for r in top_results])
        return top_results

    async def _search_by_embedding(
        self, query: str, events: list[dict], top_k: int
    ) -> list[SearchResult]:
        assert self.embedding_model is not None
        query_vector = await self.embedding_model.encode(query)
        event_texts = [self._get_searchable_text(event) for event in events]
        all_event_vectors = await self.embedding_model.batch_encode(event_texts)
        today = datetime.now(timezone.utc).date()
        results = []
        for event, event_vector in zip(events, all_event_vectors):
            similarity = cosine_similarity(query_vector, event_vector)
            strength = event.get("memory_strength", 1)
            last_recall = event.get("last_recall_date", today.isoformat())
            try:
                last_date = date.fromisoformat(last_recall)
                days_elapsed = (today - last_date).days
            except (ValueError, TypeError):
                days_elapsed = 0
            retention = forgetting_curve(days_elapsed, strength)
            score = similarity * retention
            if similarity >= self.EMBEDDING_MIN_SIMILARITY and score > 0:
                results.append(
                    SearchResult(event=dict(event), score=score, source="event")
                )
        results.sort(key=lambda x: x.score, reverse=True)
        top_results = results[:top_k]
        await self._strengthen_events([r.event for r in top_results])
        return top_results

    async def _expand_event_interactions(
        self, results: list[SearchResult]
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

    async def _strengthen_events(self, matched_events: list[dict]) -> None:
        if not matched_events:
            return
        matched_ids = {e["id"] for e in matched_events if "id" in e}
        if not matched_ids:
            return
        all_events = await self._storage.read_events()
        today = datetime.now(timezone.utc).date().isoformat()
        updated = False
        for event in all_events:
            if event.get("id") in matched_ids:
                event["memory_strength"] = event.get("memory_strength", 1) + 1
                event["last_recall_date"] = today
                updated = True
        if updated:
            await self._storage.write_events(all_events)
        await self._strengthen_interactions(matched_ids)
        all_events = await self._storage.read_events()
        await self._soft_forget_events(all_events, matched_ids)

    async def _strengthen_interactions(self, event_ids: set[str]) -> None:
        if not event_ids:
            return
        all_interactions = await self._interactions_store.read()
        today = datetime.now(timezone.utc).date().isoformat()
        updated = False
        for interaction in all_interactions:
            if interaction.get("event_id") in event_ids:
                interaction["memory_strength"] = (
                    interaction.get("memory_strength", 1) + 1
                )
                interaction["last_recall_date"] = today
                updated = True
        if updated:
            await self._interactions_store.write(all_interactions)

    async def _soft_forget_events(
        self, all_events: list[dict], matched_ids: set[str]
    ) -> None:
        """对 retention 过低的记忆执行软遗忘."""
        if not matched_ids:
            return
        today = datetime.now(timezone.utc).date()
        updated = False
        for event in all_events:
            if event.get("id") in matched_ids:
                continue
            strength = event.get("memory_strength", 1)
            last_recall = event.get("last_recall_date", today.isoformat())
            try:
                last_date = date.fromisoformat(last_recall)
                days_elapsed = (today - last_date).days
            except (ValueError, TypeError):
                days_elapsed = 0
            retention = forgetting_curve(days_elapsed, strength)
            if retention < SOFT_FORGET_THRESHOLD:
                event["memory_strength"] = SOFT_FORGET_STRENGTH
                event["forgotten"] = True
                updated = True
        if updated:
            await self._storage.write_events(all_events)

    async def _search_summaries(
        self, query: str, daily_summaries: dict, top_k: int = 1
    ) -> list[SearchResult]:
        if not daily_summaries:
            return []
        query_lower = query.lower()
        today = datetime.now(timezone.utc).date()
        results = []
        matched_keys = []
        for date_group, summary_data in daily_summaries.items():
            if isinstance(summary_data, dict):
                content = summary_data.get("content", "")
                strength = summary_data.get("memory_strength", 1)
                last_recall = summary_data.get("last_recall_date", date_group)
            else:
                content = str(summary_data)
                strength = 1
                last_recall = date_group
            if query_lower in content.lower():
                try:
                    last_date = date.fromisoformat(str(last_recall))
                    days_elapsed = (today - last_date).days
                except (ValueError, TypeError):
                    days_elapsed = 0
                retention = forgetting_curve(days_elapsed, strength)
                score = retention * SUMMARY_WEIGHT
                results.append(
                    SearchResult(
                        event={
                            "content": content,
                            "date_group": date_group,
                            "memory_strength": strength,
                            "last_recall_date": last_recall,
                        },
                        score=score,
                        source="daily_summary",
                    )
                )
                matched_keys.append(date_group)
        results.sort(key=lambda x: x.score, reverse=True)
        await self._strengthen_summaries(matched_keys, daily_summaries)
        return results[:top_k]

    async def _strengthen_summaries(
        self, matched_keys: list[str], daily_summaries: dict
    ) -> None:
        if not matched_keys:
            return
        today = datetime.now(timezone.utc).date().isoformat()
        updated = False
        for key in matched_keys:
            if key in daily_summaries:
                summary_data = daily_summaries[key]
                if isinstance(summary_data, dict):
                    summary_data["memory_strength"] = (
                        summary_data.get("memory_strength", 1) + 1
                    )
                    summary_data["last_recall_date"] = today
                    updated = True
        if updated:
            summaries = await self._summaries_store.read()
            summaries["daily_summaries"] = daily_summaries
            await self._summaries_store.write(summaries)

    async def _search_personality(self, query: str, top_k: int) -> list[SearchResult]:
        """Search personality summaries using keyword matching, retention weight is SUMMARY_WEIGHT * 0.8."""
        personality_data = await self._personality_store.read()
        daily_personality = personality_data.get("daily_personality", {})
        if not daily_personality:
            return []
        query_lower = query.lower()
        today = datetime.now(timezone.utc).date()
        results = []
        matched_date_groups = []
        for date_group, data in daily_personality.items():
            if not isinstance(data, dict):
                continue
            content = data.get("content", "")
            if query_lower in content.lower():
                strength = data.get("memory_strength", 1)
                last_recall = data.get("last_recall_date", date_group)
                try:
                    last_date = date.fromisoformat(last_recall)
                    days_elapsed = (today - last_date).days
                except (ValueError, TypeError):
                    days_elapsed = 0
                retention = forgetting_curve(days_elapsed, strength)
                score = retention * SUMMARY_WEIGHT * 0.8
                results.append(
                    SearchResult(
                        event={
                            "content": content,
                            "date_group": date_group,
                            "memory_strength": strength,
                            "last_recall_date": last_recall,
                        },
                        score=score,
                        source="personality",
                    )
                )
                matched_date_groups.append(date_group)
        results.sort(key=lambda x: x.score, reverse=True)
        await self._strengthen_personality(matched_date_groups, daily_personality)
        return results[:top_k]

    async def _strengthen_personality(
        self, matched_date_groups: list[str], daily_personality: dict
    ) -> None:
        """强化匹配到的人格摘要的 memory_strength 和 last_recall_date."""
        if not matched_date_groups:
            return
        today = datetime.now(timezone.utc).date().isoformat()
        updated = False
        for date_group in matched_date_groups:
            if date_group in daily_personality:
                data = daily_personality[date_group]
                if isinstance(data, dict):
                    data["memory_strength"] = data.get("memory_strength", 1) + 1
                    data["last_recall_date"] = today
                    updated = True
        if updated:
            personality_data = await self._personality_store.read()
            personality_data["daily_personality"] = daily_personality
            await self._personality_store.write(personality_data)

    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录并关联事件."""
        interaction_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        today = datetime.now(timezone.utc).date().isoformat()
        interaction = {
            "id": interaction_id,
            "event_id": "",
            "query": query,
            "response": response,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "memory_strength": 1,
            "last_recall_date": today,
        }

        append_event_id = await self._should_append_to_event(interaction)
        event = None
        if append_event_id:
            interaction["event_id"] = append_event_id
        else:
            event_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
            now_iso = datetime.now(timezone.utc).isoformat()
            event = {
                "id": event_id,
                "content": query,
                "type": event_type,
                "interaction_ids": [interaction_id],
                "created_at": now_iso,
                "updated_at": now_iso,
                "memory_strength": 1,
                "last_recall_date": today,
                "date_group": today,
            }
            interaction["event_id"] = event_id

        await self._interactions_store.append(interaction)

        if append_event_id:
            await self._append_interaction_to_event(append_event_id, interaction_id)
            await self._update_event_summary(append_event_id)
        else:
            await self._storage._store.append(event)

        await self._maybe_summarize(today)
        await self._maybe_summarize_personality(today)
        return interaction_id

    async def _should_append_to_event(self, interaction: dict) -> Optional[str]:
        events = await self._storage.read_events()
        if not events:
            return None
        today = datetime.now(timezone.utc).date().isoformat()
        recent = events[-1]
        if recent.get("date_group") != today:
            return None
        if self.embedding_model:
            query_vec = await self.embedding_model.encode(interaction["query"])
            event_vec = await self.embedding_model.encode(recent.get("content", ""))
            similarity = cosine_similarity(query_vec, event_vec)
            if similarity >= AGGREGATION_SIMILARITY_THRESHOLD:
                return recent["id"]
            return None
        content_lower = recent.get("content", "").lower()
        query_lower = interaction["query"].lower()
        query_chars = list(set(query_lower))
        if not query_chars:
            return None
        overlap = sum(1 for c in query_chars if c in content_lower)
        if overlap / len(query_chars) >= 0.5:
            return recent["id"]
        return None

    async def _append_interaction_to_event(
        self, event_id: str, interaction_id: str
    ) -> None:
        async with self._lock:
            all_events = await self._storage.read_events()
            for event in all_events:
                if event.get("id") == event_id:
                    event.setdefault("interaction_ids", []).append(interaction_id)
                    event["updated_at"] = datetime.now(timezone.utc).isoformat()
                    break
            await self._storage.write_events(all_events)

    async def _update_event_summary(self, event_id: str) -> None:
        if not self.chat_model:
            return
        interactions = await self._interactions_store.read()
        child_interactions = [i for i in interactions if i.get("event_id") == event_id]
        if not child_interactions:
            return
        combined = "\n".join(
            f"用户: {i['query']}\n系统: {i['response']}" for i in child_interactions
        )
        prompt = f"请简洁总结以下交互记录（一句话）：\n{combined}"
        try:
            summary_text = await self.chat_model.generate(prompt)
        except Exception:
            return
        all_events = await self._storage.read_events()
        for event in all_events:
            if event.get("id") == event_id:
                event["content"] = summary_text
                break
        await self._storage.write_events(all_events)

    async def _persist_interaction(self, interaction: dict) -> None:
        all_interactions = await self._interactions_store.read()
        for i, item in enumerate(all_interactions):
            if item["id"] == interaction["id"]:
                all_interactions[i] = interaction
                break
        await self._interactions_store.write(all_interactions)

    async def _maybe_summarize(self, date_group: str) -> None:
        events = await self._storage.read_events()
        group_events = [e for e in events if e.get("date_group") == date_group]
        count = len(group_events)
        if count < DAILY_SUMMARY_THRESHOLD:
            return
        summaries = await self._summaries_store.read()
        daily_summaries = summaries.get("daily_summaries", {})
        latest_source_ts = max(
            (e.get("updated_at") or e.get("created_at", "") for e in group_events),
            default="",
        )
        if date_group in daily_summaries:
            existing = daily_summaries[date_group]
            if (
                isinstance(existing, dict)
                and existing.get("event_count", 0) >= count
                and existing.get("source_updated_at", "") >= latest_source_ts
            ):
                return
        if not self.chat_model:
            return
        content = "\n".join(
            e.get("content", "") for e in group_events if e.get("content")
        )
        prompt = f"请简洁总结以下事件（一句话）：\n{content}"
        try:
            summary_text = await self.chat_model.generate(prompt)
        except Exception:
            return
        daily_summaries[date_group] = {
            "content": summary_text,
            "memory_strength": 1,
            "last_recall_date": date_group,
            "event_count": count,
            "source_updated_at": latest_source_ts,
        }
        summaries["daily_summaries"] = daily_summaries
        await self._summaries_store.write(summaries)
        if len(daily_summaries) >= OVERALL_SUMMARY_THRESHOLD:
            await self._update_overall_summary(daily_summaries, summaries)

    async def _maybe_summarize_personality(self, date_group: str) -> None:
        """每日对话达到阈值时，生成人格分析摘要."""
        if not self.chat_model:
            return
        events = await self._storage.read_events()
        group_events = [e for e in events if e.get("date_group") == date_group]
        interactions = await self._interactions_store.read()
        group_interactions = [
            i
            for i in interactions
            if i.get("event_id") in {e.get("id") for e in group_events}
        ]
        if len(group_interactions) < PERSONALITY_SUMMARY_THRESHOLD:
            return
        latest_source_ts = max(
            (e.get("updated_at") or e.get("created_at", "") for e in group_events),
            default="",
        )
        async with self._personality_lock:
            personality_data = await self._personality_store.read()
            daily_personality = personality_data.get("daily_personality", {})
            if date_group in daily_personality:
                existing = daily_personality[date_group]
                if (
                    isinstance(existing, dict)
                    and existing.get("interaction_count", 0) >= len(group_interactions)
                    and existing.get("source_updated_at", "") >= latest_source_ts
                ):
                    return
            combined = "\n".join(
                f"用户: {i['query']}\n系统: {i['response']}" for i in group_interactions
            )
        prompt = f"""Based on the following dialogue, please summarize user's personality traits and emotions,
        and devise response strategies based on your speculation. Dialogue content:
        {combined}

        User's personality traits, emotions, and response strategy are:
        """
        try:
            summary_text = await self.chat_model.generate(prompt)
        except Exception:
            logger.exception(
                "Failed to generate personality summary for date_group=%s", date_group
            )
            return
        async with self._personality_lock:
            daily_personality[date_group] = {
                "content": summary_text,
                "memory_strength": 1,
                "last_recall_date": date_group,
                "interaction_count": len(group_interactions),
                "source_updated_at": latest_source_ts,
            }
            personality_data["daily_personality"] = daily_personality
            await self._personality_store.write(personality_data)
            if len(daily_personality) >= OVERALL_PERSONALITY_THRESHOLD:
                await self._update_overall_personality(personality_data)

    async def _update_overall_personality(self, personality_data: dict) -> None:
        """汇总多条每日人格分析为整体人格档案."""
        if not self.chat_model:
            return
        daily_personality = personality_data.get("daily_personality", {})
        all_summaries = [
            f"[{date_group}] {data.get('content', '')}"
            for date_group, data in daily_personality.items()
            if isinstance(data, dict)
        ]
        combined = "\n".join(all_summaries)
        prompt = f"""The following are the user's exhibited personality traits and emotions throughout multiple dialogues,
along with appropriate response strategies for the current situation:
{combined}

Please provide a highly concise and general summary of the user's personality and the most appropriate
response strategy for the AI lover, summarized as:
"""
        try:
            overall = await self.chat_model.generate(prompt)
        except Exception:
            logger.exception("Failed to generate overall personality summary")
            return
        personality_data["overall_personality"] = overall
        await self._personality_store.write(personality_data)

    async def _update_overall_summary(
        self, daily_summaries: dict, summaries: dict
    ) -> None:
        if not self.chat_model:
            return
        all_summaries = []
        for date_group, summary_data in daily_summaries.items():
            if isinstance(summary_data, dict):
                all_summaries.append(
                    f"[{date_group}] {summary_data.get('content', '')}"
                )
            else:
                all_summaries.append(f"[{date_group}] {summary_data}")
        combined = "\n".join(all_summaries)
        prompt = f"请简洁总结以下每日摘要（两到三句话）：\n{combined}"
        try:
            overall = await self.chat_model.generate(prompt)
        except Exception:
            return
        summaries["overall_summary"] = overall
        await self._summaries_store.write(summaries)
