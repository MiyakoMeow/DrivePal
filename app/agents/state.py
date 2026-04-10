"""Agent状态定义模块."""

from dataclasses import dataclass, field
from typing import TypedDict


class AgentState(TypedDict):
    """工作流流水线中的共享状态."""

    messages: list[dict]
    context: dict
    task: dict | None
    decision: dict | None
    result: str | None
    event_id: str | None
    driving_context: dict | None
    stages: WorkflowStages | None


@dataclass
class WorkflowStages:
    """各 Agent 阶段的输出快照."""

    context: dict = field(default_factory=dict)
    task: dict = field(default_factory=dict)
    decision: dict = field(default_factory=dict)
    execution: dict = field(default_factory=dict)
