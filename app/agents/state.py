"""Agent状态定义模块."""

from dataclasses import dataclass, field
from typing import NotRequired, TypedDict


class AgentState(TypedDict):
    """工作流流水线中的共享状态."""

    original_query: str
    context: dict
    task: dict | None
    decision: dict | None
    result: str | None
    event_id: str | None
    driving_context: dict | None
    stages: WorkflowStages | None  # noqa: F821
    output_content: NotRequired[dict | None]
    session_id: NotRequired[str | None]
    pending_reminder_id: NotRequired[str | None]
    action_result: NotRequired[dict | None]


@dataclass
class WorkflowStages:
    """各 Agent 阶段的输出快照."""

    context: dict = field(default_factory=dict)
    task: dict = field(default_factory=dict)
    decision: dict = field(default_factory=dict)
    execution: dict = field(default_factory=dict)
