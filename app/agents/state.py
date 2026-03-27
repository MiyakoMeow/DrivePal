"""Agent状态定义模块."""

from typing import TypedDict, Optional
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):

    """LangGraph Agent状态定义."""

    messages: list[BaseMessage]
    context: dict
    task: Optional[dict]
    decision: Optional[dict]
    memory_mode: str
    result: Optional[str]
    event_id: Optional[str]
