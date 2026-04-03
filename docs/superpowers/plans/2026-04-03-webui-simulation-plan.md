# WebUI Simulation & Proactive Reminder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add simulation clock, real-time driving context sync, proactive reminder scheduler, and UI enhancements (number spinners, clock panel, notification banner) to the WebUI test page.

**Architecture:** Three-layer interface separation — Production GraphQL (`/graphql`), Simulation Control WebSocket (`/ws/sim`), Notification WebSocket (`/ws/notify`). Backend singletons: `SimulationClock` (time), `SimulationState` (driving context). Test-only event scheduler scans `events.toml` for `remind_at` triggers.

**Tech Stack:** FastAPI WebSocket, asyncio, Pydantic, TOML storage, vanilla JS WebSocket API

---

### Task 1: SimulationClock Singleton

**Files:**
- Create: `app/simulation/__init__.py`
- Create: `app/simulation/clock.py`
- Test: `tests/test_simulation/test_clock.py`

- [ ] **Step 1: Create `app/simulation/__init__.py`**

Empty init file.

- [ ] **Step 2: Write failing tests for SimulationClock**

```python
# tests/test_simulation/test_clock.py
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.simulation.clock import SimulationClock


@pytest.fixture(autouse=True)
def reset_clock():
    SimulationClock._instance = None
    yield
    SimulationClock._instance = None


def test_now_returns_system_time_by_default():
    clock = SimulationClock()
    before = datetime.now(timezone.utc)
    result = clock.now()
    after = datetime.now(timezone.utc)
    assert before <= result <= after


def test_set_time_and_now():
    clock = SimulationClock()
    dt = datetime(2025, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    clock.set_time(dt)
    assert clock.now() == dt


def test_reset_time():
    clock = SimulationClock()
    clock.set_time(datetime(2025, 6, 1, 9, 0, 0, tzinfo=timezone.utc))
    clock.set_time(None)
    before = datetime.now(timezone.utc)
    result = clock.now()
    after = datetime.now(timezone.utc)
    assert before <= result <= after


def test_advance():
    clock = SimulationClock()
    dt = datetime(2025, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    clock.set_time(dt)
    clock.advance(timedelta(hours=1))
    assert clock.now() == datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)


def test_time_scale():
    clock = SimulationClock()
    assert clock.time_scale == 1.0
    clock.set_time_scale(2.0)
    assert clock.time_scale == 2.0


@pytest.mark.asyncio
async def test_start_stop():
    clock = SimulationClock()
    dt = datetime(2025, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    clock.set_time(dt)
    clock.set_time_scale(60.0)
    clock.start()
    await asyncio.sleep(0.1)
    clock.stop()
    assert clock.now() > dt


def test_on_tick_callback():
    clock = SimulationClock()
    dt = datetime(2025, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    clock.set_time(dt)
    clock.set_time_scale(60.0)
    ticks = []
    clock.on_tick = lambda: ticks.append(clock.now())
    clock.start()
    await asyncio.sleep(0.1)
    clock.stop()
    assert len(ticks) > 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_simulation/test_clock.py -v`
Expected: FAIL (module not found)

- [ ] **Step 4: Implement SimulationClock**

```python
# app/simulation/clock.py
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, ClassVar

logger = logging.getLogger(__name__)


class SimulationClock:
    _instance: ClassVar[SimulationClock | None] = None

    def __new__(cls) -> SimulationClock:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._simulated_time = None
            cls._instance._time_scale = 1.0
            cls._instance._task: asyncio.Task | None = None
            cls._instance._last_tick: datetime | None = None
            cls._instance._on_tick: Callable | None = None
        return cls._instance

    @property
    def time_scale(self) -> float:
        return self._time_scale

    @property
    def on_tick(self) -> Callable | None:
        return self._on_tick

    @on_tick.setter
    def on_tick(self, cb: Callable | None) -> None:
        self._on_tick = cb

    def now(self) -> datetime:
        if self._simulated_time is not None:
            return self._simulated_time
        return datetime.now(timezone.utc)

    def set_time(self, dt: datetime | None) -> None:
        self._simulated_time = dt
        self._last_tick = dt

    def advance(self, delta: timedelta) -> None:
        if self._simulated_time is not None:
            self._simulated_time += delta
            self._last_tick = self._simulated_time

    def set_time_scale(self, scale: float) -> None:
        self._time_scale = scale

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._last_tick = datetime.now(timezone.utc)
        self._task = asyncio.create_task(self._tick_loop())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            now_wall = datetime.now(timezone.utc)
            if self._last_tick is not None and self._simulated_time is not None:
                elapsed = (now_wall - self._last_tick).total_seconds()
                self._simulated_time += timedelta(seconds=elapsed * self._time_scale)
            self._last_tick = now_wall
            if self._on_tick:
                try:
                    self._on_tick()
                except Exception:
                    pass
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_simulation/test_clock.py -v`
Expected: PASS

