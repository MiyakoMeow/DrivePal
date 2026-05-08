"""Agent工作流编排模块."""

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.agents.prompts import SYSTEM_PROMPTS
from app.agents.rules import apply_rules, format_constraints, postprocess_decision
from app.agents.state import AgentState, WorkflowStages
from app.memory.memory import MemoryModule
from app.memory.types import MemoryMode
from app.models.chat import get_chat_model
from app.storage.toml_store import TOMLStore

logger = logging.getLogger(__name__)


class ChatModelUnavailableError(RuntimeError):
    """ChatModel 不可用时抛出的异常."""

    def __init__(self) -> None:
        """初始化 ChatModel 不可用错误."""
        super().__init__("ChatModel not available")


class LLMJsonResponse(BaseModel):
    """LLM JSON 输出包装，含校验与兜底."""

    model_config = ConfigDict(extra="allow")

    raw: str

    @classmethod
    def from_llm(cls, text: str) -> LLMJsonResponse:
        """Parse LLM output, warning on fail but always return valid."""
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed: dict = {}
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                parsed = data
        except json.JSONDecodeError as e:
            logger.warning("LLM JSON parse failed: %s", e)
        parsed.pop("raw", None)  # prevent collision with explicit raw=text
        return cls(raw=text, **parsed)


class ReminderContent(BaseModel):
    """提醒内容校验模型。"""

    text: str = ""
    content: str = ""

    @classmethod
    def from_decision(cls, decision: dict) -> str:
        """从 decision dict 中提取提醒内容，多处 key 兜底。"""
        for key in ("reminder_content", "remind_content", "content"):
            val = decision.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):
                return val.get("text") or val.get("content") or ""
        return "无提醒内容"


