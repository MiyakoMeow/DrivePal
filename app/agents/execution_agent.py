"""Execution Agent：执行阶段——规则后处理、频次检查、工具调用、提醒发送."""

import base64
import hashlib
import logging
import os
from datetime import UTC, datetime

from app.agents.outputs import OutputRouter
from app.agents.pending import PendingReminderManager
from app.agents.rules import apply_rules, postprocess_decision
from app.agents.state import AgentState, WorkflowStages
from app.agents.types import (
    ReminderContent,
    WorkflowError,
    format_time_for_display,
    map_pending_trigger,
)
from app.config import user_data_dir
from app.exceptions import AppError
from app.memory.memory import MemoryModule
from app.memory.privacy import sanitize_context
from app.memory.types import MemoryMode
from app.tools import get_default_executor
from app.tools.executor import ToolConfirmationRequiredError, ToolExecutionError

logger = logging.getLogger(__name__)


class ExecutionAgent:
    """Execution 阶段 Agent：规则后处理 + 提醒发送."""

    def __init__(self, memory: MemoryModule, current_user: str) -> None:
        self._memory = memory
        self._current_user = current_user
        self._pending_manager: PendingReminderManager | None = None
        self._output_router = OutputRouter()
        self._tts_enabled: bool | None = None

    def _get_tts_enabled(self) -> bool:
        if self._tts_enabled is not None:
            return self._tts_enabled
        env_val = os.environ.get("DRIVEPAL_TTS_ENABLED")
        if env_val is not None:
            self._tts_enabled = env_val.lower() in ("1", "true", "yes")
        else:
            try:
                from app.voice.config import VoiceConfig

                self._tts_enabled = VoiceConfig.load().tts_enabled
            except Exception:
                self._tts_enabled = False
        return self._tts_enabled

    async def _synthesize_tts(self, text: str) -> str | None:
        """合成 TTS 音频，返 base64 编码。失败返 None。"""
        if not text or not self._get_tts_enabled():
            return None
        try:
            from app.voice.tts import get_tts_client

            mp3_bytes = await get_tts_client().synthesize(text)
            if mp3_bytes:
                return base64.b64encode(mp3_bytes).decode("ascii")
        except Exception:
            logger.warning("TTS synthesis failed", exc_info=True)
        return None

    @property
    def pending_manager(self) -> PendingReminderManager:
        """懒初始化 PendingReminderManager，避免每次调用重建。"""
        if self._pending_manager is None:
            self._pending_manager = PendingReminderManager(
                user_data_dir(self._current_user)
            )
        return self._pending_manager

    @staticmethod
    def ensure_postprocessed(
        decision: dict, driving_ctx: dict | None
    ) -> tuple[dict, list[str]]:
        """统一入口：确保 decision 已过规则后处理。幂等。"""
        if decision.get("_postprocessed") or not driving_ctx:
            return decision, []
        decision, modifications = postprocess_decision(decision, driving_ctx)
        decision["_postprocessed"] = True
        return decision, modifications

    async def run(self, state: AgentState) -> dict:
        """执行 Execution 阶段."""
        decision = state.get("decision") or {}
        stages = state.get("stages")

        action = decision.get("action", "")
        if action == "cancel_last":
            return await self._handle_cancel(state, stages)

        driving_ctx = state.get("driving_context")
        decision, modifications = self.ensure_postprocessed(decision, driving_ctx)

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

        await self._handle_tool_calls(decision, state)

        rules_result = self._resolve_rules(state, driving_ctx)
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

    async def _handle_cancel(
        self,
        state: AgentState,
        stages: WorkflowStages | None,
    ) -> dict:
        cancelled = await self.pending_manager.cancel_last()
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

    async def _handle_tool_calls(self, decision: dict, state: AgentState) -> list[str]:
        """执行工具调用，返回结果列表并写入 state."""
        tool_calls = decision.get("tool_calls", [])
        if not tool_calls or not isinstance(tool_calls, list):
            return []
        executor = get_default_executor()
        tool_results: list[str] = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                t_name = tc.get("tool", "")
                t_params = tc.get("params", {})
                try:
                    t_result = await executor.execute(
                        t_name, t_params, driving_context=state.get("driving_context")
                    )
                    tool_results.append(f"[{t_name}] {t_result}")
                except WorkflowError:
                    raise
                except ToolConfirmationRequiredError as e:
                    tool_results.append(f"[{t_name}] {e.message}")
                except ToolExecutionError as e:
                    tool_results.append(f"[{t_name}] 失败: {e}")
                except AppError:
                    raise
        if tool_results:
            logger.info("Tool call results: %s", "; ".join(tool_results))
            state["tool_results"] = tool_results
        return tool_results

    async def _handle_postpone(
        self,
        decision: dict,
        state: AgentState,
        driving_ctx: dict | None,
        rules_result: dict,
        modifications: list[str],
        stages: WorkflowStages | None,
    ) -> dict:
        output_content = self._output_router.route(decision, rules_result)
        audio_base64 = await self._synthesize_tts(output_content.speakable_text)

        trigger_type, trigger_target, trigger_text = map_pending_trigger(
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
                pr1 = await self.pending_manager.add(
                    content=output_content,
                    trigger_type="location",
                    trigger_target=loc_target,
                    event_id="",
                    trigger_text="到达目的地时",
                )
                pending_ids.append(pr1.id)
            if time_target:
                pr2 = await self.pending_manager.add(
                    content=output_content,
                    trigger_type="time",
                    trigger_target={"time": time_target},
                    event_id="",
                    trigger_text=f"{format_time_for_display(time_target)} 时",
                )
                pending_ids.append(pr2.id)
        else:
            pr = await self.pending_manager.add(
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
            "audio_base64": audio_base64,
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
        content = ReminderContent.from_decision(decision)
        original_query = state.get("original_query", "")

        output_content = self._output_router.route(decision, rules_result)
        audio_base64 = await self._synthesize_tts(output_content.speakable_text)

        safe_ctx = sanitize_context(driving_ctx) if driving_ctx else None
        if safe_ctx is not None and stages is not None:
            stages.context = safe_ctx

        interaction_result = await self._memory.write_interaction(
            original_query,
            content,
            mode=MemoryMode.MEMORY_BANK,
            user_id=self._current_user,
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
            "audio_base64": audio_base64,
        }

    async def _check_frequency_guard(
        self,
        state: AgentState,
    ) -> str | None:
        """检查频次约束，返回抑制消息或 None."""
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

    def _resolve_rules(self, state: AgentState, driving_ctx: dict | None) -> dict:
        if "rules_result" in state:
            return state["rules_result"] or {}
        rules_result = apply_rules(driving_ctx) if driving_ctx else {}
        state["rules_result"] = rules_result
        return rules_result
