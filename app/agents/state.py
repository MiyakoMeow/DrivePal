from typing import TypedDict, Optional
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """LangGraph Agent状态定义"""

    messages: list[BaseMessage]
    context: dict
    task: dict
    decision: dict
    memory_mode: str
    result: Optional[str]
    event_id: Optional[str]
