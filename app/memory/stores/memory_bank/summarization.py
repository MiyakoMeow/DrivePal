# ruff: noqa: TC003
"""MemoryBank 摘要管理器."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.memory.components import SUMMARY_WEIGHT, forgetting_curve
from app.memory.schemas import SearchResult
from app.storage.toml_store import TOMLStore

if TYPE_CHECKING:
    from app.models.chat import ChatModel

DAILY_SUMMARY_THRESHOLD = 2
OVERALL_SUMMARY_THRESHOLD = 3

logger = logging.getLogger(__name__)


class SummaryManager:
    """摘要管理器，负责日常摘要的生成、搜索和强化."""

    def __init__(self, data_dir: Path) -> None:
        """初始化摘要管理器."""
        self._summaries_store = TOMLStore(
            data_dir,
            Path("memorybank_summaries.toml"),
            lambda: {"daily_summaries": {}, "overall_summary": ""},
        )
        self._lock = asyncio.Lock()

    @property
    def summaries_store(self) -> TOMLStore:
        """摘要存储."""
        return self._summaries_store

    async def search_summaries(
        self, query: str, daily_summaries: dict, top_k: int = 1
    ) -> list[SearchResult]:
        """搜索日常摘要并强化匹配结果."""
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
        await self.strengthen_summaries(matched_keys, daily_summaries)
        return results[:top_k]

    async def strengthen_summaries(
        self, matched_keys: list[str], daily_summaries: dict
    ) -> None:
        """强化匹配到的摘要的记忆强度."""
        if not matched_keys:
            return
        today = datetime.now(timezone.utc).date().isoformat()
        async with self._lock:
            summaries = await self._summaries_store.read()
            current_daily = summaries.get("daily_summaries", {})
            updated = False
            for key in matched_keys:
                if key in current_daily:
                    summary_data = current_daily[key]
                    if isinstance(summary_data, dict):
                        summary_data["memory_strength"] = (
                            summary_data.get("memory_strength", 1) + 1
                        )
                        summary_data["last_recall_date"] = today
                        updated = True
            if updated:
                summaries["daily_summaries"] = current_daily
                await self._summaries_store.write(summaries)

    async def maybe_summarize(
        self, date_group: str, events: list[dict], chat_model: ChatModel | None
    ) -> None:
        """事件数量达到阈值时生成日常摘要."""
        count = len(events)
        if count < DAILY_SUMMARY_THRESHOLD:
            return
        if not chat_model:
            return
        latest_source_ts = max(
            (e.get("updated_at") or e.get("created_at", "") for e in events),
            default="",
        )
        should_generate = False
        async with self._lock:
            summaries = await self._summaries_store.read()
            daily_summaries = summaries.get("daily_summaries", {})
            if date_group in daily_summaries:
                existing = daily_summaries[date_group]
                if (
                    isinstance(existing, dict)
                    and existing.get("event_count", 0) >= count
                    and existing.get("source_updated_at", "") >= latest_source_ts
                ):
                    return
            should_generate = True
            content = "\n".join(
                e.get("content", "") for e in events if e.get("content")
            )
        if not should_generate:
            return
        prompt = f"请简洁总结以下事件（一句话）：\n{content}"
        try:
            summary_text = await chat_model.generate(prompt)
        except Exception:
            return
        needs_overall_update = False
        async with self._lock:
            summaries = await self._summaries_store.read()
            daily_summaries = summaries.get("daily_summaries", {})
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
                needs_overall_update = True
        if needs_overall_update:
            await self.update_overall_summary(daily_summaries, summaries, chat_model)

    async def update_overall_summary(
        self, daily_summaries: dict, summaries: dict, chat_model: ChatModel | None
    ) -> None:
        """根据日常摘要更新总体摘要."""
        if not chat_model:
            return
        all_summaries: list[str] = []
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
            overall = await chat_model.generate(prompt)
        except Exception:
            return
        async with self._lock:
            summaries = await self._summaries_store.read()
            summaries["overall_summary"] = overall
            await self._summaries_store.write(summaries)