- [ ] **Step 6: Run lint and typecheck**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 7: Commit**

```bash
git add app/simulation/ tests/test_simulation/
git commit -m "feat(simulation): add SimulationClock singleton with time_scale support"
```

---

### Task 2: SimulationState Singleton

**Files:**
- Create: `app/simulation/state.py`
- Test: `tests/test_simulation/test_state.py`

- [ ] **Step 1: Write failing tests for SimulationState**

```python
# tests/test_simulation/test_state.py
import pytest

from app.simulation.state import SimulationState


@pytest.fixture(autouse=True)
def reset_state():
    SimulationState._instance = None
    yield
    SimulationState._instance = None


def test_default_context():
    state = SimulationState()
    ctx = state.get_context()
    assert ctx.scenario == "parked"
    assert ctx.driver.emotion == "neutral"
    assert ctx.spatial.current_location.speed_kmh == 0.0


def test_update_single_field():
    state = SimulationState()
    state.update("spatial.current_location.speed_kmh", 80)
    assert state.get_context().spatial.current_location.speed_kmh == 80.0


def test_update_nested_field():
    state = SimulationState()
    state.update("driver.fatigue_level", 0.7)
    assert state.get_context().driver.fatigue_level == 0.7


def test_update_scenario():
    state = SimulationState()
    state.update("scenario", "highway")
    assert state.get_context().scenario == "highway"


def test_update_invalid_field():
    state = SimulationState()
    with pytest.raises(AttributeError):
        state.update("nonexistent.field", "value")


def test_reset():
    state = SimulationState()
    state.update("spatial.current_location.speed_kmh", 80)
    state.reset()
    assert state.get_context().spatial.current_location.speed_kmh == 0.0


def test_set_preset():
    state = SimulationState()
    state.set_preset({
        "scenario": "highway",
        "driver": {"fatigue_level": 0.5},
    })
    ctx = state.get_context()
    assert ctx.scenario == "highway"
    assert ctx.driver.fatigue_level == 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_simulation/test_state.py -v`
Expected: FAIL

- [ ] **Step 3: Implement SimulationState**

```python
# app/simulation/state.py
from __future__ import annotations

from typing import Any, ClassVar

from app.schemas.context import DrivingContext


class SimulationState:
    _instance: ClassVar[SimulationState | None] = None

    def __new__(cls) -> SimulationState:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._context = DrivingContext()
        return cls._instance

    def get_context(self) -> DrivingContext:
        return self._context

    def update(self, field_path: str, value: Any) -> None:
        parts = field_path.split(".")
        obj: Any = self._context
        for part in parts[:-1]:
            obj = getattr(obj, part)
        setattr(obj, parts[-1], value)

    def set_preset(self, context_dict: dict) -> None:
        safe = {k: v for k, v in context_dict.items() if k in DrivingContext.model_fields}
        self._context = DrivingContext(**safe)

    def reset(self) -> None:
        self._context = DrivingContext()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_simulation/test_state.py -v`
Expected: PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 6: Commit**

```bash
git add app/simulation/state.py tests/test_simulation/test_state.py
git commit -m "feat(simulation): add SimulationState singleton with dot-path field updates"
```

---

### Task 3: WebSocket ConnectionManager + Simulation Control Endpoint

**Files:**
- Create: `app/simulation/ws_manager.py`
- Create: `app/simulation/ws_sim.py`
- Test: `tests/test_simulation/test_ws.py`

- [ ] **Step 1: Write failing tests for ConnectionManager**

```python
# tests/test_simulation/test_ws.py
import json
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.simulation.ws_manager import ConnectionManager


def test_connection_manager_add_remove():
    manager = ConnectionManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    manager.connect(ws1)
    manager.connect(ws2)
    assert len(manager.active_connections) == 2
    manager.disconnect(ws1)
    assert len(manager.active_connections) == 1


@pytest.mark.asyncio
async def test_connection_manager_broadcast():
    manager = ConnectionManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    manager.connect(ws1)
    manager.connect(ws2)
    await manager.broadcast({"type": "test", "value": 42})
    ws1.send_text.assert_called_once_with('{"type": "test", "value": 42}')
    ws2.send_text.assert_called_once_with('{"type": "test", "value": 42}')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_simulation/test_ws.py::test_connection_manager_add_remove -v`
Expected: FAIL

- [ ] **Step 3: Implement ConnectionManager**

```python
# app/simulation/ws_manager.py
from __future__ import annotations

import json
import logging
from typing import Any

from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    def connect(self, websocket: WebSocket) -> None:
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False)
        dead: list[WebSocket] = []
        for ws in self.active_connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_simulation/test_ws.py -v`
