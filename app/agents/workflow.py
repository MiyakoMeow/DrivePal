"""Agent工作流编排模块."""

import contextvars
import hashlib
import json
import logging
import re
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from app.agents.conversation import _conversation_manager
from app.agents.outputs import OutputRouter
from app.agents.pending import PendingReminderManager
from app.agents.probabilistic import (
    OVERLOADED_WARNING_THRESHOLD,
    compute_interrupt_risk,
    infer_intent,
    is_enabled,
)
from app.agents.prompts import SYSTEM_PROMPTS
from app.agents.prompts_proactive import PROACTIVE_JOINT_DECISION_PROMPT
from app.agents.rules import apply_rules, postprocess_decision
from app.agents.shortcuts import ShortcutResolver
from app.agents.state import AgentState, WorkflowStages
from app.config import user_data_dir
from app.exceptions import AppError
from app.memory.memory import MemoryModule
from app.memory.privacy import sanitize_context
from app.memory.types import MemoryMode
from app.models.chat import get_chat_model
from app.storage.toml_store import TOMLStore
from app.tools import get_default_executor
from app.tools.executor import ToolExecutionError

_ablation_disable_feedback: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_ablation_disable_feedback", default=False
)


def set_ablation_disable_feedback(v: bool) -> None:
    """设置消融实验标记：禁用反馈权重。ContextVar 自动任务隔离。"""
    _ablation_disable_feedback.set(v)


def get_ablation_disable_feedback() -> bool:
    """读取消融实验标记（当前 Context 的值）。"""
    return _ablation_disable_feedback.get()


logger = logging.getLogger(__name__)

_PREFERENCE_WEIGHT_HIGH: float = 0.6
_PREFERENCE_WEIGHT_LOW: float = 0.5
_INTENT_CONFIDENCE_THRESHOLD: float = 0.3


class WorkflowError(AppError):
    """工作流异常（模型不可用等）。"""

    def __init__(self, code: str = "WORKFLOW_ERROR", message: str = "") -> None:
        if not message:
            message = "Workflow error"
        super().__init__(code=code, message=message)


class LLMJsonResponse(BaseModel):
    """LLM JSON 输出包装，含校验与兜底."""

    model_config = ConfigDict(extra="forbid")

    raw: str
    data: dict | None = None

    @classmethod
    def from_llm(cls, text: str) -> LLMJsonResponse:
        """Parse LLM output, warning on fail but always return valid."""
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return cls(raw=text, data=data)
        except json.JSONDecodeError:
            pass
        return cls(raw=text)


class ContextOutput(BaseModel):
    """Context Agent JSON 输出模型，extra forbid。

    validation_alias 兜底 LLM 字段名漂移——不同模型/温度下可能产出
    非标准键名（如 scene/location/datetime 等）。
    """

    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(
        default="",
        validation_alias=AliasChoices("scenario", "scene", "driving_scenario"),
    )
    driver_state: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("driver_state", "driver", "state"),
    )
    spatial: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("spatial", "location", "position"),
    )
    traffic: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("traffic", "traffic_status"),
    )
    current_datetime: str = Field(
        default="",
        validation_alias=AliasChoices("current_datetime", "datetime", "time"),
    )
    related_events: list = Field(
        default_factory=list,
        validation_alias=AliasChoices("related_events", "events", "history"),
    )
    conversation_history: list | None = None


class JointDecisionOutput(BaseModel):
    """JointDecision Agent JSON 输出模型。

    merge TaskOutput + StrategyOutput，decision 字段以 dict 传递（规则后处理）。
    extra forbid 防止 LLM 注入非法字段。
    """

    model_config = ConfigDict(extra="forbid")

    task_type: str = Field(
        default="general",
        validation_alias=AliasChoices("task_type", "type", "task_attribution"),
    )
    confidence: float = Field(
        default=0.0,
        validation_alias=AliasChoices("confidence", "conf"),
    )
    entities: list = Field(
        default_factory=list,
        validation_alias=AliasChoices("entities", "events", "event_list"),
    )
    decision: dict = Field(default_factory=dict)


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