class AgentWorkflow:
    """多Agent协作工作流."""

    def __init__(
        self,
        data_dir: Path = Path("data"),
        memory_mode: MemoryMode = MemoryMode.MEMORY_BANK,
        memory_module: MemoryModule | None = None,
    ) -> None:
        """初始化工作流实例."""
        self.data_dir = data_dir
        self._memory_mode = memory_mode

        if memory_module is not None:
            self.memory_module = memory_module
        else:
            chat_model = get_chat_model()
            self.memory_module = MemoryModule(data_dir, chat_model=chat_model)

        self._nodes = [
            self._context_node,
            self._task_node,
            self._strategy_node,
            self._execution_node,
        ]
        self._strategies_store = TOMLStore(data_dir, Path("strategies.toml"), dict)

    async def _call_llm_json(self, user_prompt: str) -> LLMJsonResponse:
        if not self.memory_module.chat_model:
            raise ChatModelUnavailableError
        result = await self.memory_module.chat_model.generate(
            user_prompt,
            json_mode=True,
        )
        return LLMJsonResponse.from_llm(result)

    async def _context_node(self, state: AgentState) -> dict:
        user_input = state.get("original_query", "")
        stages = state.get("stages")

        try:
            related_events = (
                await self.memory_module.search(user_input, mode=self._memory_mode)
                if user_input
                else []
            )
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as e:
            logger.warning("Memory search failed: %s", e)
            related_events = []

        try:
            if related_events:
                relevant_memories = [e.to_public() for e in related_events]
            else:
                relevant_memories = [
                    e.model_dump()
                    for e in await self.memory_module.get_history(
                        mode=self._memory_mode,
                    )
                ]
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as e:
            logger.warning("Memory get_history failed: %s", e)
            relevant_memories = (
                [e.to_public() for e in related_events] if related_events else []
            )

        current_datetime = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        driving_context = state.get("driving_context")

        if driving_context:
            context = dict(driving_context)
            context["current_datetime"] = current_datetime
            context["related_events"] = relevant_memories
        else:
            system_prompt = SYSTEM_PROMPTS["context"].format(
                current_datetime=current_datetime,
            )

            prompt = f"""{system_prompt}

用户输入: {user_input}
历史记录: {json.dumps(relevant_memories, ensure_ascii=False)}

请输出JSON格式的上下文对象. """

            parsed = await self._call_llm_json(prompt)
            context = {
                **parsed.model_dump(),
                "current_datetime": current_datetime,
                "related_events": relevant_memories,
            }

        if stages is not None:
            stages.context = context

        return {
            "context": context,
        }

    async def _task_node(self, state: AgentState) -> dict:
        user_input = state.get("original_query", "")
        context = state.get("context", {})
        stages = state.get("stages")

        prompt = f"""{SYSTEM_PROMPTS["task"]}

用户输入: {user_input}
上下文: {json.dumps(context, ensure_ascii=False)}

请输出JSON格式的任务对象. """

        task = (await self._call_llm_json(prompt)).model_dump()
        if stages is not None:
            stages.task = task
        return {
            "task": task,
        }

    async def _strategy_node(self, state: AgentState) -> dict:
        context = state.get("context", {})
        task = state.get("task") or {}
        stages = state.get("stages")

        strategies = await self._strategies_store.read()

        constraints_block = ""
        driving_context = state.get("driving_context")
        postpone = False
        if driving_context:
            constraints = apply_rules(driving_context)
            constraints_block = "\n\n" + format_constraints(constraints)
            postpone = constraints.get("postpone", False)

        prompt = f"""{SYSTEM_PROMPTS["strategy"]}

上下文: {json.dumps(context, ensure_ascii=False)}
任务: {json.dumps(task, ensure_ascii=False)}
个性化策略: {json.dumps(strategies, ensure_ascii=False)}{constraints_block}

请输出JSON格式的决策结果. """

        decision = (await self._call_llm_json(prompt)).model_dump()
        decision["postpone"] = postpone
        if stages is not None:
            stages.decision = decision
        return {
            "decision": decision,
        }

    @staticmethod
    def _extract_content(decision: dict) -> str:
        """从决策 dict 中提取提醒内容。"""
        return ReminderContent.from_decision(decision)

    async def _execution_node(self, state: AgentState) -> dict:
        decision = state.get("decision") or {}
        stages = state.get("stages")

        # 规则硬约束：LLM 决策后强制覆盖，不可绕过
        driving_ctx = state.get("driving_context")
        if driving_ctx:
            decision = postprocess_decision(decision, driving_ctx)

        postpone = decision.get("postpone", False)
        if postpone:
            result = "提醒已延后：当前驾驶状态不适合发送提醒"
            if stages is not None:
                stages.execution = {
                    "content": None,
                    "event_id": None,
                    "result": result,
                }
            return {
                "result": result,
                "event_id": None,
            }

        content = self._extract_content(decision)
        original_query = state.get("original_query", "")
        interaction_result = await self.memory_module.write_interaction(
            original_query,
            content,
            mode=self._memory_mode,
        )
        event_id = interaction_result.event_id
        if not event_id:
            logger.warning("Memory write returned empty event_id, using fallback")
            event_id = (
                f"unknown_{hashlib.sha256(str(decision).encode()).hexdigest()[:8]}"
            )

        result = f"提醒已发送: {content}"
        if stages is not None:
            stages.execution = {
                "content": content,
                "event_id": event_id,
                "result": result,
            }
        return {
            "result": result,
            "event_id": event_id,
        }

    async def run_with_stages(
        self,
        user_input: str,
        driving_context: dict | None = None,
    ) -> tuple[str, str | None, WorkflowStages]:
        """运行完整工作流并返回结果、事件ID和各阶段输出."""
        stages = WorkflowStages()
        state: AgentState = {
            "original_query": user_input,
            "context": {},
            "task": None,
            "decision": None,
            "result": None,
            "event_id": None,
            "driving_context": driving_context,
            "stages": stages,
        }

        for node_fn in self._nodes:
            updates = await node_fn(state)
            state.update(updates)

        result = state.get("result") or "处理完成"
        event_id = state.get("event_id")
        return result, event_id, stages
