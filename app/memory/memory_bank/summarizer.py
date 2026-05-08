"""摘要与人格生成，不可变保护（多用户版）。"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .faiss_index import FaissIndexManager
    from .llm import LlmClient

logger = logging.getLogger(__name__)
GENERATION_EMPTY = "GENERATION_EMPTY"
_SUMMARY_SYSTEM_PROMPT = (
    "You are an in-car AI assistant with expertise in remembering "
    "vehicle preferences, driving habits, and in-car conversation context."
)


class Summarizer:
    """摘要与人格生成器，不可变保护（一旦生成不覆盖）。"""

    def __init__(self, llm: LlmClient, index_manager: FaissIndexManager) -> None:
        self._llm = llm
        self._index_manager = index_manager

    async def get_daily_summary(self, user_id: str, date_key: str) -> str | None:
        """生成某天的对话摘要（已存在则不覆盖）。"""
        meta = self._index_manager.get_metadata(user_id)
        if any(m.get("source") == f"summary_{date_key}" for m in meta):
            return None
        texts = [
            m["text"]
            for m in meta
            if m.get("source") == date_key and m.get("type") != "daily_summary"
        ]
        if not texts:
            return None
        result = await self._llm.call(
            self._summarize_prompt("\n".join(texts)),
            system_prompt=_SUMMARY_SYSTEM_PROMPT,
        )
        if result:
            return f"The summary of the conversation on {date_key} is: {result}"
        return None

    async def get_overall_summary(self, user_id: str) -> str | None:
        """基于所有日常摘要生成总体摘要（已存在则不覆盖）。"""
        extra = self._index_manager.get_extra(user_id)
        if extra.get("overall_summary"):
            return None
        meta = self._index_manager.get_metadata(user_id)
        daily_sums = [m for m in meta if m.get("type") == "daily_summary"]
        if not daily_sums:
            return None
        parts = [
            "Please provide a highly concise summary of the following in-car "
            "conversation summaries, capturing the essential vehicle preferences, "
            "user habits, and key information as succinctly as possible."
        ]
        parts.extend(f"\n{m.get('text', '')}" for m in daily_sums)
        parts.append("\nSummarization: ")
        result = await self._llm.call(
            "".join(parts), system_prompt=_SUMMARY_SYSTEM_PROMPT
        )
        if result:
            extra["overall_summary"] = result
            return result
        extra["overall_summary"] = GENERATION_EMPTY
        return None

    async def get_daily_personality(self, user_id: str, date_key: str) -> str | None:
        """生成某天的人格画像（已存在则不覆盖）。"""
        extra = self._index_manager.get_extra(user_id)
        existing = extra.setdefault("daily_personalities", {})
        if not isinstance(existing, dict):
            existing = {}
            extra["daily_personalities"] = existing
        if date_key in existing:
            return None
        texts = [
            m["text"]
            for m in self._index_manager.get_metadata(user_id)
            if m.get("source") == date_key and m.get("type") != "daily_summary"
        ]
        if not texts:
            return None
        result = await self._llm.call(
            self._personality_prompt("\n".join(texts)),
            system_prompt=_SUMMARY_SYSTEM_PROMPT,
        )
        if result:
            existing[date_key] = result
            return result
        return None

    async def get_overall_personality(self, user_id: str) -> str | None:
        """基于所有日常人格画像生成总体人格（已存在则不覆盖）。"""
        extra = self._index_manager.get_extra(user_id)
        if extra.get("overall_personality"):
            return None
        dailies = extra.get("daily_personalities", {})
        if not isinstance(dailies, dict) or not dailies:
            return None
        parts = [
            "The following are analyses of users' vehicle-related preferences "
            "and habits across multiple driving sessions:\n",
        ]
        parts.extend(
            f"\nAt {date}, the analysis shows {str(text).strip()}"
            for date, text in sorted(dailies.items())
        )
        parts.append(
            "\nPlease provide a highly concise summary of the users' vehicle "
            "preferences and driving habits, organized by user, and the most "
            "appropriate in-car response strategy for the AI assistant, "
            "summarized as:"
        )
        result = await self._llm.call(
            "".join(parts), system_prompt=_SUMMARY_SYSTEM_PROMPT
        )
        if result:
            extra["overall_personality"] = result
            return result
        extra["overall_personality"] = GENERATION_EMPTY
        return None

    @staticmethod
    def _summarize_prompt(text: str) -> str:
        return (
            "Please summarize the following in-car dialogue concisely, "
            "focusing specifically on:\n"
            "1. Vehicle settings or preferences mentioned (seat position, "
            "climate temperature/ventilation, ambient light color, navigation "
            "mode, music/radio settings, HUD brightness, etc.)\n"
            "2. Which person (by name) expressed or changed each preference\n"
            "3. Any conflicts or differences between users' vehicle preferences\n"
            "4. Conditional constraints (e.g. preference depends on time of day, "
            "weather, or passenger presence)\n"
            "Ignore general conversation topics unrelated to the vehicle.\n"
            f"Dialogue content:\n{text}\n"
            "Summarization："
        )

    @staticmethod
    def _personality_prompt(text: str) -> str:
        return (
            "Based on the following in-car dialogue, analyze the users' "
            "vehicle-related preferences and habits:\n"
            "1. What vehicle settings does each user prefer (seat, climate, "
            "lighting, media, navigation, etc.)?\n"
            "2. How do their preferences vary by context (time of day, "
            "weather, passengers)?\n"
            "3. What driving or comfort habits are exhibited?\n"
            "4. What response strategy should the AI use to anticipate "
            "each user's needs?\n"
            f"Dialogue content:\n{text}\n"
            "Analysis:"
        )
