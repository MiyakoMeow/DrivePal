# WebUI Simulation & Proactive Reminder Design

## Overview

Optimize the WebUI test page to support real-time simulation of driving context, simulated clock, and proactive reminder testing. Interfaces are separated into three layers: production, simulation control, and notification.

## 1. Interface Architecture

| Layer | Purpose | Protocol | Mount |
|-------|---------|----------|-------|
| Production | Business logic (query, feedback, history) | GraphQL | `/graphql` |
| Simulation Control | Set simulated time/context/scale, manage scheduler | WebSocket | `/ws/sim` |
| Notification | Push proactive reminders to frontend | WebSocket | `/ws/notify` |

All three endpoints are always mounted on the FastAPI app. The `/ws/sim` and `/ws/notify` routes are test-only in intent — they have no auth, no persistence, and their functionality (clock, scheduler) is irrelevant in production.

## 2. Backend: SimulationClock

`app/simulation/clock.py` — module-level singleton.

- `simulated_time: datetime | None` (None = follow system clock)
- `now() -> datetime`: return simulated time if set, else system UTC
- `set_time(dt: datetime | None)`: set or clear simulated time
- `advance(delta: timedelta)`: fast-forward
- `time_scale: float` (default 1.0); background asyncio task ticks wall-clock, advances simulated time by `elapsed * time_scale`
- `set_time_scale(scale: float)`: change speed
- `start()` / `stop()`: control background task

`now()` is called by workflow `_context_node` to replace `datetime.now(timezone.utc)`. When no simulated time is set, behavior is identical to before.

## 3. Backend: SimulationState

`app/simulation/state.py` — module-level singleton.

- Maintains a `DrivingContext` instance (from `app/schemas/context.py`)
- `update(field_path: str, value: Any)`: dot-notation field update, e.g. `"spatial.current_location.speed_kmh"` → 80. Validates against `DrivingContext` model on update.
- `get_context() -> DrivingContext`: return full context
- `reset()`: clear to defaults

Field path notation uses snake_case, dot-separated, matching the Pydantic model structure exactly.

## 4. WebSocket: Simulation Control (`/ws/sim`)

`app/simulation/ws_sim.py` — WebSocket endpoint.

**Client → Server:**

| type | payload | description |
|------|---------|-------------|
| `set_clock` | `{datetime: str \| null}` | ISO 8601. Null = reset to system |
| `set_time_scale` | `{scale: float}` | Speed multiplier |
| `advance` | `{seconds: float}` | Fast-forward by N simulated seconds |
| `update_context` | `{field: str, value: Any}` | Single field update (snake_case dot-path) |
| `set_preset` | `{context: dict}` | Batch replace entire context (snake_case keys) |
| `start_scheduler` | `{}` | Start event scheduler |
| `stop_scheduler` | `{}` | Stop event scheduler |

**Server → Client:**

| type | payload | description |
|------|---------|-------------|
| `clock_tick` | `{current_time: str, scale: float}` | ~1s wall-clock interval |
| `context_snapshot` | `{context: dict}` | Full context (snake_case). Sent on connect and on `set_preset` |

## 5. WebSocket: Notification (`/ws/notify`)

`app/simulation/ws_notify.py` — WebSocket endpoint.

**Server → Client only:**

| type | payload | description |
|------|---------|-------------|
| `proactive_reminder` | `{event_id: str, content: str, decision: dict, triggered_at: str}` | Scheduler-triggered reminder |

One-way channel. Frontend only listens.

## 6. Event Scheduler

`app/simulation/scheduler.py` — asyncio background task, started/stopped via `/ws/sim`.

- Wall-clock polling interval: 2s (fixed, not affected by time_scale)
- Each tick: get `SimulationClock.now()`, read events via `EventStorage.read_events()`
- Trigger condition: event has `remind_at` field and `simulated_time >= remind_at` and event not yet notified
- On trigger: run **mini-workflow** (`_context_node` + `_task_node` + `_strategy_node`) with the event content as user input, using `SimulationState.get_context()` as driving context → broadcast result to `/ws/notify`
- Deduplication: in-memory `set[str]` of notified event IDs, cleared on `stop_scheduler`

