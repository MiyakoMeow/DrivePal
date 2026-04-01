"""Agent状态定义模块."""

from __future__ import annotations

from typing import Optional, TypedDict, TYPE_CHECKING


if TYPE_CHECKING:
    from app.memory.types import MemoryMode


class AgentState(TypedDict):
    """Agent状态定义."""

    messages: list[dict]
    context: dict
    task: Optional[dict]
    decision: Optional[dict]
    memory_mode: MemoryMode
    result: Optional[str]
    event_id: Optional[str]