Expected: PASS

- [ ] **Step 5: Implement `/ws/sim` endpoint with clock_tick broadcast**

```python
# app/simulation/ws_sim.py
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from app.simulation.clock import SimulationClock
from app.simulation.state import SimulationState
from app.simulation.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

_manager = ConnectionManager()
_clock_broadcast_task: asyncio.Task | None = None


async def _clock_broadcast_loop() -> None:
    clock = SimulationClock()
    while True:
        await asyncio.sleep(1.0)
        try:
            await _manager.broadcast({
                "type": "clock_tick",
                "current_time": clock.now().isoformat(),
                "scale": clock.time_scale,
            })
        except Exception:
            pass


async def start_clock_broadcast() -> None:
    global _clock_broadcast_task
    if _clock_broadcast_task is None or _clock_broadcast_task.done():
        _clock_broadcast_task = asyncio.create_task(_clock_broadcast_loop())


async def simulation_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    _manager.connect(websocket)
    clock = SimulationClock()
    state = SimulationState()
    await start_clock_broadcast()
    try:
        await websocket.send_text(json.dumps({
            "type": "context_snapshot",
            "context": state.get_context().model_dump(),
        }, ensure_ascii=False))
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await _handle_message(msg, websocket, clock, state)
    except WebSocketDisconnect:
        pass
    finally:
        _manager.disconnect(websocket)


async def _handle_message(
    msg: dict[str, Any],
    ws: WebSocket,
    clock: SimulationClock,
    state: SimulationState,
) -> None:
    t = msg.get("type")
    if t == "set_clock":
        val = msg.get("datetime")
        if val:
            from datetime import datetime, timezone
            clock.set_time(datetime.fromisoformat(val).replace(tzinfo=timezone.utc))
        else:
            clock.set_time(None)
    elif t == "set_time_scale":
        clock.set_time_scale(msg.get("scale", 1.0))
    elif t == "advance":
        from datetime import timedelta
        clock.advance(timedelta(seconds=msg.get("seconds", 0)))
    elif t == "update_context":
        state.update(msg["field"], msg["value"])
    elif t == "set_preset":
        state.set_preset(msg["context"])
        await _manager.broadcast({
            "type": "context_snapshot",
            "context": state.get_context().model_dump(),
        })
```

- [ ] **Step 6: Run lint and typecheck**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 7: Commit**

```bash
git add app/simulation/ws_manager.py app/simulation/ws_sim.py tests/test_simulation/test_ws.py
git commit -m "feat(simulation): add ConnectionManager and /ws/sim WebSocket endpoint"
```

---

### Task 4: Mount WebSocket Routes in FastAPI App

**Files:**
- Modify: `app/api/main.py`

- [ ] **Step 1: Add WebSocket route mounts to `app/api/main.py`**

In `_lifespan`, start/stop the clock tick task. In route mounting, add `/ws/sim` and `/ws/notify`.

Add after the `_mount_graphql()` call (around line 88):

```python
from app.simulation.ws_sim import simulation_ws

app.websocket("/ws/sim")(simulation_ws)
```

Also add `_notify_ws` placeholder (Task 5):

```python
from app.simulation.ws_notify import notify_ws

app.websocket("/ws/notify")(notify_ws)
```

In `_lifespan`, start the clock on startup, stop on shutdown:

```python
@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_storage(DATA_DIR)
    logger.info("Data directory initialized: %s", DATA_DIR)
    if not Path.exists(WEBUI_DIR):
        logger.warning("WebUI directory not found: %s", WEBUI_DIR)
    from app.simulation.clock import SimulationClock
    SimulationClock().start()
    yield
    SimulationClock().stop()
```

- [ ] **Step 2: Run existing tests to verify no breakage**

Run: `uv run pytest tests/ -v --timeout=30`
Expected: PASS (all existing tests unaffected)

- [ ] **Step 3: Run lint and typecheck**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 4: Commit**

```bash
git add app/api/main.py
git commit -m "feat(simulation): mount WebSocket routes and start clock in lifespan"
```

---

### Task 5: Notification WebSocket + Event Scheduler

**Files:**
- Create: `app/simulation/ws_notify.py`
- Create: `app/simulation/scheduler.py`
- Test: `tests/test_simulation/test_scheduler.py`

- [ ] **Step 1: Create `/ws/notify` endpoint (listen-only)**

```python
# app/simulation/ws_notify.py
from __future__ import annotations

import json
import logging

from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

_active_ws: list[WebSocket] = []


async def notify_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    _active_ws.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _active_ws.remove(websocket)


async def broadcast_reminder(reminder: dict) -> None:
    payload = json.dumps({"type": "proactive_reminder", **reminder}, ensure_ascii=False)
    dead: list[WebSocket] = []
    for ws in _active_ws:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _active_ws.remove(ws)
```