def _format_time_for_display(time_str: str) -> str:
    """从 ISO 时间字符串提取 HH:MM 用于显示."""
    try:
        dt = datetime.fromisoformat(time_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.strftime("%H:%M")
    except ValueError, TypeError:
        return time_str


def _extract_location_target(driving_ctx: dict | None) -> dict:
    """从 driving_context 中提取目标位置经纬度。"""
    if driving_ctx:
        spatial = driving_ctx.get("spatial", {}) or {}
        dest = spatial.get("destination", {}) or {}
        if dest.get("latitude") is not None:
            return {"latitude": dest["latitude"], "longitude": dest["longitude"]}
    return {}


def _map_pending_trigger(
    decision: dict, driving_ctx: dict | None
) -> tuple[str, dict, str]:
    """从 decision 映射 trigger_type、trigger_target、trigger_text."""
    timing = decision.get("timing", "")
    if timing == "location":
        return (
            "location",
            _extract_location_target(driving_ctx),
            "到达目的地时",
        )
    if timing == "location_time":
        return (
            "location_time",
            {
                "location": _extract_location_target(driving_ctx),
                "time": decision.get("target_time", ""),
            },
            "到达目的地或到时间时",
        )
    if timing == "delay":
        seconds = decision.get("delay_seconds", 300)
        target_dt = datetime.now(UTC) + timedelta(seconds=seconds)
        target_str = target_dt.isoformat()
        return "time", {"time": target_str}, f"延迟 {seconds} 秒后"

    target_time = decision.get("target_time", "")
    if target_time:
        return "time", {"time": target_time}, f"{target_time} 时"
    if driving_ctx:
        return (
            "context",
            {"previous_scenario": driving_ctx.get("scenario", "")},
            "驾驶状态恢复时",
        )
    # 兜底：无 driving_ctx 且无时间信息时，创建即刻触发的时间提醒
    # 注意：此时轮询调用 poll() 后会立即触发（now >= target_time）
    return "time", {"time": datetime.now(UTC).isoformat()}, ""


class AgentWorkflow:
    """多Agent协作工作流."""

    def __init__(
        self,
        data_dir: Path = Path("data"),
        memory_module: MemoryModule | None = None,
        current_user: str = "default",
    ) -> None:
        """初始化工作流实例."""
        self.data_dir = data_dir
        self._memory_mode = MemoryMode.MEMORY_BANK
        self.current_user = current_user

        if memory_module is not None:
            self.memory_module = memory_module
        else:
            chat_model = get_chat_model()
            self.memory_module = MemoryModule(data_dir, chat_model=chat_model)
        self._conversations = _conversation_manager
        self._shortcuts = ShortcutResolver()

        self._nodes = [
            self._context_node,
            self._joint_decision_node,
            self._execution_node,
        ]
        self._strategies_store = TOMLStore(
            user_dir=user_data_dir(current_user),
            filename="strategies.toml",
            default_factory=dict,
        )

    @staticmethod
    def _format_constraints_hint(rules_result: dict | None) -> str:
        """从规则结果生成自然语言约束提示."""
        if not rules_result:
            return ""
        hints: list[str] = []
        channels = rules_result.get("allowed_channels")
        if channels:
            ch_str = ", ".join(channels)
            hints.append(f"当前仅建议通过 {ch_str} 通道提醒。")
        max_freq = rules_result.get("max_frequency_minutes")
        if max_freq is not None:
            hints.append(f"两次提醒建议至少间隔 {max_freq} 分钟。")
        if rules_result.get("only_urgent"):
            hints.append("当前仅紧急提醒适合发送。")
        if rules_result.get("postpone"):
            hints.append("当前应延后非紧急提醒。")
        return " ".join(hints)

    @staticmethod
    def _ensure_postprocessed(
        decision: dict, driving_ctx: dict | None
    ) -> tuple[dict, list[str]]:
        """统一入口：确保 decision 已过规则后处理。幂等。"""
        if decision.get("_postprocessed") or not driving_ctx:
            return decision, []
        decision, modifications = postprocess_decision(decision, driving_ctx)
        decision["_postprocessed"] = True
        return decision, modifications

    async def _format_preference_hint(self) -> str:
        """从 strategies.toml 读 reminder_weights → 自然语言偏好提示."""
        if get_ablation_disable_feedback():
            return ""
        strategies = await self._strategies_store.read()
        weights = strategies.get("reminder_weights", {})
        if not isinstance(weights, dict):
            return ""
        items: list[tuple[str, float]] = [
            (k, float(v)) for k, v in weights.items() if isinstance(v, (int, float))
        ]
        if not items:
            return ""
        items.sort(key=lambda x: -x[1])
        top_type, top_weight = items[0]
        if top_weight >= _PREFERENCE_WEIGHT_HIGH:
            return (
                f"用户当前偏好 {top_type} 类提醒（权重 {top_weight}），"
                "若非安全规则冲突请优先处理。"
            )
        if top_weight >= _PREFERENCE_WEIGHT_LOW:
            return f"用户略偏好 {top_type} 类提醒，可适当考虑。"
        return ""

    async def _call_llm_json(self, user_prompt: str) -> LLMJsonResponse:
        if not self.memory_module.chat_model:
            raise WorkflowError(
                code="MODEL_UNAVAILABLE", message="ChatModel not available"
            )
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
        except Exception as e:
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
        except Exception as e:
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
        session_id = state.get("session_id")

        relevant_memories = await self._search_memories(user_input)

        # --- 多轮对话：注入对话历史 ---
        conversation_history = []
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

            parsed = await self._call_llm_json(prompt)
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

    async def _joint_decision_node(self, state: AgentState) -> dict:
        """JointDecision 节点：合并 Task 归因 + 策略决策为一次 LLM 调用.

        prompt 精简原则：
        - 不注入 strategies.toml 全文，仅读 reminder_weights
        - 规则约束转自然语言（_format_constraints_hint）
        - 概率推断仅传关键信号，非完整 intent dict
        - 权重作为显式引导（_format_preference_hint）
        """
        user_input = state.get("original_query", "")
        context = state.get("context", {})
        driving_context = state.get("driving_context")
        stages = state.get("stages")

        rules_result = apply_rules(driving_context) if driving_context else {}
        state["rules_result"] = rules_result
        constraints_hint = self._format_constraints_hint(rules_result)
        preference_hint = await self._format_preference_hint()

        prob_hint = ""
        if is_enabled() and self._memory_mode == MemoryMode.MEMORY_BANK:
            try:
                intent = await infer_intent(
                    user_input,
                    self.memory_module,
                    user_id=self.current_user,
                )
                risk = compute_interrupt_risk(driving_context or {})
                if intent.get("intent_confidence", 0) > _INTENT_CONFIDENCE_THRESHOLD:
                    prob_hint = (
                        f"用户当前意图倾向：{intent.get('type', 'unknown')}"
                        f"（置信度 {intent.get('intent_confidence', 0)}）。"
                    )
                if risk >= OVERLOADED_WARNING_THRESHOLD:
                    prob_hint += "⚠ 当前打断风险较高，请谨慎决定。"
            except AppError as e:
                logger.warning("Probabilistic inference failed: %s", e)

        prompt_parts: list[str] = [
            f"用户输入：{user_input}",
            f"驾驶上下文：{json.dumps(context, ensure_ascii=False)}",
        ]
        if prob_hint:
            prompt_parts.append(prob_hint)
        if constraints_hint:
            prompt_parts.append(f"安全约束：{constraints_hint}")
        if preference_hint:
            prompt_parts.append(f"用户偏好：{preference_hint}")
        prompt_body = "\n\n".join(prompt_parts)

        # JointDecision prompt 使用 format() 注入 constraints/preference
        system_prompt = SYSTEM_PROMPTS["joint_decision"].format(
            constraints_hint=constraints_hint or "无特殊约束。",
            preference_hint=preference_hint or "无特殊偏好。",
        )
        full_prompt = f"{system_prompt}\n\n{prompt_body}"
        parsed = await self._call_llm_json(full_prompt)

        try:
            validated = JointDecisionOutput.model_validate(parsed.data or {})
            task = {
                "type": validated.task_type,
                "confidence": validated.confidence,
                "entities": validated.entities,
            }
            decision = validated.decision
        except ValidationError as e:
            logger.warning("JointDecisionOutput validation failed: %s", e)
            raw = parsed.data or {}
            decision = raw.get("decision", {})
            task = {
                "type": raw.get("task_type") or raw.get("type", "general"),
                "confidence": raw.get("confidence", 0.0),
                "entities": raw.get("entities", []),
            }

        # postpone 由规则引擎决定
        if rules_result:
            decision["postpone"] = rules_result.get("postpone", False)

        if stages is not None:
            stages.task = task
            stages.decision = decision

        return {"task": task, "decision": decision}

    @staticmethod
    def _extract_content(decision: dict) -> str:
        """从决策 dict 中提取提醒内容。"""
        return ReminderContent.from_decision(decision)

    async def _check_frequency_guard(
        self,
        state: AgentState,
    ) -> str | None:
        """检查频次约束，返回抑制消息或 None。"""
        driving_ctx = state.get("driving_context")
        if not driving_ctx:
            return None
        constraints = state.get("rules_result") or {}
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

    async def _handle_cancel(
        self,
        state: AgentState,
        stages: WorkflowStages | None,
    ) -> dict:
        pm = PendingReminderManager(user_data_dir(self.current_user))
        cancelled = await pm.cancel_last()
        result = "提醒已取消" if cancelled else "暂无待取消的提醒"
        if stages is not None:
            stages.execution = {
                "content": None,
                "event_id": None,
                "result": result,
                "cancelled": cancelled,
            }
        return {
            "result": result,
            "event_id": None,
            "action_result": {"cancelled": cancelled},
        }

    async def _handle_tool_calls(self, decision: dict) -> None:
        tool_calls = decision.get("tool_calls", [])
        if not tool_calls or not isinstance(tool_calls, list):
            return
        executor = get_default_executor()
        tool_results: list[str] = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                t_name = tc.get("tool", "")
                t_params = tc.get("params", {})
                try:
                    t_result = await executor.execute(t_name, t_params)
                    tool_results.append(f"[{t_name}] {t_result}")
                except WorkflowError:
                    raise
                except ToolExecutionError as e:
                    tool_results.append(f"[{t_name}] 失败: {e}")
                except AppError:
                    raise
        if tool_results:
            logger.info("Tool call results: %s", "; ".join(tool_results))

    async def _handle_postpone(
        self,
        decision: dict,
        state: AgentState,
        driving_ctx: dict | None,
        rules_result: dict,
        modifications: list[str],
        stages: WorkflowStages | None,
    ) -> dict:
        output_router = OutputRouter()
        output_content = output_router.route(decision, rules_result)

        pm = PendingReminderManager(user_data_dir(self.current_user))
        trigger_type, trigger_target, trigger_text = _map_pending_trigger(
            decision, driving_ctx
        )
        pending_ids: list[str] = []

        if trigger_type == "location_time":
            loc_target = trigger_target.get("location", {})
            time_target = trigger_target.get("time", "")
            if (
                loc_target.get("latitude") is not None
                and loc_target.get("longitude") is not None
            ):
                pr1 = await pm.add(
                    content=output_content,
                    trigger_type="location",
                    trigger_target=loc_target,
                    event_id="",
                    trigger_text="到达目的地时",
                )
                pending_ids.append(pr1.id)
            if time_target:
                pr2 = await pm.add(
                    content=output_content,
                    trigger_type="time",
                    trigger_target={"time": time_target},
                    event_id="",
                    trigger_text=f"{_format_time_for_display(time_target)} 时",
                )
                pending_ids.append(pr2.id)
        else:
            pr = await pm.add(
                content=output_content,
                trigger_type=trigger_type,
                trigger_target=trigger_target,
                event_id="",
                trigger_text=trigger_text,
            )
            pending_ids = [pr.id]

        reason = decision.get("reason", "")
        result = (
            f"提醒已延后：{reason}。将在条件满足时提醒"
            if reason
            else "提醒已延后，将在条件满足时提醒"
        )
        if stages is not None:
            stages.execution = {
                "content": None,
                "event_id": None,
                "result": result,
                "pending_reminder_ids": pending_ids,
                "modifications": modifications,
            }
        return {
            "result": result,
            "event_id": None,
            "output_content": output_content.model_dump(),
            "pending_reminder_id": pending_ids[0] if pending_ids else None,
        }

    async def _handle_immediate_send(
        self,
        decision: dict,
        state: AgentState,
        driving_ctx: dict | None,
        rules_result: dict,
        modifications: list[str],
        stages: WorkflowStages | None,
    ) -> dict:
        content = self._extract_content(decision)
        original_query = state.get("original_query", "")

        output_router = OutputRouter()
        output_content = output_router.route(decision, rules_result)

        safe_ctx = sanitize_context(driving_ctx) if driving_ctx else None
        if safe_ctx is not None and stages is not None:
            stages.context = safe_ctx

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
                "output": output_content.model_dump(),
                "modifications": modifications,
            }
        return {
            "result": result,
            "event_id": event_id,
            "output_content": output_content.model_dump(),
        }

    async def _execution_node(self, state: AgentState) -> dict:
        decision = state.get("decision") or {}
        stages = state.get("stages")

        action = decision.get("action", "")
        if action == "cancel_last":
            return await self._handle_cancel(state, stages)

        driving_ctx = state.get("driving_context")
        decision, modifications = AgentWorkflow._ensure_postprocessed(
            decision, driving_ctx
        )

        # 同步 stages.decision 为 post-postprocess 版本——
        # 消融实验通过 stages.decision 读取最终决策送 Judge 评分，
        # 若不同步则 Full 流水线送 pre-postprocess（含违规）而 SingleLLM 送 post-postprocess，
        # 造成不公平比较。
        if stages is not None:
            stages.decision = decision

        if not decision.get("should_remind", True):
            result = "提醒已取消：安全规则禁止发送"
            if stages is not None:
                stages.execution = {
                    "content": None,
                    "event_id": None,
                    "result": result,
                    "modifications": modifications,
                }
            return {"result": result, "event_id": None}

        await self._handle_tool_calls(decision)

        if "rules_result" in state:
            rules_result = state["rules_result"] or {}
        else:
            rules_result = apply_rules(driving_ctx) if driving_ctx else {}
            state["rules_result"] = rules_result

        postpone = decision.get("postpone", False)
        timing = decision.get("timing", "")

        if postpone or timing in ("delay", "location", "location_time"):
            return await self._handle_postpone(
                decision, state, driving_ctx, rules_result, modifications, stages
            )

        freq_msg = await self._check_frequency_guard(state)
        if freq_msg is not None:
            if stages is not None:
                stages.execution = {
                    "content": None,
                    "event_id": None,
                    "result": freq_msg,
                    "modifications": modifications,
                }
            return {"result": freq_msg, "event_id": None}

        return await self._handle_immediate_send(
            decision, state, driving_ctx, rules_result, modifications, stages
        )

    async def run_with_stages(
        self,
        user_input: str,
        driving_context: dict | None = None,
        session_id: str | None = None,
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
            "session_id": session_id,
        }

        try:
            # --- 快捷指令检查 ---
            shortcut_decision = self._shortcuts.resolve(user_input)
            if shortcut_decision:
                shortcut_decision, _modifications = AgentWorkflow._ensure_postprocessed(
                    shortcut_decision, driving_context
                )
                state["decision"] = shortcut_decision
                exec_result = await self._execution_node(state)
                state.update(exec_result)
                result = state.get("result") or "处理完成"
                event_id = state.get("event_id")
                self._log_conversation_turn(state, session_id, user_input)
                return result, event_id, stages

            for node_fn in self._nodes:
                updates = await node_fn(state)
                state.update(updates)

            result = state.get("result") or "处理完成"
            event_id = state.get("event_id")

        except Exception as e:
            logger.warning("run_with_stages failed: %s", e, exc_info=True)
            if session_id:
                self._log_conversation_turn(state, session_id, user_input)
            raise
        else:
            if session_id:
                self._log_conversation_turn(state, session_id, user_input)
            return result, event_id, stages

    async def proactive_run(
        self,
        context_override: dict | None = None,
        memory_hints: list[dict] | None = None,
        trigger_source: str = "scheduler",
    ) -> tuple[str, str | None, WorkflowStages]:
        """主动模式：无用户 query，由 scheduler/context 变化触发。

        Args:
            context_override: 外部提供的驾驶上下文（非 None 时跳过 LLM context 推断）
            memory_hints: 预检索的相关记忆列表
            trigger_source: 触发来源（scheduler/location/time/state）

        Returns:
            (result, event_id, stages) 同 run_with_stages

        """
        stages = WorkflowStages()
        state: AgentState = {
            "original_query": f"[proactive:{trigger_source}]",
            "context": {},
            "task": None,
            "decision": None,
            "result": None,
            "event_id": None,
            "driving_context": context_override,
            "stages": stages,
            "session_id": None,
        }

        if context_override:
            context = dict(context_override)
            context["current_datetime"] = datetime.now(UTC).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            context["related_events"] = memory_hints or []
            state["context"] = context
            if stages is not None:
                stages.context = context
        else:
            try:
                updates = await self._context_node(state)
                state.update(updates)
            except Exception as e:
                logger.warning("proactive_run context_node failed: %s", e)
                return "主动模式不可用：无法获取上下文", None, stages

        rules_result = apply_rules(context_override) if context_override else {}
        constraints_hint = self._format_constraints_hint(rules_result)
        preference_hint = await self._format_preference_hint()

        prompt = PROACTIVE_JOINT_DECISION_PROMPT.format(
            constraints_hint=constraints_hint or "无特殊约束。",
            preference_hint=preference_hint or "无特殊偏好。",
        )
        prompt += f"\n驾驶上下文：{json.dumps(state['context'], ensure_ascii=False)}"
        prompt += f"\n触发来源：{trigger_source}"

        try:
            parsed = await self._call_llm_json(prompt)
        except Exception as e:
            logger.warning("proactive_run LLM call failed: %s", e)
            return "主动模式不可用：LLM 调用失败", None, stages

        try:
            validated = JointDecisionOutput.model_validate(parsed.data or {})
            decision = validated.decision
        except Exception as e:
            logger.warning("proactive_run JointDecision validation failed: %s", e)
            raw = parsed.data or {}
            decision = raw.get("decision", {})

        decision, _modifications = AgentWorkflow._ensure_postprocessed(
            decision, stages.context
        )

        state["decision"] = decision
        state["task"] = {"type": "proactive", "confidence": 1.0, "entities": []}

        try:
            exec_result = await self._execution_node(state)
            state.update(exec_result)
        except Exception as e:
            logger.warning("proactive_run execution_node failed: %s", e)
            return "主动提醒处理失败", None, stages

        result = state.get("result") or "处理完成"
        event_id = state.get("event_id")
        return result, event_id, stages

    async def execute_pending_reminder(
        self,
        content: str,
        driving_context: dict | None = None,
        trigger_source: str = "pending_reminder",
    ) -> tuple[str, str | None, WorkflowStages]:
        """对已确定内容的 pending reminder 跳过 LLM，仅走 Execution。"""
        stages = WorkflowStages()
        decision: dict = {
            "should_remind": True,
            "reminder_content": content,
            "action": "remind",
            "timing": "immediate",
            "channel": "audio",
        }
        state: AgentState = {
            "original_query": f"[proactive:{trigger_source}]",
            "context": {},
            "task": None,
            "decision": decision,
            "result": None,
            "event_id": None,
            "driving_context": driving_context,
            "stages": stages,
            "session_id": None,
        }
        try:
            exec_result = await self._execution_node(state)
            state.update(exec_result)
        except Exception as e:
            logger.warning("execute_pending_reminder failed: %s", e)
            return "待触发提醒处理失败", None, stages
        result = state.get("result") or "处理完成"
        event_id = state.get("event_id")
        return result, event_id, stages

    @staticmethod
    def _build_done_data(state: AgentState, session_id: str | None) -> dict:
        """构建 done 事件 data 字典。"""
        done_data: dict[str, object] = {
            "event_id": state.get("event_id"),
            "session_id": session_id,
        }
        pending_id = state.get("pending_reminder_id")
        if pending_id:
            done_data["status"] = "pending"
            done_data["pending_reminder_id"] = pending_id
        elif state.get("result") and any(
            kw in str(state.get("result")) for kw in ("取消", "抑制")
        ):
            done_data["status"] = "suppressed"
            done_data["reason"] = state.get("result")
        else:
            done_data["status"] = "delivered"
            done_data["result"] = state.get("output_content")
        return done_data

    def _log_conversation_turn(
        self, state: AgentState, session_id: str | None, user_input: str
    ) -> None:
        if session_id:
            self._conversations.add_turn(
                session_id,
                user_input,
                state.get("decision") or {},
                state.get("result") or "",
            )

    async def run_stream(
        self,
        user_input: str,
        driving_context: dict | None = None,
        session_id: str | None = None,
    ) -> AsyncGenerator[dict]:
        """SSE 流式方法，逐阶段 yield 事件。

        每个阶段完成后立即 yield，不等待全部阶段结束。
        """
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
            "session_id": session_id,
        }

        # --- 快捷指令检查 ---
        shortcut_decision = self._shortcuts.resolve(user_input)
        if shortcut_decision:
            shortcut_decision, _modifications = AgentWorkflow._ensure_postprocessed(
                shortcut_decision, driving_context
            )
            state["decision"] = shortcut_decision
            try:
                exec_result = await self._execution_node(state)
                state.update(exec_result)
                done_data = self._build_done_data(state, session_id)
                yield {"event": "done", "data": done_data}
            except Exception as e:
                logger.warning("run_stream shortcut stage failed: %s", e, exc_info=True)
                yield {
                    "event": "error",
                    "data": {"code": "INTERNAL", "message": str(e)},
                }
            self._log_conversation_turn(state, session_id, user_input)
            return

        # Stage 1: Context
        yield {"event": "stage_start", "data": {"stage": "context"}}
        try:
            updates = await self._context_node(state)
            state.update(updates)
            yield {"event": "context_done", "data": {"context": state["context"]}}
        except Exception as e:
            logger.warning(
                "run_stream %s stage failed: %s", "context", e, exc_info=True
            )
            yield {
                "event": "error",
                "data": {"code": "CONTEXT_FAILED", "message": str(e)},
            }
            self._log_conversation_turn(state, session_id, user_input)
            return

        # Stage 2: JointDecision
        yield {"event": "stage_start", "data": {"stage": "joint_decision"}}
        try:
            updates = await self._joint_decision_node(state)
            state.update(updates)
            task = state.get("task") or {}
            decision = state.get("decision") or {}
            yield {
                "event": "decision",
                "data": {
                    "should_remind": decision.get("should_remind"),
                    "task_type": task.get("type", "general"),
                },
            }
        except Exception as e:
            logger.warning(
                "run_stream %s stage failed: %s", "joint_decision", e, exc_info=True
            )
            yield {
                "event": "error",
                "data": {"code": "JOINT_DECISION_FAILED", "message": str(e)},
            }
            self._log_conversation_turn(state, session_id, user_input)
            return

        # Stage 3: Execution
        yield {"event": "stage_start", "data": {"stage": "execution"}}
        try:
            updates = await self._execution_node(state)
            state.update(updates)
            done_data = self._build_done_data(state, session_id)
            yield {"event": "done", "data": done_data}
        except Exception as e:
            logger.warning(
                "run_stream %s stage failed: %s", "execution", e, exc_info=True
            )
            yield {
                "event": "error",
                "data": {"code": "EXECUTION_FAILED", "message": str(e)},
            }
            self._log_conversation_turn(state, session_id, user_input)
            return

        self._log_conversation_turn(state, session_id, user_input)
