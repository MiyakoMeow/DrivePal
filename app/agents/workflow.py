"""Agent工作流编排模块——薄编排器.

三阶段 Agent 各自独立实现，本模块仅负责：
1. 实例化 Context / JointDecision / Execution 三 Agent
2. 提供 run_with_stages / run_stream / proactive_run / execute_pending_reminder 编排入口
3. 快捷指令检查 + 对话记录写入
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

from app.agents.context_agent import ContextAgent
from app.agents.conversation import _conversation_manager
from app.agents.execution_agent import ExecutionAgent
from app.agents.joint_decision_agent import (
    JointDecisionAgent,
    get_ablation_disable_feedback,
    set_ablation_disable_feedback,
)
from app.agents.shortcuts import ShortcutResolver
from app.agents.state import AgentState, WorkflowStages
from app.agents.types import WorkflowError
from app.config import user_data_dir
from app.exceptions import AppError
from app.memory.memory import MemoryModule
from app.models.chat import get_chat_model
from app.storage.toml_store import TOMLStore

__all__ = [
    "AgentWorkflow",
    "get_ablation_disable_feedback",
    "set_ablation_disable_feedback",
]

logger = logging.getLogger(__name__)

# 阶段超时容忍倍数：实际耗时超过 timeout×此倍数时判定为外层超时误捕
_STAGE_OVERAGE_FACTOR: float = 1.5


class AgentWorkflow:
    """多Agent协作工作流——薄编排器."""

    def __init__(
        self,
        data_dir: Path = Path("data"),
        memory_module: MemoryModule | None = None,
        current_user: str = "default",
    ) -> None:
        """初始化工作流实例."""
        self.data_dir = data_dir
        self.current_user = current_user

        if memory_module is not None:
            self.memory_module = memory_module
        else:
            chat_model = get_chat_model()
            self.memory_module = MemoryModule(data_dir, chat_model=chat_model)
        self._conversations = _conversation_manager
        self._shortcuts = ShortcutResolver()

        strategies_store = TOMLStore(
            user_dir=user_data_dir(current_user),
            filename="strategies.toml",
            default_factory=dict,
        )

        self._context_agent = ContextAgent(
            self.memory_module, self._conversations, current_user
        )
        self._joint_decision_agent = JointDecisionAgent(
            self.memory_module, strategies_store, current_user
        )
        self._execution_agent = ExecutionAgent(self.memory_module, current_user)

        self._nodes = [
            self._context_node,
            self._joint_decision_node,
            self._execution_node,
        ]

    @staticmethod
    def _validate_timeout(stage_name: str, timeout: float) -> None:
        """校验阶段超时值为正数，无效则抛 WorkflowError。"""
        if timeout <= 0:
            raise WorkflowError(
                code="INVALID_STAGE_TIMEOUT",
                message=f"Stage {stage_name}: invalid timeout value {timeout}",
            )

    async def _context_node(self, state: AgentState) -> dict:
        return await self._context_agent.run(state)

    async def _joint_decision_node(self, state: AgentState) -> dict:
        return await self._joint_decision_agent.run(state)

    async def _execution_node(self, state: AgentState) -> dict:
        return await self._execution_agent.run(state)

    async def run_with_stages(
        self,
        user_input: str,
        driving_context: dict | None = None,
        session_id: str | None = None,
        stage_timeout: dict[str, float] | None = None,
    ) -> tuple[str, str | None, WorkflowStages]:
        """运行完整工作流并返回结果、事件ID和各阶段输出.

        Args:
            user_input: 用户输入文本
            driving_context: 驾驶上下文信息
            session_id: 会话ID
            stage_timeout: 各阶段超时（秒），键为阶段名（context/joint_decision/execution）

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

        try:
            shortcut_decision = self._shortcuts.resolve(user_input)
            if shortcut_decision:
                shortcut_decision, _modifications = ExecutionAgent.ensure_postprocessed(
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
                stage_name = node_fn.__name__.replace("_node", "").lstrip("_")
                t0 = time.perf_counter()
                logger.info("stage=%s start", stage_name)

                timeout = stage_timeout.get(stage_name) if stage_timeout else None
                if timeout is not None:
                    self._validate_timeout(stage_name, timeout)
                    try:
                        async with asyncio.timeout(timeout):
                            updates = await node_fn(state)
                    except TimeoutError:
                        elapsed = (time.perf_counter() - t0) * 1000
                        # 确认 TimeoutError 来自本阶段 asyncio.timeout：若实际耗时
                        # 远小于阈值则不属此超时，重抛供外层处理（防误捕非此源的
                        # TimeoutError）。
                        if elapsed < timeout * 1000 * 0.95:
                            logger.warning(
                                "stage=%s TimeoutError at %.1fms (limit=%.1fs) "
                                "— not from this stage timeout, re-raising",
                                stage_name,
                                elapsed,
                                timeout,
                            )
                            raise
                        # 若实际耗时远超阶段超时阈值，可能是外层 variant 超时
                        # (300s) 在此被内层捕获。重抛 TimeoutError 让外层处理。
                        if elapsed > timeout * 1000 * _STAGE_OVERAGE_FACTOR:
                            logger.warning(
                                "stage=%s elapsed=%.1fms exceeds stage timeout by %.1fx, "
                                "likely outer variant timeout — re-raising",
                                stage_name,
                                elapsed,
                                elapsed / (timeout * 1000),
                            )
                            raise
                        logger.warning(
                            "stage=%s timeout after %.1fms (limit=%.1fs)",
                            stage_name,
                            elapsed,
                            timeout,
                        )
                        raise WorkflowError(
                            code="STAGE_TIMEOUT",
                            message=f"Stage {stage_name} timed out after {timeout}s",
                        ) from None
                else:
                    updates = await node_fn(state)

                elapsed = (time.perf_counter() - t0) * 1000
                logger.info("stage=%s end (%.1fms)", stage_name, elapsed)
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
        """主动模式：无用户 query，由 scheduler/context 变化触发。"""
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

        try:
            jd_updates = await self._joint_decision_agent.run_proactive(
                state, trigger_source
            )
            state.update(jd_updates)
        except Exception as e:
            logger.warning("proactive_run LLM call failed: %s", e)
            return "主动模式不可用：LLM 调用失败", None, stages

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
        except AppError:
            raise
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
        if state.get("tool_results"):
            done_data["tool_results"] = state["tool_results"]
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
        """SSE 流式方法，逐阶段 yield 事件。"""
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

        shortcut_decision = self._shortcuts.resolve(user_input)
        if shortcut_decision:
            shortcut_decision, _modifications = ExecutionAgent.ensure_postprocessed(
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