- [ ] **Step 2: Write failing tests for EventScheduler**

```python
# tests/test_simulation/test_scheduler.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.simulation.scheduler import EventScheduler


@pytest.fixture
def mock_components():
    with patch("app.simulation.scheduler.EventStorage") as MockStorage:
        storage = MockStorage.return_value
        storage.read_events = AsyncMock(return_value=[
            {"id": "evt1", "content": "明天开会", "remind_at": "2025-06-01T09:00:00+00:00"},
            {"id": "evt2", "content": "买东西", "remind_at": None},
        ])
        yield storage


@pytest.fixture
def mock_clock():
    clock = MagicMock()
    clock.now.return_value = datetime(2025, 6, 1, 8, 55, 0, tzinfo=timezone.utc)
    return clock


@pytest.fixture
def mock_state():
    state = MagicMock()
    from app.schemas.context import DrivingContext
    state.get_context.return_value = DrivingContext()
    return state


@pytest.mark.asyncio
async def test_scheduler_triggers_on_remind_at(mock_components, mock_clock, mock_state):
    scheduler = EventScheduler(mock_clock, mock_state, mock_components)
    notified = []
    with patch("app.simulation.scheduler.broadcast_reminder", new_callable=AsyncMock, side_effect=lambda r: notified.append(r)):
        await scheduler.tick()
    assert len(notified) == 0

    mock_clock.now.return_value = datetime(2025, 6, 1, 9, 0, 1, tzinfo=timezone.utc)
    await scheduler.tick()
    assert len(notified) == 1
    assert notified[0]["event_id"] == "evt1"


@pytest.mark.asyncio
async def test_scheduler_dedup(mock_components, mock_clock, mock_state):
    mock_clock.now.return_value = datetime(2025, 6, 1, 9, 0, 1, tzinfo=timezone.utc)
    scheduler = EventScheduler(mock_clock, mock_state, mock_components)
    notified = []
    with patch("app.simulation.scheduler.broadcast_reminder", new_callable=AsyncMock, side_effect=lambda r: notified.append(r)):
        await scheduler.tick()
        await scheduler.tick()
    assert len(notified) == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_simulation/test_scheduler.py -v`
Expected: FAIL

- [ ] **Step 4: Implement EventScheduler with mini-workflow**

The scheduler needs access to `AgentWorkflow` to run the mini-pipeline (context → task → strategy). It receives the workflow factory, not a raw instance, to avoid lifecycle issues.

```python
# app/simulation/scheduler.py
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Awaitable

from app.memory.components import EventStorage

if TYPE_CHECKING:
    from app.simulation.clock import SimulationClock
    from app.simulation.state import SimulationState

logger = logging.getLogger(__name__)


class EventScheduler:
    def __init__(
        self,
        clock: SimulationClock,
        state: SimulationState,
        event_storage: EventStorage,
        workflow_factory: Callable[[], Any] | None = None,
        poll_interval: float = 2.0,
    ) -> None:
        self._clock = clock
        self._state = state
        self._storage = event_storage
        self._workflow_factory = workflow_factory
        self._poll_interval = poll_interval
        self._notified: set[str] = set()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._notified.clear()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval)
            try:
                await self.tick()
            except Exception as e:
                logger.warning("Scheduler tick failed: %s", e)

    async def tick(self) -> None:
        from app.simulation.ws_notify import broadcast_reminder

        now = self._clock.now()
        events = await self._storage.read_events()
        for event in events:
            eid = event.get("id", "")
            if eid in self._notified:
                continue
            remind_at_str = event.get("remind_at")
            if not remind_at_str:
                continue
            try:
                remind_at = datetime.fromisoformat(remind_at_str)
            except (ValueError, TypeError):
                continue
            if now >= remind_at:
                self._notified.add(eid)
                decision = {}
                if self._workflow_factory:
                    try:
                        decision = await self._run_mini_workflow(event)
                    except Exception as e:
                        logger.warning("Mini-workflow failed for %s: %s", eid, e)
                await broadcast_reminder({
                    "event_id": eid,
                    "content": event.get("content", ""),
                    "decision": decision,
                    "triggered_at": now.isoformat(),
                })

    async def _run_mini_workflow(self, event: dict) -> dict:
        from app.agents.workflow import AgentWorkflow
        from app.agents.state import WorkflowStages

        workflow: AgentWorkflow = self._workflow_factory()
        stages = WorkflowStages()
        context_dict = self._state.get_context().model_dump()
        from app.agents.state import AgentState
        state: AgentState = {
            "messages": [{"role": "user", "content": event.get("content", "")}],
            "context": {},
            "task": None,
            "decision": None,
            "result": None,
            "event_id": None,
            "driving_context": context_dict,
            "stages": stages,
        }
        for node_fn in [workflow._context_node, workflow._task_node, workflow._strategy_node]:
            updates = await node_fn(state)
            state.update(updates)
        return stages.decision
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_simulation/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 6: Run lint and typecheck**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 7: Commit**

```bash
git add app/simulation/ws_notify.py app/simulation/scheduler.py tests/test_simulation/test_scheduler.py
git commit -m "feat(simulation): add /ws/notify endpoint and EventScheduler"
```

---

### Task 6: Wire Scheduler into `/ws/sim` + Integrate SimulationClock into Workflow

**Files:**
- Modify: `app/simulation/ws_sim.py`
- Modify: `app/agents/workflow.py`

- [ ] **Step 1: Add scheduler start/stop to `_handle_message` in `ws_sim.py`**

Add to the `elif` chain in `_handle_message`:

```python
    elif t == "start_scheduler":
        from app.simulation.scheduler import EventScheduler
        from app.memory.components import EventStorage
        from app.api.main import DATA_DIR
        storage = EventStorage(DATA_DIR)
        scheduler = EventScheduler(clock, state, storage)
        scheduler.start()
    elif t == "stop_scheduler":
        from app.simulation.scheduler import EventScheduler
        EventScheduler._scheduler_instance.stop() if hasattr(EventScheduler, '_scheduler_instance') else None
