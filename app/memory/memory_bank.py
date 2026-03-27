import math
import uuid
from datetime import date, datetime
from typing import Optional

from app.models.chat import ChatModel
from app.models.embedding import EmbeddingModel
from app.storage.json_store import JSONStore

DAILY_SUMMARY_THRESHOLD = 5
OVERALL_SUMMARY_THRESHOLD = 3
SUMMARY_WEIGHT = 0.8
TOP_K = 3


def forgetting_curve(days_elapsed: int, strength: int) -> float:
    if days_elapsed <= 0:
        return 1.0
    return math.exp(-days_elapsed / (5 * strength))


class MemoryBankBackend:
    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional[EmbeddingModel] = None,
        chat_model: Optional[ChatModel] = None,
    ):
        self.embedding_model = embedding_model
        self.chat_model = chat_model
        self.events_store = JSONStore(data_dir, "events.json", list)
        self._default_summaries = {"daily_summaries": {}, "overall_summary": ""}
        self.summaries_store = JSONStore(
            data_dir,
            "memorybank_summaries.json",
            lambda: dict(self._default_summaries),
        )

    def write_with_memory(self, event: dict) -> str:
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
        return all_results[:top_k]

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
        query_vector = self.embedding_model.encode(query)
        today = date.today()
        results = []
        for event in events:
            event_vector = self.embedding_model.encode(event.get("content", ""))
            similarity = self._cosine_similarity(query_vector, event_vector)
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
            self._update_overall_summary(daily_summaries)

    def _update_overall_summary(self, daily_summaries: dict) -> None:
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
        summaries = self.summaries_store.read()
        summaries["overall_summary"] = overall
        self.summaries_store.write(summaries)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a * norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
