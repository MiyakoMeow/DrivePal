"""Context Agent：感知阶段——记忆检索 + 上下文构建."""

import json
import logging
from datetime import UTC, datetime

from pydantic import ValidationError

from app.agents.conversation import ConversationManager
from app.agents.prompts import SYSTEM_PROMPTS
from app.agents.state import AgentState
from app.agents.types import ContextOutput, call_llm_json
from app.memory.memory import MemoryModule
from app.memory.types import MemoryMode

logger = logging.getLogger(__name__)


class ContextAgent:
    """Context 阶段 Agent：检索记忆 + 构建上下文."""

    def __init__(
        self,
        memory: MemoryModule,
        conversations: ConversationManager,
        current_user: str,
    ) -> None:
        self._memory = memory
        self._conversations = conversations
        self._current_user = current_user

    async def run(self, state: AgentState) -> dict:
        """执行 Context 阶段."""
        user_input = state.get("original_query", "")
        stages = state.get("stages")
        session_id = state.get("session_id")

        relevant_memories = await self._search_memories(user_input)

        conversation_history: list[dict] = []
        if session_id:
            turns = self._conversations.get_history(session_id)
            conversation_history = [
                {
                    "turn": t.turn_id,
                    "user": t.query,
                    "assistant_summary": t.response_summary,
                    "intent": t.decision_snapshot,
                }
                for t in turns
            ]

        current_datetime = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        driving_context = state.get("driving_context")

        if driving_context:
            context = dict(driving_context)
            context["current_datetime"] = current_datetime
            context["related_events"] = relevant_memories
            if conversation_history:
                context["conversation_history"] = conversation_history
        else:
            system_prompt = SYSTEM_PROMPTS["context"].format(
                current_datetime=current_datetime,
            )
            history_block = ""
            if conversation_history:
                history_block = (
                    "\n对话历史: "
                    + json.dumps(conversation_history, ensure_ascii=False)
                    + "\n请结合对话历史理解指代（如'刚才那个'指上一轮的 entities）。"
                )

            prompt = f"""{system_prompt}

用户输入: {user_input}
历史记录: {json.dumps(relevant_memories, ensure_ascii=False)}{history_block}

请输出JSON格式的上下文对象. """

            parsed = await call_llm_json(
                self._memory.chat_model, prompt, max_tokens=2048
            )
            try:
                validated = ContextOutput.model_validate(parsed.data or {})
                context = validated.model_dump()
            except ValidationError as e:
                logger.warning("ContextOutput validation failed: %s", e)
                raw_data = parsed.data
                context = raw_data or {}
            context["current_datetime"] = current_datetime
            context["related_events"] = relevant_memories

        if stages is not None:
            stages.context = context

        return {
            "context": context,
        }

    async def _safe_memory_search(self, user_input: str) -> list[dict] | None:
        """搜索相关记忆，失败或结果为空返回 None."""
        try:
            events = await self._memory.search(
                user_input,
                mode=MemoryMode.MEMORY_BANK,
            )
            if events:
                return [e.to_public() for e in events]
        except Exception as e:
            logger.warning("Memory search failed: %s", e)
        return None

    async def _safe_memory_history(self) -> list[dict]:
        """获取最近历史记录，失败返回空列表."""
        try:
            history = await self._memory.get_history(
                mode=MemoryMode.MEMORY_BANK,
                user_id=self._current_user,
            )
            return [e.model_dump() for e in history]
        except Exception as e:
            logger.warning("Memory get_history failed: %s", e)
            return []

    async def _search_memories(
        self,
        user_input: str,
    ) -> list[dict]:
        """搜索相关记忆，失败时回退到最近历史记录."""
        if not user_input:
            return await self._safe_memory_history()
        events = await self._safe_memory_search(user_input)
        if events:
            return events
        return await self._safe_memory_history()
