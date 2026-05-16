"""JointDecision Agent：合并 Task 归因 + 策略决策为一次 LLM 调用."""

import contextvars
import json
import logging

from pydantic import ValidationError

from app.agents.probabilistic import (
    OVERLOADED_WARNING_THRESHOLD,
    compute_interrupt_risk,
    infer_intent,
    is_enabled,
)
from app.agents.prompts import SYSTEM_PROMPTS
from app.agents.prompts_proactive import PROACTIVE_JOINT_DECISION_PROMPT
from app.agents.rules import apply_rules
from app.agents.state import AgentState
from app.agents.types import JointDecisionOutput, call_llm_json
from app.exceptions import AppError
from app.memory.memory import MemoryModule
from app.storage.toml_store import TOMLStore

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


class JointDecisionAgent:
    """JointDecision 阶段 Agent：合并 Task 归因 + 策略决策."""

    def __init__(
        self,
        memory: MemoryModule,
        strategies_store: TOMLStore,
        current_user: str,
    ) -> None:
        self._memory = memory
        self._strategies_store = strategies_store
        self._current_user = current_user

    @staticmethod
    def format_constraints_hint(rules_result: dict | None) -> str:
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

    async def run(self, state: AgentState) -> dict:
        """执行 JointDecision 阶段（响应式）."""
        user_input = state.get("original_query", "")
        context = state.get("context", {})
        driving_context = state.get("driving_context")
        stages = state.get("stages")

        rules_result = apply_rules(driving_context) if driving_context else {}
        state["rules_result"] = rules_result
        constraints_hint = self.format_constraints_hint(rules_result)
        preference_hint = await self._format_preference_hint()

        prob_hint = ""
        if is_enabled():
            try:
                intent = await infer_intent(
                    user_input,
                    self._memory,
                    user_id=self._current_user,
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

        system_prompt = SYSTEM_PROMPTS["joint_decision"].format(
            constraints_hint=constraints_hint or "无特殊约束。",
            preference_hint=preference_hint or "无特殊偏好。",
        )
        full_prompt = f"{system_prompt}\n\n{prompt_body}"
        parsed = await call_llm_json(
            self._memory.chat_model, full_prompt, max_tokens=2048
        )

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
            _decision = raw.get("decision", {})
            decision = _decision if isinstance(_decision, dict) else {}
            task = {
                "type": raw.get("task_type") or raw.get("type", "general"),
                "confidence": raw.get("confidence", 0.0),
                "entities": raw.get("entities", []),
            }

        if rules_result:
            decision["postpone"] = rules_result.get("postpone", False)

        if stages is not None:
            stages.task = task
            stages.decision = decision

        return {"task": task, "decision": decision}

    async def run_proactive(self, state: AgentState, trigger_source: str) -> dict:
        """执行 JointDecision 阶段（主动式）."""
        driving_context = state.get("driving_context")
        stages = state.get("stages")

        rules_result = apply_rules(driving_context) if driving_context else {}
        state["rules_result"] = rules_result
        constraints_hint = self.format_constraints_hint(rules_result)
        preference_hint = await self._format_preference_hint()

        prompt = PROACTIVE_JOINT_DECISION_PROMPT.format(
            constraints_hint=constraints_hint or "无特殊约束。",
            preference_hint=preference_hint or "无特殊偏好。",
        )
        prompt += (
            f"\n驾驶上下文：{json.dumps(state.get('context', {}), ensure_ascii=False)}"
        )
        prompt += f"\n触发来源：{trigger_source}"

        parsed = await call_llm_json(self._memory.chat_model, prompt, max_tokens=2048)

        try:
            validated = JointDecisionOutput.model_validate(parsed.data or {})
            decision = validated.decision
        except ValidationError as e:
            logger.warning("proactive JointDecision validation failed: %s", e)
            raw = parsed.data or {}
            _decision = raw.get("decision", {})
            decision = _decision if isinstance(_decision, dict) else {}

        task = {"type": "proactive", "confidence": 1.0, "entities": []}

        if stages is not None:
            stages.task = task
            stages.decision = decision

        return {"task": task, "decision": decision}
