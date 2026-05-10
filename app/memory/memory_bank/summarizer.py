"""摘要与人格生成，不可变保护（一旦生成不覆盖）。"""

import logging
from typing import TYPE_CHECKING

from app.memory.exceptions import SummarizationEmpty

if TYPE_CHECKING:
    from .config import MemoryBankConfig
    from .index_reader import IndexReader
    from .llm import LlmClient

logger = logging.getLogger(__name__)
GENERATION_EMPTY = "GENERATION_EMPTY"
_SUMMARY_DEFAULT_TEMPERATURE = 0.3
_SUMMARY_DEFAULT_MAX_TOKENS = 400


class Summarizer:
    """摘要与人格生成器，不可变保护（一旦生成不覆盖）。"""

    def __init__(
        self,
        llm: LlmClient,
        index: IndexReader,
        config: MemoryBankConfig,
    ) -> None:
        """初始化 Summarizer。

        Args:
            llm: LLM 客户端。
            index: 索引只读视图。
            config: MemoryBank 配置。

        """
        self._llm = llm
        self._index = index
        self._config = config

    @property
    def _effective_temperature(self) -> float:
        return (
            self._config.llm_temperature
            if self._config.llm_temperature is not None
            else _SUMMARY_DEFAULT_TEMPERATURE
        )

    @property
    def _effective_max_tokens(self) -> int:
        return (
            self._config.llm_max_tokens
            if self._config.llm_max_tokens is not None
            else _SUMMARY_DEFAULT_MAX_TOKENS
        )

    async def get_daily_summary(self, date_key: str) -> str | None:
        """生成某天的对话摘要（已存在则不覆盖）。

        Raises:
            LLMCallFailedError: LLM API 调用失败（调用方决定降级）。

        """
        meta = self._index.get_metadata()
        if any(m.get("source") == f"summary_{date_key}" for m in meta):
            return None
        texts = [
            m["text"]
            for m in meta
            if m.get("source") == date_key and m.get("type") != "daily_summary"
        ]
        if not texts:
            return None
        try:
            result = await self._llm.call(
                self._summarize_prompt("\n".join(texts)),
                system_prompt=self._config.summary_system_prompt,
                temperature=self._effective_temperature,
                max_tokens=self._effective_max_tokens,
            )
        except SummarizationEmpty:
            return None
        else:
            return f"The summary of the conversation on {date_key} is: {result}"

    async def get_overall_summary(self) -> str | None:
        """基于所有日常摘要生成总体摘要（已存在则不覆盖）。

        Raises:
            LLMCallFailedError: LLM API 调用失败。

        """
        extra = self._index.get_extra()
        if extra.get("overall_summary"):
            return None
        meta = self._index.get_metadata()
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
        try:
            result = await self._llm.call(
                "".join(parts),
                system_prompt=self._config.summary_system_prompt,
                temperature=self._effective_temperature,
                max_tokens=self._effective_max_tokens,
            )
        except SummarizationEmpty:
            extra["overall_summary"] = GENERATION_EMPTY
            return None
        else:
            extra["overall_summary"] = result
            return result

    async def get_daily_personality(self, date_key: str) -> str | None:
        """生成某天的人格画像（已存在则不覆盖）。

        Raises:
            LLMCallFailedError: LLM API 调用失败。

        """
        extra = self._index.get_extra()
        existing = extra.setdefault("daily_personalities", {})
        if not isinstance(existing, dict):
            existing = {}
            extra["daily_personalities"] = existing
        if date_key in existing:
            return None
        texts = [
            m["text"]
            for m in self._index.get_metadata()
            if m.get("source") == date_key and m.get("type") != "daily_summary"
        ]
        if not texts:
            return None
        try:
            result = await self._llm.call(
                self._personality_prompt("\n".join(texts)),
                system_prompt=self._config.summary_system_prompt,
                temperature=self._effective_temperature,
                max_tokens=self._effective_max_tokens,
            )
        except SummarizationEmpty:
            return None
        else:
            existing[date_key] = result
            return result

    async def get_overall_personality(self) -> str | None:
        """基于所有日常人格画像生成总体人格（已存在则不覆盖）。

        Raises:
            LLMCallFailedError: LLM API 调用失败。

        """
        extra = self._index.get_extra()
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
        try:
            result = await self._llm.call(
                "".join(parts),
                system_prompt=self._config.summary_system_prompt,
                temperature=self._effective_temperature,
                max_tokens=self._effective_max_tokens,
            )
        except SummarizationEmpty:
            extra["overall_personality"] = GENERATION_EMPTY
            return None
        else:
            extra["overall_personality"] = result
            return result

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
