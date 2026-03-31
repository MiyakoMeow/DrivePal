"""Agent状态定义模块."""

from typing import Optional, TypedDict

from langchain_core.messages import BaseMessage
from app.memory.types import MemoryMode


class AgentState(TypedDict):
    """LangGraph Agent状态定义."""

    messages: list[BaseMessage]
    context: dict
    task: Optional[dict]
    decision: Optional[dict]
    memory_mode: "MemoryMode"
    result: Optional[str]
    event_id: Optional[str]
