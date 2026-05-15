"""主动调度器主循环。"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.agents.pending import PendingReminderManager
from app.config import user_data_dir
from app.memory.schemas import EVENT_TYPE_PASSIVE_VOICE, MemoryEvent
from app.scheduler.context_monitor import ContextDelta, ContextMonitor
from app.scheduler.memory_scanner import MemoryScanner
from app.scheduler.trigger_evaluator import TriggerEvaluator, TriggerSignal

if TYPE_CHECKING:
    from app.agents.workflow import AgentWorkflow
    from app.api.v1.ws_manager import WSManager
    from app.memory.memory import MemoryModule

logger = logging.getLogger(__name__)

_REVIEW_HOUR = 8
_REVIEW_WINDOW_MINUTES = 5
_FATIGUE_HIGH = 0.7


class ProactiveScheduler:
    """主动调度器：后台轮询上下文+记忆，触发 AgentWorkflow 主动模式。"""

    @staticmethod
    def _load_config() -> dict:
        """从 config/scheduler.toml 读取调度器配置。"""
        path = Path("config/scheduler.toml")
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
            return data.get("scheduler", {})
        except OSError, tomllib.TOMLDecodeError:
            logger.warning("Failed to read %s, using defaults", path)
            return {}

    def __init__(
        self,
        workflow: AgentWorkflow,
        memory_module: MemoryModule,
        user_id: str = "default",
        tick_interval: float | None = None,
        debounce_seconds: float | None = None,
        ws_manager: WSManager | None = None,
    ) -> None:
        """初始化 ProactiveScheduler。

        Args:
            workflow: AgentWorkflow 实例。
            memory_module: 统一记忆管理模块。
            user_id: 目标用户 ID。
            tick_interval: 轮询间隔（秒）。
            debounce_seconds: 去抖间隔（秒）。
            ws_manager: WebSocket 管理器实例，用于广播主动提醒。

        """
        self._workflow = workflow
        self._memory_scanner = MemoryScanner(memory_module, user_id)
        # 从 config/scheduler.toml 读取配置，参数可覆盖
        _cfg = self._load_config()
        if tick_interval is None:
            tick_interval = _cfg.get("tick_interval_seconds", 15)
        if debounce_seconds is None:
            debounce_seconds = _cfg.get("debounce_seconds", 30)
        proximity = _cfg.get("location_proximity_meters", 500)
        context_monitor_cfg = _cfg.get("context_monitor", {})
        fatigue_delta = context_monitor_cfg.get("fatigue_delta_threshold", 0.1)
        self._context_monitor = ContextMonitor(
            proximity_meters=proximity, fatigue_delta_threshold=fatigue_delta
        )
        self._trigger_evaluator = TriggerEvaluator(debounce_seconds)
        self._tick_interval = tick_interval
        self._ws_manager = ws_manager
        self._task: asyncio.Task | None = None
        self._running = False
        self._voice_queue: asyncio.Queue[str] = asyncio.Queue()
        self._current_context: dict = {}
        self._pending_manager: PendingReminderManager | None = None
        self._last_review_date: str | None = None

    async def push_voice_text(self, text: str) -> None:
        """推入一条被动语音文本到队列。"""
        await self._voice_queue.put(text)

    def update_context(self, ctx: dict) -> None:
        """更新当前驾驶上下文。"""
        self._current_context = ctx

    async def _poll_pending(self, ctx: dict) -> None:
        """轮询 PendingReminder 触发条件。"""
        if self._pending_manager is None:
            self._pending_manager = PendingReminderManager(
                user_data_dir(self._workflow.current_user)
            )
        pm = self._pending_manager
        triggered = await pm.poll(ctx)
        for tr in triggered:
            logger.info("PendingReminder triggered: %s", tr.get("id"))
            try:
                result, event_id, _ = await self._workflow.proactive_run(
                    context_override=ctx,
                    trigger_source="pending_reminder",
                )
                if event_id:
                    logger.info(
                        "PendingReminder executed: %s → %s",
                        tr.get("id"),
                        result,
                    )
            except (OSError, RuntimeError, ValueError, TypeError) as e:
                logger.warning(
                    "PendingReminder execution failed: %s",
                    e,
                )

    async def _scan_context_changes(self, ctx: dict, delta: ContextDelta) -> list[dict]:
        """检查上下文变化并检索相关记忆。"""
        memory_hints: list[dict] = []
        if delta.scenario_changed:
            hints = await self._memory_scanner.scan_by_scenario_change(
                old_scenario="", new_scenario=ctx.get("scenario", "")
            )
            memory_hints.extend(hints)
        if delta.location_changed:
            nearby = await self._memory_scanner.scan_by_context(ctx, top_k=5)
            memory_hints.extend(nearby)
        return memory_hints

    def _build_signals(
        self, ctx: dict, delta: ContextDelta, memory_hints: list[dict]
    ) -> list[TriggerSignal]:
        """根据上下文变化构建触发信号列表。"""
        signals: list[TriggerSignal] = []
        ctx_copy = copy.deepcopy(ctx)

        if delta.scenario_changed:
            signals.append(
                TriggerSignal(
                    source="context_change",
                    priority=1,
                    context=ctx_copy,
                    memory_hints=memory_hints,
                )
            )
        if delta.location_changed:
            signals.append(
                TriggerSignal(
                    source="location",
                    priority=1,
                    context=ctx_copy,
                    memory_hints=memory_hints,
                )
            )
        if delta.fatigue_increased or delta.workload_changed:
            signals.append(
                TriggerSignal(
                    source="state",
                    priority=2,
                    context=ctx_copy,
                    memory_hints=memory_hints,
                )
            )

        today = datetime.now(UTC)
        today_str = today.strftime("%Y-%m-%d")
        if (
            today.hour == _REVIEW_HOUR
            and today.minute < _REVIEW_WINDOW_MINUTES
            and self._last_review_date != today_str
        ):
            self._last_review_date = today_str
            signals.append(
                TriggerSignal(source="periodic", priority=0, context=ctx_copy)
            )

        fatigue = ctx.get("driver_state", {}).get("fatigue_level", 0)
        workload = ctx.get("driver_state", {}).get("workload", "")
        if fatigue > _FATIGUE_HIGH or workload == "overloaded":
            signals.append(
                TriggerSignal(
                    source="state",
                    priority=2,
                    context=ctx_copy,
                    memory_hints=memory_hints,
                )
            )

        return signals

    async def _evaluate_and_execute(
        self, signals: list[TriggerSignal], ctx: dict
    ) -> None:
        """评估触发信号并执行主动工作流。"""
        for sig in signals:
            decision = self._trigger_evaluator.evaluate(sig, ctx or None)
            if decision.should_trigger:
                try:
                    result, event_id, _ = await self._workflow.proactive_run(
                        context_override=ctx or None,
                        memory_hints=sig.memory_hints,
                        trigger_source=sig.source,
                    )
                    if event_id:
                        logger.info(
                            "Proactive trigger: %s → %s (event=%s)",
                            sig.source,
                            result,
                            event_id,
                        )
                        if self._ws_manager:
                            await self._ws_manager.broadcast_reminder(
                                self._workflow.current_user,
                                {
                                    "content": {"speakable_text": result or ""},
                                    "trigger_source": sig.source,
                                    "interrupt_level": decision.interrupt_level,
                                },
                            )
                except (OSError, RuntimeError, ValueError, TypeError) as e:
                    logger.warning("proactive_run failed for %s: %s", sig.source, e)

    async def _drain_voice_queue(self) -> None:
        """消费语音队列，写入被动语音记忆。"""
        while not self._voice_queue.empty():
            text = await self._voice_queue.get()
            text = text.strip()
            if not text:
                continue
            event = MemoryEvent(
                content=text,
                type=EVENT_TYPE_PASSIVE_VOICE,
                created_at=datetime.now(UTC).isoformat(),
            )
            try:
                await self._workflow.memory_module.write(
                    event, user_id=self._workflow.current_user
                )
                logger.info("Passive voice memory written: %.50s", text)
            except (OSError, RuntimeError, ValueError, TypeError) as e:
                logger.warning("Failed to write passive voice: %s", e)

    async def _tick(self) -> None:
        """单次 tick：语音消费、PendingReminder 轮询、上下文变化检测、触发执行。"""
        try:
            await self._drain_voice_queue()
        except Exception as e:
            logger.warning("Voice queue drain failed: %s", e)

        ctx: dict | None = self._current_context
        if not ctx:
            ctx = {}

        try:
            if ctx:
                await self._poll_pending(ctx)
        except Exception as e:
            logger.warning("Pending poll failed: %s", e)

        try:
            delta = (
                self._context_monitor.update(ctx)
                if ctx
                else self._context_monitor.update({})
            )
        except Exception as e:
            logger.warning("Context monitor update failed: %s", e)
            delta = ContextDelta()

        memory_hints: list[dict] = []
        if ctx:
            try:
                memory_hints = await self._scan_context_changes(ctx, delta)
            except Exception as e:
                logger.warning("Context scan failed: %s", e)

        try:
            signals = self._build_signals(ctx, delta, memory_hints) if ctx else []
        except Exception as e:
            logger.warning("Build signals failed: %s", e)
            signals = []

        try:
            await self._evaluate_and_execute(signals, ctx)
        except Exception as e:
            logger.warning("Evaluate and execute failed: %s", e)

    async def run(self) -> None:
        """调度器主循环。"""
        self._running = True
        logger.info("ProactiveScheduler started (tick=%ss)", self._tick_interval)
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.warning("Scheduler tick failed: %s", e)
            await asyncio.sleep(self._tick_interval)
        logger.info("ProactiveScheduler stopped")

    async def start(self) -> None:
        """启动调度器（幂等）。"""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        """停止调度器。"""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
