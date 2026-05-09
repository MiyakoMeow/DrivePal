"""Agent工作流编排模块."""

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.agents.probabilistic import (
    OVERLOADED_WARNING_THRESHOLD,
    compute_interrupt_risk,
    infer_intent,
    is_enabled,
)
from app.agents.prompts import SYSTEM_PROMPTS
from app.agents.rules import apply_rules, format_constraints, postprocess_decision
from app.agents.state import AgentState, WorkflowStages
from app.config import user_data_dir
from app.memory.memory import MemoryModule
from app.memory.privacy import sanitize_context
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
                return val.get("text") or val.get("content") or "无提醒内容"
        return "无提醒内容"


class AgentWorkflow:
    """多Agent协作工作流."""

    def __init__(
        self,
        data_dir: Path = Path("data"),
        memory_mode: MemoryMode = MemoryMode.MEMORY_BANK,
        memory_module: MemoryModule | None = None,
        current_user: str = "default",
    ) -> None:
        """初始化工作流实例."""
        self.data_dir = data_dir
        self._memory_mode = memory_mode
        self.current_user = current_user

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
        self._strategies_store = TOMLStore(
            user_dir=user_data_dir(current_user),
            filename="strategies.toml",
            default_factory=dict,
        )

    async def _call_llm_json(self, user_prompt: str) -> LLMJsonResponse:
        if not self.memory_module.chat_model:
            raise ChatModelUnavailableError
        result = await self.memory_module.chat_model.generate(
            user_prompt,
            json_mode=True,
        )
        return LLMJsonResponse.from_llm(result)

    async def _safe_memory_search(self, user_input: str) -> list[dict] | None:
        """搜索相关记忆，失败或结果为空返回 None。"""
        try:
            events = await self.memory_module.search(
                user_input,
                mode=self._memory_mode,
            )
            if events:
                return [e.to_public() for e in events]
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as e:
            logger.warning("Memory search failed: %s", e)
        return None

    async def _safe_memory_history(self) -> list[dict]:
        """获取最近历史记录，失败返回空列表。"""
        try:
            history = await self.memory_module.get_history(
                mode=self._memory_mode,
                user_id=self.current_user,
            )
            return [e.model_dump() for e in history]
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as e:
            logger.warning("Memory get_history failed: %s", e)
            return []

    async def _search_memories(
        self,
        user_input: str,
    ) -> list[dict]:
        """搜索相关记忆，失败时回退到最近历史记录。"""
        if not user_input:
            return await self._safe_memory_history()
        events = await self._safe_memory_search(user_input)
        if events:
            return events
        return await self._safe_memory_history()

    async def _context_node(self, state: AgentState) -> dict:
        user_input = state.get("original_query", "")
        stages = state.get("stages")

        relevant_memories = await self._search_memories(user_input)

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

        # 概率推断 + 反馈权重注入
        prob_block = ""
        if is_enabled() and self._memory_mode == MemoryMode.MEMORY_BANK:
            try:
                intent = await infer_intent(
                    state.get("original_query", ""),
                    self.memory_module,
                    user_id=self.current_user,
                )
                risk = compute_interrupt_risk(driving_context or {})
                intent["interrupt_risk"] = round(risk, 2)
                prob_block = f"\n\n概率推断: {json.dumps(intent, ensure_ascii=False)}"
                if risk >= OVERLOADED_WARNING_THRESHOLD:
                    prob_block += "\n⚠ 当前打断风险较高，请谨慎决定"
            except (OSError, RuntimeError, ValueError, TypeError) as e:
                logger.warning("Probabilistic inference failed: %s", e)

        # 反馈权重注入
        weights = strategies.get("reminder_weights", {})
        weights_block = ""
        if weights:
            weights_block = (
                f"\n\n事件类型偏好权重: {json.dumps(weights, ensure_ascii=False)}"
                "\n权重越高表示用户偏好该类型提醒，请在决策时优先考虑高权重类型。"
            )

        prompt = f"""{SYSTEM_PROMPTS["strategy"]}

上下文: {json.dumps(context, ensure_ascii=False)}
任务: {json.dumps(task, ensure_ascii=False)}
个性化策略: {json.dumps(strategies, ensure_ascii=False)}{weights_block}{constraints_block}{prob_block}

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

    async def _check_frequency_guard(
        self,
        driving_ctx: dict | None,
    ) -> str | None:
        """检查频次约束，返回抑制消息或 None。"""
        if not driving_ctx:
            return None
        constraints = apply_rules(driving_ctx)
        max_freq = constraints.get("max_frequency_minutes")
        if max_freq is None:
            return None
        recent_events = await self._safe_memory_history()
        now = datetime.now(UTC)
        for evt in recent_events:
            evt_time_str = evt.get("created_at", "")
            if not evt_time_str:
                continue
            try:
                evt_time = datetime.fromisoformat(evt_time_str)
            except ValueError, TypeError:
                continue
            if evt_time.tzinfo is None:
                evt_time = evt_time.replace(tzinfo=UTC)
            delta_minutes = (now - evt_time).total_seconds() / 60.0
            if delta_minutes < max_freq:
                return f"提醒已抑制：距上次提醒不足 {max_freq} 分钟"
        return None

    async def _execution_node(self, state: AgentState) -> dict:
        decision = state.get("decision") or {}
        stages = state.get("stages")

        # 规则硬约束：LLM 决策后强制覆盖，不可绕过
        driving_ctx = state.get("driving_context")
        if driving_ctx:
            decision = postprocess_decision(decision, driving_ctx)

        # 硬约束禁止发送（如 only_urgent 拦截非紧急类型）
        if not decision.get("should_remind", True):
            result = "提醒已取消：安全规则禁止发送"
            if stages is not None:
                stages.execution = {
                    "content": None,
                    "event_id": None,
                    "result": result,
                }
            return {"result": result, "event_id": None}

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

        # 频次约束检查
        freq_msg = await self._check_frequency_guard(driving_ctx)
        if freq_msg is not None:
            if stages is not None:
                stages.execution = {
                    "content": None,
                    "event_id": None,
                    "result": freq_msg,
                }
            return {"result": freq_msg, "event_id": None}

        content = self._extract_content(decision)
        original_query = state.get("original_query", "")

        # 隐私脱敏：写入前脱敏 driving_ctx 中的位置信息
        safe_ctx = sanitize_context(driving_ctx) if driving_ctx else None
        if safe_ctx is not None and stages is not None:
            stages.context = safe_ctx  # 更新 stages 中上下文为脱敏版本

        interaction_result = await self.memory_module.write_interaction(
            original_query,
            content,
            mode=self._memory_mode,
            user_id=self.current_user,
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
