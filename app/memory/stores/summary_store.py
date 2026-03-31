"""SummaryStore - 生产后端，基于LLM工具调用维护用户偏好摘要."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

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

_MEMORY_UPDATE_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "memory_update",
            "description": "Update the memory with new vehicle-related preferences. Call this ONLY if you found NEW or CHANGED vehicle preferences in today's conversation. If no new vehicle information is found, do NOT call this tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "new_memory": {
                        "type": "string",
                        "description": "The complete updated memory content. This should include ALL existing preferences (from previous memory) plus any new/changed preferences from today's conversation. Format: bullet points organized by user name.",
                    }
                },
                "required": ["new_memory"],
            },
        },
    }
]


class SummaryStore:
    """基于LLM工具调用的摘要记忆存储，维护用户车辆偏好."""

    store_name = "summary"
    requires_embedding = False
    requires_chat = True
    supports_interaction = True

    def __init__(
        self,
        data_dir: Path,
        chat_model: Optional[ChatModel] = None,
        **kwargs: object,
    ) -> None:
        """初始化摘要存储."""
        self._storage = EventStorage(data_dir)
        self._state_store = JSONStore(data_dir, Path("summary_state.json"), dict)
        self.chat_model = chat_model

    def _read_state(self) -> dict[str, Any]:
        state: dict[str, Any] = self._state_store.read()  # type: ignore[assignment]
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
        pending = events[-state["pending_count"] :]
        parts = []
        for e in pending:
            if c := e.get("content"):
                parts.append(c)
            if d := e.get("description"):
                parts.append(d)
        content = "\n".join(parts)
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

        try:
            self.chat_model.generate_with_tools(
                prompt=prompt,
                tools=_MEMORY_UPDATE_TOOL,
                system_prompt=_SUMMARY_SYSTEM_PROMPT,
                tool_executor=_tool_executor,
            )
        except Exception:
            raise
        if len(new_summary) > MAX_MEMORY_LENGTH:
            pos = new_summary.rfind("\n-", 0, MAX_MEMORY_LENGTH)
            if pos > MAX_MEMORY_LENGTH // 2:
                new_summary = (
                    new_summary[:pos] + "\n[Memory truncated due to length limit]"
                )
            else:
                new_summary = (
                    new_summary[:MAX_MEMORY_LENGTH]
                    + "\n[Memory truncated due to length limit]"
                )
        state["summary"] = new_summary
        state["pending_count"] = 0
        self._write_state(state)

    def write(self, event: MemoryEvent) -> str:
        """写入事件并触发摘要更新."""
        event_id = self._storage.append_event(event)
        state = self._read_state()
        state["pending_count"] = state.get("pending_count", 0) + 1
        self._write_state(state)
        self._maybe_update_summary()
        return event_id

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """搜索摘要."""
        state = self._read_state()
        summary = state.get("summary", "")
        if not summary:
            return []
        return [
            SearchResult(
                event={"content": summary, "type": "summary"},
                score=1.0,
                source="summary",
            )
        ]

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取历史事件."""
        events = self._storage.read_events()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """更新反馈（当前为空实现）."""
        pass

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录."""
        event = MemoryEvent(content=query, type=event_type, description=response)
        return self.write(event)
