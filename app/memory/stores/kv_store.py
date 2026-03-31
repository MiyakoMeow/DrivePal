"""KVStore - 生产后端，基于LLM工具调用维护键值对形式的用户车辆偏好."""

from __future__ import annotations

import json
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
                    "key": {
                        "type": "string",
                        "description": "A descriptive key for the memory entry (e.g., 'Gary_instrument_panel_color')",
                    },
                    "value": {
                        "type": "string",
                        "description": "The value to store (e.g., 'green')",
                    },
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_remove",
            "description": "Remove a memory entry by key.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "The key of the memory entry to remove",
                    }
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search memory entries by key. Supports both exact and fuzzy matching.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "The key or keyword to search for",
                    }
                },
                "required": ["key"],
            },
        },
    },
]


def _kv_search(kv_data: dict[str, str], key: str) -> dict[str, str]:
    if key in kv_data:
        return {key: kv_data[key]}
    key_lower = key.lower()
    return {
        k: v
        for k, v in kv_data.items()
        if key_lower in k.lower() or key_lower in v.lower()
    }


class KVStore:
    """键值对记忆存储，通过LLM工具调用从对话中提取车辆偏好."""

    store_name = "key_value"
    requires_embedding = False
    requires_chat = True
    supports_interaction = True

    def __init__(
        self,
        data_dir: Path,
        chat_model: Optional[ChatModel] = None,
        **kwargs: dict,
    ) -> None:
        """初始化KV存储."""
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
        pending = events[-state["pending_count"] :]
        content = "\n".join(e.get("content", "") for e in pending if e.get("content"))
        if not content.strip():
            return
        kv_data: dict[str, str] = dict(state.get("kv_data", {}))
        current_keys = (
            ", ".join(kv_data.keys())
            if kv_data
            else "No vehicle preferences recorded yet."
        )
        prompt = f"**Current Memory Keys:**\n{current_keys}\n\n**New Conversations:**\n{content}\n\nPlease review the conversation and update the memory store with any VEHICLE-RELATED preferences found."

        def _tool_executor(name: str, args: dict) -> str:
            if name == "memory_add":
                kv_data[args["key"]] = args["value"]
                return json.dumps(
                    {"success": True, "action": "updated", "key": args["key"]}
                )
            if name == "memory_remove":
                kv_data.pop(args.get("key", ""), None)
                return json.dumps(
                    {"success": True, "action": "removed", "key": args.get("key", "")}
                )
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
        """写入事件并触发KV提取."""
        event_id = self._storage.append_event(event)
        state = self._read_state()
        state["pending_count"] = state.get("pending_count", 0) + 1
        self._write_state(state)
        self._maybe_extract_kv()
        return event_id

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """搜索KV条目."""
        state = self._read_state()
        kv_data: dict[str, str] = state.get("kv_data", {})
        if not kv_data:
            return []
        matches = _kv_search(kv_data, query)
        results = []
        for k, v in matches.items():
            results.append(
                SearchResult(
                    event={
                        "content": f"{k}: {v}",
                        "type": "kv_entry",
                        "key": k,
                        "value": v,
                    },
                    score=1.0 if k == query else 0.7,
                    source="kv_store",
                )
            )
        return results[:top_k]

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取历史事件."""
        events = self._storage.read_events()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """更新反馈（暂不支持）."""
        pass

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录."""
        event = MemoryEvent(content=query, type=event_type, description=response)
        return self.write(event)
