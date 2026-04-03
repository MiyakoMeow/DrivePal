# WebUI Simulation & Proactive Reminder Design

## Overview

Optimize the WebUI test page to support real-time simulation of driving context, simulated clock, and proactive reminder testing via WebSocket.

## 1. Backend: SimulationClock

- `app/simulation/clock.py` — singleton
- `simulated_time: datetime | None` (None = follow system clock)
- `now() -> datetime`: return simulated time if set, else system UTC
- `set_time(dt: datetime | None)`: set or clear simulated time
- `advance(delta: timedelta)`: fast-forward simulated time
- `time_scale: float` (default 1.0); background asyncio task drives clock at this rate
- `set_time_scale(scale: float)`: change speed

## 2. Backend: SimulationState

- `app/simulation/state.py` — singleton
- Maintains current `DrivingContext` snapshot
- `update_field(field_path: str, value: Any)`: update a single field (e.g. `"speedKmh"`, `"driver.fatigueLevel"`)
- `get_context() -> dict`: return full context for workflow/scheduler use
- `get_field(field_path: str) -> Any`: read a single field

## 3. WebSocket Communication

### Endpoint

- FastAPI WebSocket route at `/ws`
- Clients auto-subscribe to broadcast on connect

### Message Protocol (JSON)

**Server → Client:**

| type | payload | description |
|------|---------|-------------|
| `clock_tick` | `{current_time: str}` | Periodic clock update (~1s real-time) |
| `state_sync` | `{context: dict}` | Another client updated context |
| `proactive_reminder` | `{reminder: dict}` | Scheduler-triggered reminder |
| `state_update_ack` | `{field: str, value: Any}` | Field update confirmation |

**Client → Server:**

| type | payload | description |
|------|---------|-------------|
| `update_field` | `{field: str, value: Any}` | Real-time single field update |
| `set_clock` | `{datetime: str}` | Set simulated time (ISO 8601) |
| `set_time_scale` | `{scale: float}` | Set clock speed multiplier |

### Connection Manager

- `app/simulation/ws_manager.py`
- `ConnectionManager` class: track connected clients, broadcast, send-to-all

## 4. Event Scheduler

- `app/simulation/scheduler.py` — asyncio background task
- Periodically scans stored events from memory module
- Checks if `simulated_time >= event.remind_at` for pending reminders
- When triggered: runs Strategy Agent decision → broadcasts `proactive_reminder` via WebSocket
- Polling interval: configurable, default 5s simulated time
- Deduplication: tracks which event_ids have been reminded

## 5. GraphQL Changes

### New Mutations

- `setSimulationClock(datetime: String, timeScale: Float): SimulationClockResult`
- `resetSimulationClock(): SimulationClockResult`

### Modified Mutations

- `processQuery`: when `SimulationState` has active context and no explicit `context` is provided, use `SimulationState.get_context()` automatically
- Workflow `_context_node`: use `SimulationClock.now()` instead of `datetime.now(timezone.utc)`

### New Query

- `simulationClock: SimulationClockInfo` — returns current simulated time, time_scale, is_simulated flag

## 6. Frontend UI Changes

### Left Panel

**Simulated Clock Section (new):**

- Large clock display showing current simulated time (auto-updating via WebSocket)
- `<input type="date">` + `<input type="time" step="1">` for manual time setting
- Time scale buttons: `1x / 2x / 5x / 10x / 60x` button group
- Quick actions: "Fast-forward 1h", "Fast-forward to tomorrow 9:00"
- "Reset to system time" button

**Number Spinner Component:**

- All `<input type="number">` fields (lat, lng, speed, ETA, delay) become: `[-] [input] [+]`
- `-/+` buttons adjust by `step` value, trigger WebSocket `update_field`
- Fatigue range slider also gets `[-] [input] [+]` treatment (step=0.1)

**Real-time Sync:**

- All field `oninput` events → WebSocket `update_field` message
- Preset load → batch field updates via WebSocket

**Presets (unchanged):**

- Save/clear preset buttons remain, still use GraphQL mutations

### Right Panel

**Notification Banner (new):**

- Top of right panel, hidden by default
- Slides in on `proactive_reminder` WebSocket message
- Shows reminder content, decision reason, timestamp
- Manual dismiss button
- History of received notifications

**Query & Stages (unchanged)**

### Styles

- `.number-spinner`: flex layout, `[-] input [+]`, fixed button width
- `.clock-panel`: dark background, large monospace time display
- `.notification-banner`: slide-in animation, amber/orange accent

## 7. Data Flow

```
User edits field → oninput → WebSocket(update_field) → SimulationState
                                                          ↓
Set simulated time → WebSocket(set_clock) → SimulationClock
                                                          ↓
                                                  Event Scheduler scans
                                                          ↓
                                      Strategy Agent → WebSocket(proactive_reminder) → Frontend banner
                                                          ↓
User sends query → GraphQL(processQuery) → workflow uses SimulationState + SimulationClock
```

## 8. Testing

- New `tests/test_simulation/` directory
- `test_clock.py`: SimulationClock unit tests
- `test_state.py`: SimulationState unit tests
- `test_scheduler.py`: Event scheduler tests (mock memory, mock clock)
- `test_ws.py`: WebSocket integration tests
- Existing `test_graphql.py`: mock SimulationState/Clock for existing tests

## 9. Dependencies

- `websockets` — Python WebSocket support (FastAPI dependency)
- No new frontend dependencies (native WebSocket API)

## Out of Scope

- Real sensor/device integration
- Multi-user authentication
- Persistent simulation state across server restarts
