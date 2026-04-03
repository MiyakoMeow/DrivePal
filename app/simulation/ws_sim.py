"""WebSocket /ws/sim 模拟控制端点."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from starlette.websockets import WebSocket, WebSocketDisconnect

from app.simulation.clock import SimulationClock
from app.simulation.state import simulation_state
from app.simulation.ws_manager import ConnectionManager

if TYPE_CHECKING:
    from app.simulation.scheduler import EventScheduler

logger = logging.getLogger(__name__)

_manager = ConnectionManager()
_scheduler: EventScheduler | None = None
_clock_task: asyncio.Task[None] | None = None


async def _clock_broadcast_loop() -> None:
    global _clock_task
    try:
        while True:
            await asyncio.sleep(1.0)
            clock = SimulationClock()
            await _manager.broadcast(
                {
                    "type": "clock_tick",
                    "time": clock.now().isoformat(),
                    "time_scale": clock.time_scale,
                }
            )
    except asyncio.CancelledError:
        pass


def _start_clock_broadcast() -> None:
    global _clock_task
    if _clock_task is None or _clock_task.done():
        _clock_task = asyncio.create_task(_clock_broadcast_loop())


async def simulation_ws(websocket: WebSocket) -> None:
    """处理 /ws/sim WebSocket 连接."""
    global _scheduler
    await _manager.connect(websocket)
    _start_clock_broadcast()

    ctx = simulation_state.get_context()
    await websocket.send_text(
        json.dumps(
            {"type": "context_snapshot", "context": ctx.model_dump()},
            ensure_ascii=False,
        )
    )

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "set_clock":
                clock = SimulationClock()
                clock.set_time(msg["time"])

            elif msg_type == "set_time_scale":
                clock = SimulationClock()
                clock.set_time_scale(msg["scale"])

            elif msg_type == "advance":
                clock = SimulationClock()
                clock.advance(msg.get("seconds", 1.0))

            elif msg_type == "update_context":
                simulation_state.update(msg["field_path"], msg["value"])

            elif msg_type == "set_preset":
                simulation_state.set_preset(msg["context"])

            elif msg_type == "start_scheduler":
                from app.agents.workflow import AgentWorkflow
                from app.api.main import DATA_DIR, get_memory_module
                from app.memory.components import EventStorage
                from app.memory.types import MemoryMode
                from app.simulation.scheduler import EventScheduler

                mm = get_memory_module()

                def make_workflow() -> AgentWorkflow:
                    return AgentWorkflow(
                        DATA_DIR, MemoryMode.MEMORY_BANK, memory_module=mm
                    )

                _scheduler = EventScheduler(
                    SimulationClock(),
                    simulation_state,
                    EventStorage(DATA_DIR),
                    workflow_factory=make_workflow,
                )
                _scheduler.start()

            elif msg_type == "stop_scheduler":
                if _scheduler is not None:
                    _scheduler.stop()
                    _scheduler = None

    except WebSocketDisconnect:
        pass
    finally:
        _manager.disconnect(websocket)
