# 基线记忆后端适配器 + 生产 Store 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 VehicleMemBench 的 4 个基线封装为评估 adapter，并将 summary/kv 封装为生产 store。

**Architecture:** 两层架构。评估层（adapters/）注册到 ADAPTERS 字典供 runner.py 调用。生产层（app/memory/stores/）实现 MemoryStore Protocol 注册到 _STORES_REGISTRY。ChatModel 新增 generate_with_tools() 支持 tool calling。

**Tech Stack:** Python 3.13+, LangChain ChatOpenAI (bind_tools), pydantic, pytest

**Spec:** `docs/superpowers/specs/2026-04-01-baseline-memory-adapters-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `app/models/chat.py` | ChatModel.generate_with_tools() — 多轮 tool calling loop |
| `app/memory/types.py` | MemoryMode 枚举新增 SUMMARY / KEY_VALUE |
| `app/memory/memory.py` | _import_all_stores() 注册新 store |
| `app/memory/stores/summary_store.py` | SummaryStore — 增量摘要，tool calling 更新 |
| `app/memory/stores/kv_store.py` | KVStore — 增量 KV 提取，模糊搜索 |
| `adapters/memory_adapters/common.py` | BaselineMemory dataclass |
| `adapters/memory_adapters/none_adapter.py` | NoneAdapter |
| `adapters/memory_adapters/gold_adapter.py` | GoldAdapter |
| `adapters/memory_adapters/summary_adapter.py` | SummaryAdapter |
| `adapters/memory_adapters/kv_adapter.py` | KVAdapter |
| `adapters/memory_adapters/__init__.py` | ADAPTERS 注册 |
| `adapters/memory_adapters/memory_bank_adapter.py` | 签名更新 |
| `adapters/runner.py` | prepare 统一，run 新增 none |
| `tests/stores/test_summary_store.py` | SummaryStore 测试 |
| `tests/stores/test_kv_store.py` | KVStore 测试 |
| `tests/test_memory_store_contract.py` | contract 测试参数化扩展 |

---

### Task 1: ChatModel.generate_with_tools()

**Files:**
- Modify: `app/models/chat.py`
- Test: `tests/test_chat_model.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_chat_model.py`:

```python
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage, ToolMessage
from app.models.chat import ChatModel
from app.models.settings import LLMProviderConfig


def _make_provider() -> LLMProviderConfig:
    return LLMProviderConfig(
        provider=MagicMock(
            model="test-model",
            api_key="test-key",
            base_url="http://localhost:8000/v1",
            temperature=0.0,
        )
    )


def test_generate_with_tools_single_round():
    provider = _make_provider()
    model = ChatModel(providers=[provider])

    fake_tool_call = {
        "name": "memory_update",
        "args": {"new_memory": "updated"},
        "id": "call_1",
        "type": "tool_call",
    }
    first_response = AIMessage(content="", tool_calls=[fake_tool_call])
    final_response = AIMessage(content="done")

    mock_client = MagicMock()
    bound = MagicMock()
    mock_client.bind_tools.return_value = bound
    bound.invoke.side_effect = [first_response, final_response]

    with patch.object(model, "_create_client", return_value=mock_client):
        result = model.generate_with_tools(
            prompt="test",
            tools=[{"type": "function", "function": {"name": "memory_update", "parameters": {}}}],
            tool_executor=lambda name, args: "ok",
        )
    assert result == "done"


def test_generate_with_tools_no_tool_call():
    provider = _make_provider()
    model = ChatModel(providers=[provider])

    mock_client = MagicMock()
    bound = MagicMock()
    mock_client.bind_tools.return_value = bound
    bound.invoke.return_value = AIMessage(content="direct answer")

    with patch.object(model, "_create_client", return_value=mock_client):
        result = model.generate_with_tools(
            prompt="test",
            tools=[],
            tool_executor=lambda name, args: "ok",
        )
    assert result == "direct answer"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chat_model.py -v`
Expected: FAIL (AttributeError: 'ChatModel' has no attribute 'generate_with_tools')

- [ ] **Step 3: Write minimal implementation**

Add to `app/models/chat.py`, after `batch_generate`:

```python
from langchain_core.messages import AIMessage, ToolMessage
from typing import Callable