```

Better approach — use a module-level scheduler reference:

```python
_scheduler: EventScheduler | None = None
```

And in `start_scheduler`:

```python
    elif t == "start_scheduler":
        global _scheduler
        from app.simulation.scheduler import EventScheduler
        from app.memory.components import EventStorage
        from app.api.main import DATA_DIR, get_memory_module
        from app.agents.workflow import AgentWorkflow
        from app.memory.types import MemoryMode
        mm = get_memory_module()
        def make_workflow():
            return AgentWorkflow(DATA_DIR, MemoryMode.MEMORY_BANK, memory_module=mm)
        _scheduler = EventScheduler(clock, state, EventStorage(DATA_DIR), workflow_factory=make_workflow)
        _scheduler.start()
    elif t == "stop_scheduler":
        if _scheduler is not None:
            _scheduler.stop()
            _scheduler = None
```

- [ ] **Step 2: Integrate SimulationClock into workflow `_context_node`**

In `app/agents/workflow.py`, replace line 99:

```python
current_datetime = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
```

With:

```python
from app.simulation.clock import SimulationClock
current_datetime = SimulationClock().now().strftime("%Y-%m-%d %H:%M:%S")
```

- [ ] **Step 3: Run existing tests**

Run: `uv run pytest tests/test_graphql.py tests/test_chat.py -v --timeout=30`
Expected: PASS (SimulationClock defaults to system time, no-op for existing tests)

- [ ] **Step 4: Run lint and typecheck**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 5: Commit**

```bash
git add app/simulation/ws_sim.py app/agents/workflow.py
git commit -m "feat(simulation): wire scheduler into /ws/sim and integrate clock into workflow"
```

---

### Task 7: Add `remind_at` to MemoryEvent + Persistence Pipeline

**Files:**
- Modify: `app/memory/schemas.py`
- Modify: `app/agents/prompts.py`
- Modify: `app/agents/workflow.py` (_execution_node)
- Modify: `app/memory/components.py` (SimpleInteractionWriter)
- Modify: `app/memory/interfaces.py` (MemoryStore protocol)
- Modify: `app/memory/memory.py` (MemoryModule facade)

- [ ] **Step 1: Add `remind_at` field to MemoryEvent**

In `app/memory/schemas.py:10`, add field:

```python
    remind_at: str | None = None
```

- [ ] **Step 2: Update MemoryStore protocol `write_interaction` signature**

In `app/memory/interfaces.py:34`, change:

```python
    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder", *, remind_at: str | None = None
    ) -> str:
```

- [ ] **Step 3: Update SimpleInteractionWriter**

In `app/memory/components.py:147`, change `write_interaction`:

```python
    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder", *, remind_at: str | None = None
    ) -> str:
        event = MemoryEvent(
            content=query,
            type=event_type,
            description=response,
            remind_at=remind_at,
        )
        return await self._storage.append_event(event)
```

- [ ] **Step 4: Update MemoryModule facade**

In `app/memory/memory.py:101`, update `write_interaction`:

```python
    async def write_interaction(
        self,
        query: str,
        response: str,
        event_type: str = "reminder",
        *,
        mode: MemoryMode | None = None,
        remind_at: str | None = None,
    ) -> str:
        store = await self._get_store(self._resolve_mode(mode))
        if not getattr(store, "supports_interaction", False):
            raise NotImplementedError(
                f"Store '{store.store_name}' does not support write_interaction"
            )
        return await store.write_interaction(query, response, event_type, remind_at=remind_at)
