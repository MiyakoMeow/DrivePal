"""人格分析管理器."""

import asyncio
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.memory.components import SUMMARY_WEIGHT, forgetting_curve
from app.memory.schemas import SearchResult
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
        self._inflight_daily_personality: set[str] = set()

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
        today = datetime.now(UTC).date()
        results = []
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
                except ValueError, TypeError:
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
                    ),
                )
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    async def strengthen(self, matched_date_groups: list[str]) -> None:
        """强化匹配到的人格摘要的 memory_strength 和 last_recall_date."""
        if not matched_date_groups:
            return
        today = datetime.now(UTC).date().isoformat()
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

    async def maybe_summarize(  # noqa: C901
        self,
        date_group: str,
        events: list[dict],
        interactions: list[dict],
        chat_model: ChatModel | None,
    ) -> None:
        """每日对话达到阈值时，生成人格分析摘要.

        注意：人格摘要一旦创建将不可变。这是有意的设计选择，用于避免批量导入时的冗余 LLM 调用。
        如果稍后向同一 date_group 添加交互，现有摘要不会重新生成。
        如需强制重新生成，请从存储中删除人格条目。
        """
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
        # 注意：latest_source_ts 仅用于调试/审计目的，不参与缓存失效判断（人格摘要不可变）
        should_generate = False
        async with self._personality_lock:
            personality_data = await self._store.read()
            daily_personality = personality_data.get("daily_personality", {})
            if date_group in self._inflight_daily_personality:
                return
            if date_group in daily_personality:
                existing = daily_personality[date_group]
                if isinstance(existing, dict):
                    return
            self._inflight_daily_personality.add(date_group)
            should_generate = True
            combined = "\n".join(
                f"用户: {i.get('query', '')}\n系统: {i.get('response', '')}"
                for i in group_interactions
            )
        if not should_generate:
            return
        prompt = f"""Based on the following dialogue, please summarize user's personality traits and emotions,
        and devise response strategies based on your speculation. Dialogue content:
        {combined}

        User's personality traits, emotions, and response strategy are:
        """
        needs_overall_update = False
        try:
            summary_text = await chat_model.generate(prompt)
            async with self._personality_lock:
                personality_data = await self._store.read()
                daily_personality = personality_data.get("daily_personality", {})
                if not isinstance(daily_personality.get(date_group), dict):
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
        except Exception:
            logger.exception(
                "Failed to generate personality summary for date_group=%s",
                date_group,
            )
            return
        finally:
            self._inflight_daily_personality.discard(date_group)
        if needs_overall_update:
            overall_text = await self.generate_overall_text(
                personality_data,
                chat_model,
            )
            if overall_text:
                async with self._personality_lock:
                    personality_data = await self._store.read()
                    personality_data["overall_personality"] = overall_text
                    await self._store.write(personality_data)

    async def generate_overall_text(
        self,
        personality_data: dict,
        chat_model: ChatModel | None,
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
        prompt = f"""The following are the user's exhibited personality traits and emotions throughout multiple dialogues,
        along with appropriate response strategies for the current situation:
        {combined}

        Please provide a highly concise and general summary of the user's personality and the most appropriate
        response strategy for the AI lover, summarized as:
        """
        try:
            return await chat_model.generate(prompt)
        except Exception:
            logger.exception("Failed to generate overall personality summary")
            return None