def generate_with_tools(
    self,
    prompt: str,
    tools: list[dict],
    system_prompt: Optional[str] = None,
    *,
    max_rounds: int = 10,
    tool_executor: Callable[[str, dict], str],
) -> str:
    messages: list = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=prompt))

    errors: list[str] = []
    for provider in self.providers:
        try:
            client = self._create_client(provider)
            bound = client.bind_tools(tools)
            ai_response: AIMessage = bound.invoke(messages)
            rounds = 0
            while ai_response.tool_calls and rounds < max_rounds:
                messages.append(ai_response)
                for tc in ai_response.tool_calls:
                    result = tool_executor(tc["name"], tc["args"])
                    messages.append(
                        ToolMessage(content=str(result), tool_call_id=tc["id"])
                    )
                ai_response = bound.invoke(messages)
                rounds += 1
            return str(ai_response.content)
        except Exception as e:
            errors.append(f"{provider.provider.model}: {e}")
            continue

    raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")
```

Also add `Callable` to the existing `from typing import Optional, cast` import line.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_chat_model.py -v`
Expected: PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `uv run ruff check app/models/chat.py && uv run mypy app/models/chat.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add app/models/chat.py tests/test_chat_model.py
git commit -m "feat: add ChatModel.generate_with_tools() for tool calling support"
```

---

### Task 2: MemoryMode 扩展 + Store 注册

**Files:**
- Modify: `app/memory/types.py`
- Modify: `app/memory/memory.py`

- [ ] **Step 1: Update MemoryMode enum**

In `app/memory/types.py`, add two new values:

```python
class MemoryMode(StrEnum):
    MEMORY_BANK = "memory_bank"
    SUMMARY = "summary"
    KEY_VALUE = "key_value"
```

- [ ] **Step 2: Run lint**

Run: `uv run ruff check app/memory/types.py`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add app/memory/types.py
git commit -m "feat: add SUMMARY and KEY_VALUE to MemoryMode enum"
```

Note: `_import_all_stores()` 注册将在 Task 5 中与 contract 测试一起提交，避免中间状态 import 崩溃。

---

### Task 3: SummaryStore (生产)

**Files:**
- Create: `app/memory/stores/summary_store.py`
- Create: `tests/stores/test_summary_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/stores/test_summary_store.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock

from app.memory.schemas import MemoryEvent, SearchResult
from app.memory.stores.summary_store import SummaryStore


def _mock_chat_model(return_value: str = "mock summary") -> MagicMock:
    model = MagicMock()
    model.generate_with_tools.return_value = return_value
    return model


def test_write_returns_event_id(tmp_path: Path):
    store = SummaryStore(tmp_path)
    event_id = store.write(MemoryEvent(content="test"))
    assert isinstance(event_id, str) and len(event_id) > 0


def test_search_returns_empty_when_no_summary(tmp_path: Path):
    store = SummaryStore(tmp_path)
    assert store.search("query") == []


def test_search_returns_summary_as_single_result(tmp_path: Path):
    store = SummaryStore(tmp_path, chat_model=_mock_chat_model())
    store.write(MemoryEvent(content="event1"))
    store.write(MemoryEvent(content="event2"))
    results = store.search("anything")
    assert len(results) == 1
    assert isinstance(results[0], SearchResult)
    assert results[0].source == "summary"


def test_get_history_returns_events(tmp_path: Path):
    store = SummaryStore(tmp_path)
    store.write(MemoryEvent(content="event1"))
    store.write(MemoryEvent(content="event2"))
    history = store.get_history(limit=10)
    assert len(history) == 2
    assert all(isinstance(e, MemoryEvent) for e in history)


def test_get_history_respects_limit(tmp_path: Path):
    store = SummaryStore(tmp_path)
    for i in range(5):
        store.write(MemoryEvent(content=f"event{i}"))
    assert len(store.get_history(limit=3)) == 3


def test_write_interaction_records_event(tmp_path: Path):
    store = SummaryStore(tmp_path, chat_model=_mock_chat_model())
    event_id = store.write_interaction("query", "response")
    assert isinstance(event_id, str) and len(event_id) > 0
    history = store.get_history(limit=10)
    assert len(history) == 1


