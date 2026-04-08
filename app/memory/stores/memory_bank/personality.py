"""人格分析管理器."""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.memory.components import forgetting_curve, SUMMARY_WEIGHT
from app.memory.schemas import SearchResult
from app.memory.utils import days_elapsed_since
from app.storage.toml_store import TOMLStore

if TYPE_CHECKING:
    from app.models.chat import ChatModel

PERSONALITY_SUMMARY_THRESHOLD = 2
OVERALL_PERSONALITY_THRESHOLD = 3


logger = logging.getLogger(__name__)


class PersonalityManager:
    """管理人格摘要的搜索、强化、生成."""

    def __init__(self, data_dir: Path) -> None:
        """初始化人格存储."""
        self._store = TOMLStore(
            data_dir,
            Path("memorybank_personality.toml"),
            lambda: {"daily_personality": {}, "overall_personality": ""},
        )
        self._personality_lock = asyncio.Lock()

    @property
    def personality_store(self) -> TOMLStore:
        """人格摘要存储."""
        return self._store

    async def search(self, query: str, top_k: int) -> list[SearchResult]:
        """基于关键词匹配搜索人格摘要，retention权重为 SUMMARY_WEIGHT * 0.8."""
        personality_data = await self._store.read()
        daily_personality = personality_data.get("daily_personality", {})
        if not daily_personality:
            return []
        query_lower = query.lower()
        today = datetime.now(timezone.utc).date()
        results = []
        for date_group, data in daily_personality.items():
            if not isinstance(data, dict):
                continue
            content = data.get("content", "")
            if query_lower in content.lower():
                strength = data.get("memory_strength", 1)
                last_recall = data.get("last_recall_date", date_group)
                days_elapsed = days_elapsed_since(last_recall, today)
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
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    async def strengthen(self, matched_date_groups: list[str]) -> None:
        """强化匹配到的人格摘要的 memory_strength 和 last_recall_date."""
        if not matched_date_groups:
            return
        today = datetime.now(timezone.utc).date().isoformat()
        async with self._personality_lock:
            personality_data = await self._store.read()
            current_daily = personality_data.get("daily_personality", {})
            updated = False
            for date_group in matched_date_groups:
                if date_group in current_daily:
                    data = current_daily[date_group]
                    if isinstance(data, dict):
                        data["memory_strength"] = data.get("memory_strength", 1) + 1
                        data["last_recall_date"] = today
                        updated = True
            if updated:
                personality_data["daily_personality"] = current_daily
                await self._store.write(personality_data)

    async def maybe_summarize(
        self,
        date_group: str,
        events: list[dict],
        interactions: list[dict],
        chat_model: ChatModel | None,
    ) -> None:
        """每日对话达到阈值时，生成人格分析摘要."""
        if not chat_model:
            return
        group_events = [e for e in events if e.get("date_group") == date_group]
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
        should_generate = False
        async with self._personality_lock:
            personality_data = await self._store.read()
            daily_personality = personality_data.get("daily_personality", {})
            if date_group in daily_personality:
                existing = daily_personality[date_group]
                if (
                    isinstance(existing, dict)
                    and existing.get("interaction_count", 0) >= len(group_interactions)
                    and existing.get("source_updated_at", "") >= latest_source_ts
                ):
                    return
            should_generate = True
            combined = "\n".join(
                f"用户: {i.get('query', '')}\n系统: {i.get('response', '')}"
                for i in group_interactions
            )
        if not should_generate:
            return
        prompt = f"""根据以下对话内容，请总结用户的人格特征和情绪状态，
        并据此推测合适的回应策略。对话内容：
        {combined}

        用户的人格特征、情绪和回应策略：
        """
        try:
            summary_text = await chat_model.generate(prompt)
        except (RuntimeError, OSError) as e:
            logger.warning(
                "Failed to generate personality summary for date_group=%s: %s",
                date_group,
                e,
            )
            return
        needs_overall_update = False
        async with self._personality_lock:
            personality_data = await self._store.read()
            daily_personality = personality_data.get("daily_personality", {})
            daily_personality[date_group] = {
                "content": summary_text,
                "memory_strength": 1,
                "last_recall_date": date_group,
                "interaction_count": len(group_interactions),
                "source_updated_at": latest_source_ts,
            }
            personality_data["daily_personality"] = daily_personality
            await self._store.write(personality_data)
            if len(daily_personality) >= OVERALL_PERSONALITY_THRESHOLD:
                needs_overall_update = True
        if needs_overall_update:
            overall_text = await self.generate_overall_text(
                personality_data, chat_model
            )
            if overall_text:
                async with self._personality_lock:
                    personality_data = await self._store.read()
                    personality_data["overall_personality"] = overall_text
                    await self._store.write(personality_data)

    async def generate_overall_text(
        self, personality_data: dict, chat_model: ChatModel | None
    ) -> str | None:
        """生成整体人格档案文本（不含锁，不写存储）."""
        if not chat_model:
            return None
        daily_personality = personality_data.get("daily_personality", {})
        all_summaries = [
            f"[{date_group}] {data.get('content', '')}"
            for date_group, data in daily_personality.items()
            if isinstance(data, dict)
        ]
        combined = "\n".join(all_summaries)
        prompt = f"""以下是对话中表现出的用户人格特征和情绪状态，
        以及适合当前场景的回应策略：
        {combined}

        请用简练的语言总结用户的整体人格特征，以及 AI 助手最适合采用的回应策略：
        """
        try:
            return await chat_model.generate(prompt)
        except (RuntimeError, OSError) as e:
            logger.warning("Failed to generate overall personality summary: %s", e)
            return None