### Mini-Workflow for Scheduler

The scheduler does NOT call `_strategy_node` alone. It runs a minimal pipeline:

1. Reconstruct `AgentState` with event's content as user input, `SimulationState.get_context()` as driving context
2. Run `_context_node` → `_task_node` → `_strategy_node` (skip `_execution_node`, no new event is written)
3. Broadcast the strategy decision as `proactive_reminder`

### Scheduled Reminder Model

Add `remind_at` to `MemoryEvent`:

```python
# app/memory/schemas.py
class MemoryEvent(BaseModel):
    ...existing fields...
    remind_at: str | None = None  # ISO 8601, set by Task Agent
```

Task Agent prompt updated to parse time expressions and output `remind_at` when a future time is detected (e.g. "明天9点开会" → `remind_at: "2025-06-02T09:00:00"`).

### remind_at Persistence Pipeline

The `remind_at` value flows from Task Agent output to the persisted event:

1. `_task_node` outputs task JSON containing `remind_at` (if detected)
2. `_execution_node` reads `state["task"]["remind_at"]` and passes it to `write_interaction()`
3. `SimpleInteractionWriter.write_interaction()` gains optional `remind_at: str | None = None` parameter
4. `MemoryEvent` is created with `remind_at` set, persisted via `EventStorage.append_event()`

Files modified for this pipeline:
- `app/agents/workflow.py`: `_execution_node` extracts `remind_at` from task state
- `app/memory/components.py`: `SimpleInteractionWriter.write_interaction()` accepts `remind_at` param

### Event Access Path

Scheduler reads events directly from `events.toml` via `EventStorage` component (`app/memory/components.py`), which returns raw dicts preserving `remind_at`.

## 7. GraphQL Changes

**Breaking changes allowed.**

- Workflow `_context_node`: use `SimulationClock.now()` instead of `datetime.now(timezone.utc)`. No-op when clock is not simulated.
- No other GraphQL schema changes. `processQuery` retains its existing behavior (optional `context` parameter).
- No simulation-related mutations or queries added to GraphQL — all simulation control is via `/ws/sim`.

## 8. Frontend UI Changes

### Left Panel

**Simulated Clock Section (new, top of panel):**

- Dark background card showing current simulated time (large monospace font)
- Auto-updates via `clock_tick` messages from `/ws/sim`
- Row 1: `<input type="date">` + `<input type="time" step="1">` + "Set" button → sends `set_clock`
- Row 2: Time scale button group `1x / 2x / 5x / 10x / 60x` → sends `set_time_scale`
- Row 3: Quick actions — "Fast-forward 1h" / "Reset to system time" buttons
- "Start scheduler" / "Stop scheduler" toggle button

**Number Spinner Component:**

Replace all `<input type="number">` with a three-part widget:

```html
<div class="number-spinner">
  <button class="spin-btn" onclick="adjustField('spatial.current_location.speed_kmh', -5)">-</button>
  <input type="number" id="ctx-speedKmh" step="5" oninput="syncField('spatial.current_location.speed_kmh', this.value)">
  <button class="spin-btn" onclick="adjustField('spatial.current_location.speed_kmh', 5)">+</button>
</div>
```

Applies to: latitude (step=0.001), longitude (step=0.001), speed (step=5), ETA (step=1), delay (step=1), fatigue level (step=0.1, replaces range slider).

**Real-time Sync:**

- Each field `oninput` → `ws_sim.send({type: "update_context", field, value})`
- DOM is the frontend source-of-truth. Server sync only happens on connect (`context_snapshot`) and preset load.
- Preset load → `ws_sim.send({type: "set_preset", context: {...}})` → server responds with `context_snapshot`
- Select fields (emotion, workload, scenario, congestion) sync on `onchange`

**Presets:**

