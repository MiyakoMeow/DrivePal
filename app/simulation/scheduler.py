"""事件调度器，扫描提醒事件并触发工作流."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from app.simulation.ws_notify import broadcast_reminder

if TYPE_CHECKING:
    from app.simulation.clock import SimulationClock
    from app.simulation.state import _SimulationState

logger = logging.getLogger(__name__)


class EventScheduler:
    """事件调度器，定期扫描事件存储并触发提醒."""

    def __init__(
        self,
        clock: SimulationClock,
        state: _SimulationState,
        event_storage: Any,  # noqa: ANN401
        workflow_factory: Callable[[], Any] | None = None,
        poll_interval: float = 2.0,
    ) -> None:
        """初始化调度器."""
        self._clock = clock
        self._state = state
        self._event_storage = event_storage
        self._workflow_factory = workflow_factory
        self._poll_interval = poll_interval
        self._notified: set[str] = set()
        self._task: asyncio.Task[None] | None = None
        self._running: bool = False

    def start(self) -> None:
        """启动后台轮询任务."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())

    def stop(self) -> None:
        """停止调度器并清除已通知集合."""
        self._running = False
        self._notified.clear()
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except Exception as e:
                logger.warning("Scheduler tick error: %s", e)
            await asyncio.sleep(self._poll_interval)

    async def tick(self) -> None:
        """扫描事件并触发满足条件的提醒."""
        events = await self._event_storage.read_events()
        now = self._clock.now()

        for event in events:
            evt_id = event.get("id")
            remind_at = event.get("remind_at")

            if not evt_id or not remind_at:
                continue

            if evt_id in self._notified:
                continue

            try:
                remind_dt = datetime.fromisoformat(remind_at)
            except ValueError, TypeError:
                continue

            if now < remind_dt:
                continue

            self._notified.add(evt_id)

            decision: dict | None = None
            if self._workflow_factory is not None:
                try:
                    decision = await self._run_mini_workflow(event)
                except Exception as e:
                    logger.warning("Mini-workflow failed for %s: %s", evt_id, e)

            reminder: dict[str, Any] = {
                "event_id": evt_id,
                "content": event.get("content", ""),
                "remind_at": remind_at,
            }
            if decision:
                reminder["decision"] = decision

            await broadcast_reminder(reminder)

    async def _run_mini_workflow(self, event: dict) -> dict:
        """运行精简工作流获取策略决策."""
        from app.agents.state import AgentState, WorkflowStages

        factory = self._workflow_factory
        assert factory is not None
        workflow = factory()
        stages = WorkflowStages()

        user_input = event.get("content", "")
        driving_context = self._state.get_context().model_dump()

        state: AgentState = {
            "messages": [{"role": "user", "content": user_input}],
            "context": {},
            "task": None,
            "decision": None,
            "result": None,
            "event_id": None,
            "driving_context": driving_context,
            "stages": stages,
        }

        for node_fn in [
            workflow._context_node,
            workflow._task_node,
            workflow._strategy_node,
        ]:
            updates = await node_fn(state)
            state.update(updates)

        return stages.decision