def test_update_feedback_does_not_crash(tmp_path: Path):
    store = SummaryStore(tmp_path)
    event_id = store.write(MemoryEvent(content="event"))
    store.update_feedback(event_id, MagicMock(event_id=event_id, action="accept"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/stores/test_summary_store.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write implementation**

Create `app/memory/stores/summary_store.py`:

```python
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from app.memory.components import EventStorage
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.models.chat import ChatModel
from app.storage.json_store import JSONStore

SUMMARY_UPDATE_THRESHOLD = 2
MAX_MEMORY_LENGTH = 8192

_SUMMARY_SYSTEM_PROMPT = """You are an intelligent assistant that maintains a CONCISE memory of user vehicle preferences from conversations.

**CRITICAL RULES:**
1. If today's conversation contains NEW vehicle-related information → Call memory_update with the complete updated memory
2. If today's conversation has NO new vehicle information → Do NOT call any tool, just respond that no update is needed
3. Keep the total memory under 2000 words
4. ONLY record vehicle-related preferences

**MUST capture (Priority 1 - Vehicle preferences):**
- In-car device settings: temperature, brightness, volume, seat position, ambient light color, navigation mode, HUD, air conditioning, massage, ventilation, instrument panel color, etc.
- Conditional preferences: e.g., "at night prefer white dashboard", "in industrial areas use inside circulation"
- User-specific preferences when there are conflicts between users
- Corrections or updates to previous settings

**MAY capture briefly (Priority 2 - Only if directly relevant to vehicle):**
- Frequently visited locations (for navigation): workplace, home address
- Physical conditions that affect vehicle settings: e.g., "back pain" → needs seat massage

**DO NOT capture:**
- General life events, plans, hobbies
- Work details unrelated to driving
- Personal relationships (unless affecting vehicle settings)

Output format for memory_update: Concise bullet points organized by user name.
Example:
**UserName**
- instrument_panel_color: green
- night_dashboard_preference: white (can't see gauges with dark colors at night)
- seat_massage: enabled when back hurts
"""

_MEMORY_UPDATE_TOOL = [{
    "type": "function",
    "function": {
        "name": "memory_update",
        "description": "Update the memory with new vehicle-related preferences. Call this ONLY if you found NEW or CHANGED vehicle preferences in today's conversation. If no new vehicle information is found, do NOT call this tool.",
        "parameters": {
            "type": "object",
            "properties": {
                "new_memory": {
                    "type": "string",
                    "description": "The complete updated memory content. This should include ALL existing preferences (from previous memory) plus any new/changed preferences from today's conversation. Format: bullet points organized by user name."
                }
            },
            "required": ["new_memory"]
        }
    }
}]


class SummaryStore:
    store_name = "summary"
    requires_embedding = False
    requires_chat = True
    supports_interaction = True

    def __init__(
        self,
        data_dir: Path,
        chat_model: Optional[ChatModel] = None,
        **kwargs,
    ) -> None:
        self._storage = EventStorage(data_dir)
        self._state_store = JSONStore(data_dir, Path("summary_state.json"), dict)
        self.chat_model = chat_model

    def _read_state(self) -> dict:
        state = self._state_store.read()
        if not state:
            return {"summary": "", "pending_count": 0}
        return state

    def _write_state(self, state: dict) -> None:
        self._state_store.write(state)

    def _maybe_update_summary(self) -> None:
        if not self.chat_model:
            return
        state = self._read_state()
        if state.get("pending_count", 0) < SUMMARY_UPDATE_THRESHOLD:
            return
        events = self._storage.read_events()
        if not events:
            return
        pending = events[-state["pending_count"]:]
        content = "\n".join(e.get("content", "") for e in pending if e.get("content"))
        if not content.strip():
            return
        current_summary = state.get("summary", "")
        prompt = f"**Current Memory:**\n{current_summary}\n\n**New Conversations:**\n{content}\n\nPlease review and update the memory if needed."
        new_summary = current_summary

        def _tool_executor(name: str, args: dict) -> str:
            nonlocal new_summary
            if name == "memory_update":
                new_summary = args.get("new_memory", current_summary)
            return '{"success": true}'

        self.chat_model.generate_with_tools(
            prompt=prompt,
            tools=_MEMORY_UPDATE_TOOL,
            system_prompt=_SUMMARY_SYSTEM_PROMPT,
            tool_executor=_tool_executor,
        )
        if len(new_summary) > MAX_MEMORY_LENGTH:
            pos = new_summary.rfind("\n-", 0, MAX_MEMORY_LENGTH)
            if pos > MAX_MEMORY_LENGTH // 2:
                new_summary = new_summary[:pos] + "\n[Memory truncated due to length limit]"
            else:
                new_summary = new_summary[:MAX_MEMORY_LENGTH] + "\n[Memory truncated due to length limit]"
        state["summary"] = new_summary
        state["pending_count"] = 0
        self._write_state(state)

    def write(self, event: MemoryEvent) -> str:
        event_id = self._storage.append_event(event)
        state = self._read_state()
        state["pending_count"] = state.get("pending_count", 0) + 1
        self._write_state(state)
        self._maybe_update_summary()
        return event_id

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        state = self._read_state()
        summary = state.get("summary", "")
        if not summary:
            return []
        return [SearchResult(event={"content": summary, "type": "summary"}, score=1.0, source="summary")]

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        events = self._storage.read_events()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        pass

    def write_interaction(self, query: str, response: str, event_type: str = "reminder") -> str:
        event = MemoryEvent(content=query, type=event_type, description=response)
        return self.write(event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/stores/test_summary_store.py -v`
Expected: PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `uv run ruff check app/memory/stores/summary_store.py && uv run mypy app/memory/stores/summary_store.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add app/memory/stores/summary_store.py tests/stores/test_summary_store.py
git commit -m "feat: add SummaryStore production backend with tool calling"
```

---

### Task 4: KVStore (生产)

**Files:**
- Create: `app/memory/stores/kv_store.py`
- Create: `tests/stores/test_kv_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/stores/test_kv_store.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock

from app.memory.schemas import MemoryEvent, SearchResult
from app.memory.stores.kv_store import KVStore


def _mock_chat_model() -> MagicMock:
    model = MagicMock()
    model.generate_with_tools.return_value = "done"
    return model


def test_write_returns_event_id(tmp_path: Path):
    store = KVStore(tmp_path)
    event_id = store.write(MemoryEvent(content="test"))
    assert isinstance(event_id, str) and len(event_id) > 0


def test_search_empty_store(tmp_path: Path):
    store = KVStore(tmp_path)
    assert store.search("query") == []


def test_search_finds_kv_entry(tmp_path: Path):
    store = KVStore(tmp_path)
    state = store._read_state()
    state["kv_data"] = {"Gary_seat_position": "forward", "Patricia_temp": "22"}
    store._write_state(state)
    results = store.search("Gary_seat")
    assert len(results) >= 1
    assert "Gary_seat_position" in results[0].event["content"]


def test_search_fuzzy_match(tmp_path: Path):
    store = KVStore(tmp_path)
    state = store._read_state()
    state["kv_data"] = {"Gary_instrument_panel_color": "green"}
    store._write_state(state)
    results = store.search("panel")
    assert len(results) >= 1


def test_search_no_match(tmp_path: Path):
    store = KVStore(tmp_path)
    state = store._read_state()
    state["kv_data"] = {"Gary_temp": "22"}
    store._write_state(state)
    results = store.search("nonexistent")
    assert len(results) == 0


def test_get_history_returns_events(tmp_path: Path):
    store = KVStore(tmp_path)
    store.write(MemoryEvent(content="event1"))
    store.write(MemoryEvent(content="event2"))
    history = store.get_history(limit=10)
    assert len(history) == 2


def test_write_interaction_records_event(tmp_path: Path):
    store = KVStore(tmp_path, chat_model=_mock_chat_model())
    event_id = store.write_interaction("query", "response")
    assert isinstance(event_id, str) and len(event_id) > 0


def test_update_feedback_does_not_crash(tmp_path: Path):
    store = KVStore(tmp_path)
    event_id = store.write(MemoryEvent(content="event"))
    store.update_feedback(event_id, MagicMock(event_id=event_id, action="ignore"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/stores/test_kv_store.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write implementation**

Create `app/memory/stores/kv_store.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.memory.components import EventStorage
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.models.chat import ChatModel
from app.storage.json_store import JSONStore

KV_UPDATE_THRESHOLD = 2

_KV_SYSTEM_PROMPT = """You are an intelligent assistant that maintains a key-value memory store of user VEHICLE PREFERENCES from conversations.

**CRITICAL CONSTRAINTS:**
- ONLY store vehicle-related preferences and directly relevant context
- DO NOT store general life information (hobbies, plans, events, work details) unless they DIRECTLY affect vehicle settings
- Use concise values (under 50 characters per value)

Your task:
1. Review the current memory state provided below
2. Read today's conversation carefully
3. Extract and store ONLY vehicle-related information:

**MUST capture (Priority 1 - Vehicle preferences):**
- In-car device settings: temperature, brightness, volume, seat position, ambient light color, navigation mode, HUD, AC, massage, ventilation, instrument panel color
- Conditional preferences: e.g., "Gary_night_panel_color" = "white", "Patricia_industrial_area_circulation" = "inside"
- User-specific preferences when there are conflicts between users
- Corrections to previous settings (update the value)

**MAY capture briefly (Priority 2 - Only if directly relevant to vehicle):**
- Frequently visited locations (for navigation): "Justin_workplace" = "hospital"
- Physical conditions that affect vehicle settings: "Gary_back_condition" = "needs seat massage"

**DO NOT capture:**
- General life events, plans, hobbies
- Work details unrelated to driving
- Personal relationships (unless affecting vehicle settings)

4. Use memory_add() to store new entries or update changed ones
5. Use memory_remove() if information is explicitly revoked or outdated

If no vehicle-related information is mentioned today, do nothing."""

_KV_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "memory_add",
            "description": "Add or update a memory entry. If the key already exists, the value will be overwritten.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "A descriptive key for the memory entry (e.g., 'Gary_instrument_panel_color')"},
                    "value": {"type": "string", "description": "The value to store (e.g., 'green')"}
                },
                "required": ["key", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "memory_remove",
            "description": "Remove a memory entry by key.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "The key of the memory entry to remove"}
                },
                "required": ["key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search memory entries by key. Supports both exact and fuzzy matching.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "The key or keyword to search for"}
                },
                "required": ["key"]
            }
        }
    },
]


