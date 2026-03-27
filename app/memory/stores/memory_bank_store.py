"""记忆库后端，实现基于遗忘曲线的记忆存储、聚合与摘要功能."""

import math
import uuid
from datetime import date, datetime
from typing import Optional

from app.memory.stores.base import BaseMemoryStore
from app.models.chat import ChatModel
from app.models.embedding import EmbeddingModel
from app.storage.json_store import JSONStore
from app.memory.utils import cosine_similarity

AGGREGATION_SIMILARITY_THRESHOLD = 0.8
DAILY_SUMMARY_THRESHOLD = 5
OVERALL_SUMMARY_THRESHOLD = 3
SUMMARY_WEIGHT = 0.8
TOP_K = 3


def forgetting_curve(days_elapsed: int, strength: int) -> float:
    """根据艾宾浩斯遗忘曲线计算记忆保留率."""
    if days_elapsed <= 0:
        return 1.0
    return math.exp(-days_elapsed / (5 * strength))


class MemoryBankStore(BaseMemoryStore):

    """记忆库后端，支持遗忘曲线、记忆强化与自动摘要."""

    @property
    def store_name(self) -> str:
        """返回 store 名称."""
        return "memorybank"

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional[EmbeddingModel] = None,
        chat_model: Optional[ChatModel] = None,
    ):
        """初始化记忆库后端."""
        super().__init__(data_dir)
        self.embedding_model = embedding_model
        self.chat_model = chat_model
        self.interactions_store = JSONStore(data_dir, "interactions.json", list)
        self._default_summaries = {"daily_summaries": {}, "overall_summary": ""}
        self.summaries_store = JSONStore(
            data_dir,
            "memorybank_summaries.json",
            lambda: dict(self._default_summaries),
        )

    def write(self, event: dict) -> str:
        """写入事件并触发可能的每日摘要生成."""
        event_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        today = date.today().isoformat()
        event["id"] = event_id
        event["created_at"] = datetime.now().isoformat()
        event["memory_strength"] = 1
        event["last_recall_date"] = today
        event["date_group"] = today
        self.events_store.append(event)
        self._maybe_summarize(today)
        return event_id

    def search(self, query: str, top_k: int = TOP_K) -> list[dict]:
        """根据查询检索相关事件和摘要."""
        if not query.strip():
            return []
        events = self.events_store.read()
        summaries = self.summaries_store.read()
        daily_summaries = summaries.get("daily_summaries", {})
        if not events and not daily_summaries:
            return []
        if self.embedding_model is None:
            event_results = self._search_by_keyword(query, events, top_k)
        else:
            event_results = self._search_by_embedding(query, events, top_k)
        summary_results = self._search_summaries(query, daily_summaries, top_k=1)
        all_results = event_results + summary_results
        all_results.sort(key=lambda x: x.get("_score", 0.0), reverse=True)
        top_results = all_results[:top_k]
        return self._expand_event_interactions(top_results)

    def _search_by_keyword(
        self, query: str, events: list[dict], top_k: int
    ) -> list[dict]:
        query_lower = query.lower()
        today = date.today()
        results = []
        for event in events:
            content = event.get("content", "").lower()
            if query_lower in content:
                strength = event.get("memory_strength", 1)
                last_recall = event.get("last_recall_date", today.isoformat())
                try:
                    last_date = date.fromisoformat(last_recall)
                    days_elapsed = (today - last_date).days
                except (ValueError, TypeError):
                    days_elapsed = 0
                retention = forgetting_curve(days_elapsed, strength)
                scored = dict(event)
                scored["_score"] = retention
                results.append(scored)
        results.sort(key=lambda x: x["_score"], reverse=True)
        top_results = results[:top_k]
        self._strengthen_events(top_results)
        return top_results

    def _search_by_embedding(
        self, query: str, events: list[dict], top_k: int
    ) -> list[dict]:
        assert self.embedding_model is not None
        query_vector = self.embedding_model.encode(query)
        event_texts = [event.get("content", "") for event in events]
        all_event_vectors = self.embedding_model.batch_encode(event_texts)
        today = date.today()
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
            if score > 0:
                scored = dict(event)
                scored["_score"] = score
                results.append(scored)
        results.sort(key=lambda x: x["_score"], reverse=True)
        top_results = results[:top_k]
        self._strengthen_events(top_results)
        return top_results

    def _expand_event_interactions(self, results: list[dict]) -> list[dict]:
        interactions = self.interactions_store.read()
        interaction_by_event: dict[str, list[dict]] = {}
        for i in interactions:
            eid = i.get("event_id", "")
            if eid:
                interaction_by_event.setdefault(eid, []).append(i)
        for result in results:
            eid = result.get("id", "")
            result["interactions"] = interaction_by_event.get(eid, [])
        return results

    def _strengthen_interactions(self, event_ids: set[str]) -> None:
        if not event_ids:
            return
        all_interactions = self.interactions_store.read()
        today = date.today().isoformat()
        updated = False
        for interaction in all_interactions:
            if interaction.get("event_id") in event_ids:
                interaction["memory_strength"] = (
                    interaction.get("memory_strength", 1) + 1
                )
                interaction["last_recall_date"] = today
                updated = True
        if updated:
            self.interactions_store.write(all_interactions)

    def _strengthen_events(self, matched_events: list[dict]) -> None:
        if not matched_events:
            return
        matched_ids = {e["id"] for e in matched_events if "id" in e}
        if not matched_ids:
            return
        all_events = self.events_store.read()
        today = date.today().isoformat()
        updated = False
        for event in all_events:
            if event.get("id") in matched_ids:
                event["memory_strength"] = event.get("memory_strength", 1) + 1
                event["last_recall_date"] = today
                updated = True
        if updated:
            self.events_store.write(all_events)
        for event in matched_events:
            if "id" in event:
                event["memory_strength"] = event.get("memory_strength", 1) + 1
                event["last_recall_date"] = today
        self._strengthen_interactions(matched_ids)

    def _search_summaries(
        self, query: str, daily_summaries: dict, top_k: int = 1
    ) -> list[dict]:
        if not daily_summaries:
            return []
        query_lower = query.lower()
        today = date.today()
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
                    {
                        "_source": "daily_summary",
                        "_score": score,
                        "content": content,
                        "date_group": date_group,
                        "memory_strength": strength,
                        "last_recall_date": last_recall,
                    }
                )
                matched_keys.append(date_group)
        results.sort(key=lambda x: x["_score"], reverse=True)
        self._strengthen_summaries(matched_keys, daily_summaries)
        return results[:top_k]

    def _strengthen_summaries(
        self, matched_keys: list[str], daily_summaries: dict
    ) -> None:
        if not matched_keys:
            return
        today = date.today().isoformat()
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
            summaries = self.summaries_store.read()
            summaries["daily_summaries"] = daily_summaries
            self.summaries_store.write(summaries)

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录，自动聚合到已有事件或创建新事件."""
        interaction_id = (
            f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        )
        today = date.today().isoformat()
        interaction = {
            "id": interaction_id,
            "event_id": "",
            "query": query,
            "response": response,
            "timestamp": datetime.now().isoformat(),
            "memory_strength": 1,
            "last_recall_date": today,
        }
        self.interactions_store.append(interaction)

        append_event_id = self._should_append_to_event(interaction)
        if append_event_id:
            interaction["event_id"] = append_event_id
            self._append_interaction_to_event(append_event_id, interaction_id)
            self._update_event_summary(append_event_id)
        else:
            event_id = (
                f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
            )
            now_iso = datetime.now().isoformat()
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
            self.events_store.append(event)
            interaction["event_id"] = event_id

        self._persist_interaction(interaction)
        self._maybe_summarize(today)
        return interaction_id

    def _should_append_to_event(self, interaction: dict) -> Optional[str]:
        events = self.events_store.read()
        if not events:
            return None
        today = date.today().isoformat()
        recent = events[-1]
        if recent.get("date_group") != today:
            return None
        if self.embedding_model:
            query_vec = self.embedding_model.encode(interaction["query"])
            event_vec = self.embedding_model.encode(recent.get("content", ""))
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

    def _append_interaction_to_event(self, event_id: str, interaction_id: str) -> None:
        all_events = self.events_store.read()
        for event in all_events:
            if event.get("id") == event_id:
                event.setdefault("interaction_ids", []).append(interaction_id)
                event["updated_at"] = datetime.now().isoformat()
                break
        self.events_store.write(all_events)

    def _update_event_summary(self, event_id: str) -> None:
        if not self.chat_model:
            return
        interactions = self.interactions_store.read()
        child_interactions = [i for i in interactions if i.get("event_id") == event_id]
        if not child_interactions:
            return
        combined = "\n".join(
            f"用户: {i['query']}\n系统: {i['response']}" for i in child_interactions
        )
        prompt = f"请简洁总结以下交互记录（一句话）：\n{combined}"
        try:
            summary_text = self.chat_model.generate(prompt)
        except Exception:
            return
        all_events = self.events_store.read()
        for event in all_events:
            if event.get("id") == event_id:
                event["content"] = summary_text
                break
        self.events_store.write(all_events)

    def _persist_interaction(self, interaction: dict) -> None:
        all_interactions = self.interactions_store.read()
        for i, item in enumerate(all_interactions):
            if item["id"] == interaction["id"]:
                all_interactions[i] = interaction
                break
        self.interactions_store.write(all_interactions)

    def _maybe_summarize(self, date_group: str) -> None:
        events = self.events_store.read()
        group_events = [e for e in events if e.get("date_group") == date_group]
        count = len(group_events)
        if count < DAILY_SUMMARY_THRESHOLD:
            return
        summaries = self.summaries_store.read()
        daily_summaries = summaries.get("daily_summaries", {})
        if date_group in daily_summaries:
            existing = daily_summaries[date_group]
            if isinstance(existing, dict) and existing.get("event_count", 0) >= count:
                return
        if not self.chat_model:
            return
        content = "\n".join(
            e.get("content", "") for e in group_events if e.get("content")
        )
        prompt = f"请简洁总结以下事件（一句话）：\n{content}"
        try:
            summary_text = self.chat_model.generate(prompt)
        except Exception:
            return
        daily_summaries[date_group] = {
            "content": summary_text,
            "memory_strength": 1,
            "last_recall_date": date_group,
            "event_count": count,
        }
        summaries["daily_summaries"] = daily_summaries
        self.summaries_store.write(summaries)
        if len(daily_summaries) >= OVERALL_SUMMARY_THRESHOLD:
            self._update_overall_summary(daily_summaries, summaries)

    def _update_overall_summary(self, daily_summaries: dict, summaries: dict) -> None:
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
            overall = self.chat_model.generate(prompt)
        except Exception:
            return
        summaries["overall_summary"] = overall
        self.summaries_store.write(summaries)