- Save/clear buttons remain, still use GraphQL mutations (no change)

### Right Panel

**Notification Banner (new, top of panel):**

- Hidden by default, slides in on `proactive_reminder` from `/ws/notify`
- Shows: reminder content, decision reason, triggered time
- Dismiss button
- Notification history list (accumulates during session)

**Query & Stages: unchanged**

### JavaScript Structure

- `SimulationWS` class: manages `/ws/sim` connection, auto-reconnect, message dispatch
- `NotifyWS` class: manages `/ws/notify` connection (listen-only), auto-reconnect
- `getContextInput()`: reads from DOM (source-of-truth), converts to GraphQL camelCase format for `processQuery`
- `sendQuery()`: unchanged, still uses GraphQL

### Styles

- `.number-spinner`: `display: flex; align-items: center;` — buttons fixed 32px width, input flex:1
- `.clock-panel`: `background: #1a1a2e; color: #0f0; font-family: monospace; font-size: 24px; padding: 16px;`
- `.notification-banner`: `background: #fff3cd; border-left: 4px solid #ffc107; padding: 12px 16px; animation: slideIn 0.3s ease;`
- `.scale-btn-group`: flex row of toggle buttons, active state highlighted

## 9. Data Flow

```
┌─ Production Layer ──────────────────────────────────┐
│  User sends query → GraphQL /graphql → Workflow      │
│  (workflow internally calls SimulationClock.now())   │
└──────────────────────────────────────────────────────┘

┌─ Simulation Control Layer ──────────────────────────┐
│  Field change → /ws/sim (update_context)            │
│  Set time    → /ws/sim (set_clock)                  │
│  Set scale   → /ws/sim (set_time_scale)             │
│  Start/stop  → /ws/sim (start/stop_scheduler)       │
│                                                      │
│  SimulationClock  SimulationState  Scheduler ──┐     │
└────────────────────────────────────────────────┼─────┘
                                                 │
┌─ Notification Layer ───────────────────────────┼─────┐
│  /ws/notify ← proactive_reminder broadcast ←───┘     │
│  Frontend banner displays reminder                    │
└──────────────────────────────────────────────────────┘
```

## 10. File Structure (new/modified)

```
app/simulation/              # NEW
├── __init__.py
├── clock.py                 # SimulationClock singleton
├── state.py                 # SimulationState singleton
├── scheduler.py             # Event scheduler (test-only)
├── ws_manager.py            # ConnectionManager
├── ws_sim.py                # /ws/sim WebSocket endpoint
└── ws_notify.py             # /ws/notify WebSocket endpoint

app/agents/workflow.py       # MODIFY: use SimulationClock.now()
app/memory/schemas.py        # MODIFY: add remind_at to MemoryEvent
app/agents/prompts.py        # MODIFY: Task prompt mentions remind_at
app/api/main.py              # MODIFY: mount WebSocket routes in lifespan

webui/index.html             # MODIFY: add clock panel, number spinners, notification area
webui/app.js                 # MODIFY: add SimulationWS, NotifyWS, real-time sync
webui/styles.css             # MODIFY: add spinner, clock, notification styles

tests/test_simulation/       # NEW
├── test_clock.py
├── test_state.py
├── test_scheduler.py
└── test_ws.py
```

## 11. Testing

- `test_clock.py`: set/reset time, time_scale advance, start/stop
- `test_state.py`: update single field, batch preset, reset, invalid path rejection
- `test_scheduler.py`: mock clock + EventStorage, trigger on remind_at, deduplication, mini-workflow execution
- `test_ws.py`: WebSocket connect, send message, receive broadcast
- Existing tests: SimulationClock defaults to system clock → no interference

## 12. Dependencies

- No new dependencies required (FastAPI WebSocket support via `websockets`, already a transitive dependency of `uvicorn[standard]`)
- No new frontend dependencies

## Out of Scope

- Real sensor/device integration
- Multi-user authentication
- Persistent simulation state across restarts
- Production-grade proactive reminder (scheduler is test-only)