def _kv_search(kv_data: dict[str, str], key: str) -> dict[str, str]:
    if key in kv_data:
        return {key: kv_data[key]}
    key_lower = key.lower()
    return {k: v for k, v in kv_data.items() if key_lower in k.lower() or key_lower in v.lower()}


class KVStore:
    store_name = "key_value"
    requires_embedding = False
    requires_chat = True
    supports_interaction = True

    def __init__(
        self,
        data_dir: Path,
        chat_model: Optional[ChatModel] = None,
        **kwargs,
    ) -> None:
        self._storage = EventStorage(data_dir)
        self._state_store = JSONStore(data_dir, Path("kv_state.json"), dict)
        self.chat_model = chat_model

    def _read_state(self) -> dict:
        state = self._state_store.read()
        if not state:
            return {"kv_data": {}, "pending_count": 0}
        return state

    def _write_state(self, state: dict) -> None:
        self._state_store.write(state)

    def _maybe_extract_kv(self) -> None:
        if not self.chat_model:
            return
        state = self._read_state()
        if state.get("pending_count", 0) < KV_UPDATE_THRESHOLD:
            return
        events = self._storage.read_events()
        if not events:
            return
        pending = events[-state["pending_count"]:]
        content = "\n".join(e.get("content", "") for e in pending if e.get("content"))
        if not content.strip():
            return
        kv_data: dict[str, str] = dict(state.get("kv_data", {}))
        current_keys = ", ".join(kv_data.keys()) if kv_data else "No vehicle preferences recorded yet."
        prompt = f"**Current Memory Keys:**\n{current_keys}\n\n**New Conversations:**\n{content}\n\nPlease review the conversation and update the memory store with any VEHICLE-RELATED preferences found."

        def _tool_executor(name: str, args: dict) -> str:
            import json
            if name == "memory_add":
                kv_data[args["key"]] = args["value"]
                return json.dumps({"success": True, "action": "updated", "key": args["key"]})
            if name == "memory_remove":
                kv_data.pop(args.get("key", ""), None)
                return json.dumps({"success": True, "action": "removed", "key": args.get("key", "")})
            if name == "memory_search":
                results = _kv_search(kv_data, args.get("key", ""))
                return json.dumps({"success": True, "results": results})
            return json.dumps({"success": False, "error": f"Unknown function: {name}"})

        self.chat_model.generate_with_tools(
            prompt=prompt,
            tools=_KV_TOOLS,
            system_prompt=_KV_SYSTEM_PROMPT,
            tool_executor=_tool_executor,
        )
        state["kv_data"] = kv_data
        state["pending_count"] = 0
        self._write_state(state)

    def write(self, event: MemoryEvent) -> str:
        event_id = self._storage.append_event(event)
        state = self._read_state()
        state["pending_count"] = state.get("pending_count", 0) + 1
        self._write_state(state)
        self._maybe_extract_kv()
        return event_id

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        state = self._read_state()
        kv_data: dict[str, str] = state.get("kv_data", {})
        if not kv_data:
            return []
        matches = _kv_search(kv_data, query)
        results = []
        for k, v in matches.items():
            results.append(SearchResult(
                event={"content": f"{k}: {v}", "type": "kv_entry", "key": k, "value": v},
                score=1.0 if k == query else 0.7,
                source="kv_store",
            ))
        return results[:top_k]

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        events = self._storage.read_events()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        pass

    def write_interaction(self, query: str, response: str, event_type: str = "reminder") -> str:
        event = MemoryEvent(content=query, type=event_type, description=response)
        return self.write(event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/stores/test_kv_store.py -v`
Expected: PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `uv run ruff check app/memory/stores/kv_store.py && uv run mypy app/memory/stores/kv_store.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add app/memory/stores/kv_store.py tests/stores/test_kv_store.py
git commit -m "feat: add KVStore production backend with fuzzy search"
```

---

### Task 5: Contract 测试扩展 + Store 注册

**Files:**
- Modify: `tests/test_memory_store_contract.py`
- Modify: `app/memory/memory.py`

- [ ] **Step 1: Update _import_all_stores() registration**

In `app/memory/memory.py`, update `_import_all_stores()`:

```python
def _import_all_stores() -> None:
    from app.memory.stores.memory_bank_store import MemoryBankStore
    from app.memory.stores.summary_store import SummaryStore
    from app.memory.stores.kv_store import KVStore

    register_store(MemoryMode.MEMORY_BANK, MemoryBankStore)
    register_store(MemoryMode.SUMMARY, SummaryStore)
    register_store(MemoryMode.KEY_VALUE, KVStore)
```

- [ ] **Step 2: Update _get_store_params and fix tests for summary/kv**

The existing contract tests assume `events_store` and `strategies_store` properties (MemoryBank-specific). For summary/kv stores these don't exist. The tests need to be adapted.

Update `tests/test_memory_store_contract.py`:

```python
def _get_store_params() -> list[str]:
    return ["memory_bank", "summary", "key_value"]
```

For `test_write_then_search_returns_same_event`: only check events_store for memory_bank:

```python
def test_write_then_search_returns_same_event(self, store: "MemoryStore") -> None:
    event_id = store.write(MemoryEvent(content="测试事件"))
    if hasattr(store, "events_store"):
        events_store = cast(Any, store).events_store
        events = events_store.read()
        assert any(e["id"] == event_id for e in events)
```

For `test_update_feedback_updates_strategies`: only check for memory_bank:

```python
def test_update_feedback_does_not_crash(self, store: "MemoryStore") -> None:
    event_id = store.write(MemoryEvent(content="事件"))
    store.update_feedback(event_id, FeedbackData(action="accept", type="meeting"))
    if hasattr(store, "strategies_store"):
        strategies_store = cast(Any, store).strategies_store
        strategies = strategies_store.read()
        assert "reminder_weights" in strategies
```

Note: rename from `test_update_feedback_updates_strategies` to `test_update_feedback_does_not_crash` to reflect that only memory_bank has strategies.

- [ ] **Step 3: Run all contract tests**

Run: `uv run pytest tests/test_memory_store_contract.py -v`
Expected: PASS for all 3 store types

- [ ] **Step 4: Commit**

```bash
git add tests/test_memory_store_contract.py app/memory/memory.py
git commit -m "test: extend MemoryStore contract tests for summary and kv, register new stores"
```

---

### Task 6: BaselineMemory + 评估 Adapter (None/Gold/Summary/KV)

**Files:**
- Modify: `adapters/memory_adapters/common.py`
- Create: `adapters/memory_adapters/none_adapter.py`
- Create: `adapters/memory_adapters/gold_adapter.py`
- Create: `adapters/memory_adapters/summary_adapter.py`
- Create: `adapters/memory_adapters/kv_adapter.py`
- Modify: `adapters/memory_adapters/__init__.py`
- Modify: `adapters/memory_adapters/memory_bank_adapter.py`

- [ ] **Step 1: Add BaselineMemory to common.py**

In `adapters/memory_adapters/common.py`, add after the existing code:

```python
from dataclasses import dataclass

@dataclass
class BaselineMemory:
    memory_type: str
    memory_text: str = ""
    kv_store: dict[str, str] | None = None

    def __post_init__(self):
        if self.kv_store is None:
            self.kv_store = {}
```

- [ ] **Step 2: Create NoneAdapter**

Create `adapters/memory_adapters/none_adapter.py`:

```python
from pathlib import Path
from adapters.memory_adapters.common import BaselineMemory


class NoneAdapter:
    TAG = "none"

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def add(self, history_text: str, **kwargs) -> BaselineMemory:
        return BaselineMemory(memory_type="none")

    def get_search_client(self, store: BaselineMemory) -> None:
        raise NotImplementedError("NoneAdapter does not support search client")
```

All baseline adapters' `get_search_client` raises `NotImplementedError` because runner.py dispatches by type for baseline evaluation — only `memory_bank` uses `get_search_client`.

- [ ] **Step 3: Create GoldAdapter**

Create `adapters/memory_adapters/gold_adapter.py`:

```python
from pathlib import Path
from adapters.memory_adapters.common import BaselineMemory


class GoldAdapter:
    TAG = "gold"

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def add(self, history_text: str, **kwargs) -> BaselineMemory:
        return BaselineMemory(memory_type="gold")

    def get_search_client(self, store: BaselineMemory) -> None:
        raise NotImplementedError("GoldAdapter does not support search client")
```

- [ ] **Step 4: Create SummaryAdapter**

Create `adapters/memory_adapters/summary_adapter.py`:

```python
import sys
import os
from pathlib import Path

from adapters.memory_adapters.common import BaselineMemory


class SummaryAdapter:
    TAG = "summary"

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def add(self, history_text: str, **kwargs) -> BaselineMemory:
        agent_client = kwargs.get("agent_client")
        if not agent_client:
            return BaselineMemory(memory_type="summary")
        from adapters.runner import setup_vehiclemembench_path
        setup_vehiclemembench_path()
        from evaluation.model_evaluation import split_history_by_day, build_memory_recursive_summary
        daily = split_history_by_day(history_text)
        mem_text, _, _ = build_memory_recursive_summary(agent_client, daily)
        return BaselineMemory(memory_type="summary", memory_text=mem_text)

    def get_search_client(self, store: BaselineMemory) -> None:
        raise NotImplementedError("SummaryAdapter does not support search client")
```

- [ ] **Step 5: Create KVAdapter**

Create `adapters/memory_adapters/kv_adapter.py`:

```python
from pathlib import Path

from adapters.memory_adapters.common import BaselineMemory


class KVAdapter:
    TAG = "kv"

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def add(self, history_text: str, **kwargs) -> BaselineMemory:
        agent_client = kwargs.get("agent_client")
        if not agent_client:
            return BaselineMemory(memory_type="kv")
        from adapters.runner import setup_vehiclemembench_path
        setup_vehiclemembench_path()
        from evaluation.model_evaluation import split_history_by_day, build_memory_key_value
        daily = split_history_by_day(history_text)
        store, _, _ = build_memory_key_value(agent_client, daily)
        return BaselineMemory(memory_type="kv", kv_store=store.to_dict())

    def get_search_client(self, store: BaselineMemory) -> None:
        raise NotImplementedError("KVAdapter does not support search client")
```

- [ ] **Step 6: Update __init__.py**

Update `adapters/memory_adapters/__init__.py`:

```python
from adapters.memory_adapters.memory_bank_adapter import MemoryBankAdapter
from adapters.memory_adapters.none_adapter import NoneAdapter
from adapters.memory_adapters.gold_adapter import GoldAdapter
from adapters.memory_adapters.summary_adapter import SummaryAdapter
from adapters.memory_adapters.kv_adapter import KVAdapter

ADAPTERS = {
    "memory_bank": MemoryBankAdapter,
    "none": NoneAdapter,
    "gold": GoldAdapter,
    "summary": SummaryAdapter,
    "kv": KVAdapter,
}
```

- [ ] **Step 7: Update MemoryBankAdapter signature**

In `adapters/memory_adapters/memory_bank_adapter.py`, update `add`:

```python
def add(self, history_text: str, **kwargs) -> MemoryBankStore:
```

- [ ] **Step 8: Run lint**

Run: `uv run ruff check adapters/memory_adapters/`
Expected: No errors

- [ ] **Step 9: Commit**

```bash
git add adapters/memory_adapters/
git commit -m "feat: add baseline memory adapters (none/gold/summary/kv)"
```

---

### Task 7: runner.py 改造

**Files:**
- Modify: `adapters/runner.py`

- [ ] **Step 1: Update SUPPORTED_MEMORY_TYPES**

```python
SUPPORTED_MEMORY_TYPES = {"none", "gold", "summary", "kv", "memory_bank"}
```

- [ ] **Step 2: Update _prepare_single to use ADAPTERS**

Replace the `_prepare_single` function:

```python
def _prepare_single(
    agent_client: AgentClient, history_text: str, file_num: int, memory_type: str
) -> dict | None:
    if memory_type not in ADAPTERS:
        return None
    adapter_cls = ADAPTERS[memory_type]
    adapter = adapter_cls(data_dir=_get_output_dir() / f"store_{memory_type}_{file_num}")
    store = adapter.add(history_text, agent_client=agent_client)
    if isinstance(store, BaselineMemory):
        return {
            "type": store.memory_type,
            "memory_text": store.memory_text,
            "kv_store": store.kv_store,
        }
    return {"type": memory_type, "data_dir": str(adapter.data_dir)}
```

Add import for `BaselineMemory`:
```python
from adapters.memory_adapters.common import BaselineMemory, format_search_results
```

- [ ] **Step 3: Update _run_single**

Replace the entire evaluation loop body inside `_run_single`:

```python
try:
    if memory_type == "none":
        result = process_task_direct(task, i, agent_client, reflect_num)
    elif memory_type == "gold":
        task["history_text"] = gold_memory
        result = process_task_direct(task, i, agent_client, reflect_num)
    elif memory_type == "summary":
        memory_text = prep_data.get("memory_text", "")
        result = process_task_with_memory(
            task, i, memory_text, agent_client, reflect_num
        )
    elif memory_type == "kv":
        vmb_store = VMBMemoryStore()
        vmb_store.store = prep_data.get("kv_store", {})
        result = process_task_with_kv_memory(
            task, i, vmb_store, agent_client, reflect_num
        )
    elif memory_type in ADAPTERS:
        result = _run_custom_adapter(
            agent_client, task, i, prep_data, memory_type, reflect_num
        )
    else:
        continue
```

Keep the `memory_type in ADAPTERS` fallback for memory_bank and future adapters.

- [ ] **Step 4: Run lint**

Run: `uv run ruff check adapters/runner.py`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add adapters/runner.py
git commit -m "refactor: unify prepare via ADAPTERS, add none baseline to runner"
```

---

### Task 8: Final Verification

- [ ] **Step 1: Run full lint and typecheck**

Run: `uv run ruff check . && uv run mypy app/ adapters/`

- [ ] **Step 2: Run all tests**

Run: `uv run pytest tests/ -v`

- [ ] **Step 3: Verify imports work end-to-end**

Run: `uv run python -c "from app.memory.memory import MemoryModule; from app.memory.types import MemoryMode; print(list(MemoryMode))"`
Expected: `[<MemoryMode.MEMORY_BANK: 'memory_bank'>, <MemoryMode.SUMMARY: 'summary'>, <MemoryMode.KEY_VALUE: 'key_value'>]`

- [ ] **Step 4: Verify ADAPTERS registry**

Run: `uv run python -c "from adapters.memory_adapters import ADAPTERS; print(list(ADAPTERS.keys()))"`
Expected: `['memory_bank', 'none', 'gold', 'summary', 'kv']`