```

- [ ] **Step 5: Update Task Agent prompt to mention `remind_at`**

In `app/agents/prompts.py`, update `TASK_SYSTEM_PROMPT`:

```python
TASK_SYSTEM_PROMPT = """你是任务理解Agent，负责事件抽取和任务归因。

根据用户输入，提取：
- 事件列表（时间、地点、类型、约束）
- 任务归因（meeting/travel/shopping/contact/other）
- 置信度
- remind_at（ISO 8601格式）：如果事件包含未来时间（如"明天9点"、"下周一"），解析为绝对时间

输出JSON格式的任务对象. """
```

- [ ] **Step 6: Update `_execution_node` to propagate `remind_at`**

In `app/agents/workflow.py`, in `_execution_node` around line 219, change:

```python
        remind_at = None
        task_data = state.get("task") or {}
        if isinstance(task_data, dict):
            remind_at = task_data.get("remind_at")

        event_id = await self.memory_module.write_interaction(
            user_input, content, mode=self._memory_mode, remind_at=remind_at
        )
```

- [ ] **Step 7: Update MemoryBank and MemoChat store `write_interaction` to accept `remind_at`**

**MemoryBankStore** (`app/memory/stores/memory_bank/store.py:79`): delegates to `MemoryBankEngine.write_interaction()`. Add `*, remind_at: str | None = None` and pass to engine.

**MemoryBankEngine** (`app/memory/stores/memory_bank/engine.py:239`): add `*, remind_at: str | None = None` parameter. In the event creation block (~line 263), add `remind_at=remind_at`:

```python
# engine.py line ~263
event = {
    "id": event_id,
    "content": query,
    "type": event_type,
    "interaction_ids": [interaction_id],
    "created_at": now_iso,
    "updated_at": now_iso,
    "memory_strength": 1,
    "last_recall_date": today,
    "date_group": today,
    "remind_at": remind_at,
}
```

**MemoChatStore** (`app/memory/stores/memochat/store.py:111`): MemoChat's `write_interaction` does NOT write events to `events.toml` — it writes interaction records and recent dialogs only. The scheduler reads from `events.toml`, so MemoChat events won't be scheduled. Add `*, remind_at: str | None = None` parameter for interface compliance but no-op (log warning if non-None).

- [ ] **Step 8: Run all tests**

Run: `uv run pytest tests/ -v --timeout=30`
Expected: PASS

- [ ] **Step 9: Run lint and typecheck**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 10: Commit**

```bash
git add app/memory/ app/agents/ 
git commit -m "feat(memory): add remind_at field and persistence pipeline"
```

---

### Task 8: Frontend — Clock Panel + Number Spinners + Real-time Sync

**Files:**
- Modify: `webui/index.html`
- Modify: `webui/app.js`
- Modify: `webui/styles.css`

- [ ] **Step 1: Add clock panel HTML to left panel (top, before scene presets)**

In `webui/index.html`, add after the `<div class="main">` opening and before the existing panel-left content:

```html
            <div class="clock-panel">
                <div class="clock-display" id="clockDisplay">--:--:--</div>
                <div class="clock-date" id="clockDate">----/--/--</div>
                <div class="clock-controls">
                    <input type="date" id="simDate">
                    <input type="time" id="simTime" step="1">
                    <button class="btn btn-primary btn-xs" onclick="setSimClock()">设置</button>
                </div>
                <div class="scale-btn-group">
                    <button class="scale-btn active" onclick="setScale(1, this)">1x</button>
                    <button class="scale-btn" onclick="setScale(2, this)">2x</button>
                    <button class="scale-btn" onclick="setScale(5, this)">5x</button>
                    <button class="scale-btn" onclick="setScale(10, this)">10x</button>
                    <button class="scale-btn" onclick="setScale(60, this)">60x</button>
                </div>
                <div class="clock-actions">
                    <button class="btn btn-secondary btn-xs" onclick="advanceClock(3600)">快进 1h</button>
                    <button class="btn btn-secondary btn-xs" onclick="resetClock()">重置</button>
                    <button class="btn btn-success btn-xs" id="schedulerBtn" onclick="toggleScheduler()">启动调度</button>
                </div>
            </div>
```

- [ ] **Step 2: Replace all `<input type="number">` with number spinner widgets**

For each number field (lat, lng, speed, ETA, delay, fatigue), replace with:

```html
<div class="number-spinner">
    <button class="spin-btn" onclick="adjustField('spatial.current_location.speed_kmh', -5)">−</button>
    <input type="number" id="ctx-speedKmh" step="5" value="0" oninput="syncField('spatial.current_location.speed_kmh', this.value)">
    <button class="spin-btn" onclick="adjustField('spatial.current_location.speed_kmh', 5)">+</button>
</div>
```

Map each field:
- 纬度: `spatial.current_location.latitude`, step=0.001
- 经度: `spatial.current_location.longitude`, step=0.001
- 车速: `spatial.current_location.speed_kmh`, step=5
- ETA: `spatial.eta_minutes`, step=1
- 延误: `traffic.estimated_delay_minutes`, step=1
- 疲劳程度: `driver.fatigue_level`, step=0.1 (replaces range slider)

- [ ] **Step 3: Add notification banner to right panel (top)**

Before the query-bar card in panel-right:

```html
            <div class="notification-area" id="notificationArea" style="display:none;">
                <div class="notification-banner" id="notificationBanner">
                    <div class="notification-content" id="notificationContent"></div>
                    <button class="notification-dismiss" onclick="dismissNotification()">✕</button>
                </div>
                <div class="notification-history" id="notificationHistory"></div>
            </div>
```

- [ ] **Step 4: Add CSS styles**

```css
.clock-panel {
    background: #1a1a2e;
    color: #0f0;
    padding: 16px;
    border-radius: 8px;
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
}
.clock-display { font-size: 28px; text-align: center; letter-spacing: 2px; }
.clock-date { font-size: 14px; text-align: center; margin-bottom: 12px; opacity: 0.8; }
.clock-controls { display: flex; gap: 6px; margin-bottom: 10px; }
.clock-controls input { background: #16213e; border: 1px solid #333; color: #0f0; padding: 4px 6px; border-radius: 4px; font-size: 12px; flex: 1; }
.clock-controls input::-webkit-calendar-picker-indicator { filter: invert(1); }
.btn-xs { padding: 4px 10px; font-size: 11px; }
.scale-btn-group { display: flex; gap: 4px; margin-bottom: 10px; }
.scale-btn {
    flex: 1; padding: 4px 0; font-size: 11px; border: 1px solid #333; background: transparent;
    color: #888; border-radius: 4px; cursor: pointer; transition: all .2s;
}
.scale-btn.active { background: #0f0; color: #1a1a2e; border-color: #0f0; font-weight: 600; }
.clock-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.btn-danger { background: #dc3545; color: #fff; }
.number-spinner { display: flex; align-items: center; gap: 0; }
.number-spinner input[type="number"] { flex: 1; text-align: center; -moz-appearance: textfield; }
.number-spinner input[type="number"]::-webkit-inner-spin-button,
.number-spinner input[type="number"]::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
.spin-btn {
    width: 32px; height: 34px; border: 1px solid #ddd; background: #f5f5f5;
    font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center;
    transition: background .2s; user-select: none;
}
.spin-btn:hover { background: #e0e0e0; }
.spin-btn:first-child { border-radius: 5px 0 0 5px; }
.spin-btn:last-child { border-radius: 0 5px 5px 0; }
.number-spinner input { border-radius: 0 !important; }
.notification-area { position: sticky; top: 0; z-index: 10; }
.notification-banner {
    background: #fff3cd; border-left: 4px solid #ffc107; padding: 12px 16px;
    border-radius: 6px; display: flex; align-items: center; gap: 12px;
    animation: slideIn 0.3s ease; box-shadow: 0 2px 8px rgba(0,0,0,.1);
}
@keyframes slideIn { from { transform: translateY(-20px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
.notification-content { flex: 1; font-size: 13px; color: #856404; }
.notification-dismiss {
    background: none; border: none; font-size: 16px; cursor: pointer; color: #856404; padding: 4px;
}
.notification-history { margin-top: 8px; }
.notification-item {
    background: #fff9e6; border-left: 3px solid #ffc107; padding: 8px 12px;
    border-radius: 4px; margin-bottom: 4px; font-size: 12px; color: #666;
}
```

- [ ] **Step 5: Add JavaScript — SimulationWS, NotifyWS, clock controls, field sync**

Add to `webui/app.js`:

```javascript
class SimulationWS {
    constructor() {
        this.ws = null;
        this.reconnectDelay = 1000;
    }
    connect() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${proto}//${location.host}/ws/sim`);
        this.ws.onmessage = (e) => this._onMessage(JSON.parse(e.data));
        this.ws.onclose = () => { setTimeout(() => this.connect(), this.reconnectDelay); };
        this.ws.onerror = () => this.ws.close();
    }
    send(msg) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
    }
    _onMessage(msg) {
        if (msg.type === 'clock_tick') {
            const dt = new Date(msg.current_time);
            document.getElementById('clockDisplay').textContent = dt.toLocaleTimeString('zh-CN', {hour12: false});
            document.getElementById('clockDate').textContent = dt.toLocaleDateString('zh-CN');
        }
    }
}

class NotifyWS {
    constructor() {
        this.ws = null;
    }
    connect() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${proto}//${location.host}/ws/notify`);
        this.ws.onmessage = (e) => {
            const msg = JSON.parse(e.data);
            if (msg.type === 'proactive_reminder') showNotification(msg);
        };
        this.ws.onclose = () => { setTimeout(() => this.connect(), 2000); };
        this.ws.onerror = () => this.ws.close();
    }
}

const simWS = new SimulationWS();
const notifyWS = new NotifyWS();

function setSimClock() {
    const date = document.getElementById('simDate').value;
    const time = document.getElementById('simTime').value;
    if (!date && !time) return;
    const dt = date && time ? `${date}T${time}` : null;
    simWS.send({ type: 'set_clock', datetime: dt });
}

function setScale(scale, btn) {
    simWS.send({ type: 'set_time_scale', scale });
    document.querySelectorAll('.scale-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

function adjustClock(seconds) { simWS.send({ type: 'advance', seconds }); }
function resetClock() { simWS.send({ type: 'set_clock', datetime: null }); }
let schedulerRunning = false;
function toggleScheduler() {
    schedulerRunning = !schedulerRunning;
    simWS.send({ type: schedulerRunning ? 'start_scheduler' : 'stop_scheduler' });
    const btn = document.getElementById('schedulerBtn');
    btn.textContent = schedulerRunning ? '停止调度' : '启动调度';
    btn.classList.toggle('btn-success', !schedulerRunning);
    btn.classList.toggle('btn-danger', schedulerRunning);
}

function adjustField(field, delta) {
    const map = {
        'spatial.current_location.latitude': 'ctx-lat',
        'spatial.current_location.longitude': 'ctx-lng',
        'spatial.current_location.speed_kmh': 'ctx-speedKmh',
        'spatial.eta_minutes': 'ctx-etaMinutes',
        'traffic.estimated_delay_minutes': 'ctx-delayMinutes',
        'driver.fatigue_level': 'ctx-fatigueLevel',
    };
    const input = document.getElementById(map[field]);
    if (!input) return;
    const step = parseFloat(input.step) || 1;
    input.value = (parseFloat(input.value) || 0) + delta * step;
    syncField(field, input.value);
}

function syncField(field, value) {
    simWS.send({ type: 'update_context', field, value: parseFloat(value) || value });
}

function showNotification(msg) {
    const area = document.getElementById('notificationArea');
    area.style.display = 'block';
    document.getElementById('notificationContent').innerHTML =
        `<strong>主动提醒</strong>: ${escapeHtml(msg.content)} <div style="font-size:11px;color:#999;margin-top:4px">${escapeHtml(msg.triggered_at || '')}</div>`;
    const history = document.getElementById('notificationHistory');
    const item = document.createElement('div');
    item.className = 'notification-item';
    item.textContent = `${msg.content} (${msg.triggered_at || ''})`;
    history.prepend(item);
}

function dismissNotification() {
    document.getElementById('notificationArea').style.display = 'none';
}

simWS.connect();
notifyWS.connect();
```

- [ ] **Step 6: Manually verify in browser**

Run: `uv run python main.py` and open http://localhost:8000
- Clock display shows current time
- Number spinners have -/+ buttons
- WebSocket connections establish (check browser console)

- [ ] **Step 7: Commit**

```bash
git add webui/
git commit -m "feat(webui): add clock panel, number spinners, notification banner, WebSocket clients"
```

---

### Task 9: Update `fillForm` and `clearForm` for New UI

**Files:**
- Modify: `webui/app.js`

- [ ] **Step 1: Update `fillForm` to work with new spinner inputs**

The existing `fillForm` reads DOM by ID. Since the input IDs haven't changed (only wrapped in spinners), existing code should work. Verify that:

- `document.getElementById('ctx-fatigueLevel')` now returns the number input (not the range slider). Update `fatigueVal` display logic:

```javascript
function updateFatigueDisplay(val) {
    document.getElementById('fatigueVal').textContent = (parseFloat(val) || 0).toFixed(1);
}
```

- [ ] **Step 2: Update `clearForm` to reset fatigue display**

Ensure `clearForm` calls `updateFatigueDisplay(0)`.

- [ ] **Step 3: Manually test preset load/clear**

- [ ] **Step 4: Commit**

```bash
git add webui/app.js
git commit -m "fix(webui): update fillForm/clearForm for number spinner UI"
```

---

### Task 10: Final Integration Test + CI

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v --timeout=30`
Expected: ALL PASS

- [ ] **Step 2: Run lint and typecheck**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 3: Run CI test commands**

Run: `uv run ruff check` && `uv run ty check` && `uv run pytest tests/ -v --timeout=30`

- [ ] **Step 4: Commit any fixes if needed**

```bash
git add -A && git commit -m "fix: resolve lint/typecheck issues from simulation feature"
```
