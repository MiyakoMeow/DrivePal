"""Agent状态定义模块."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, TypedDict


class AgentState(TypedDict):
    messages: list[dict]
    context: dict
    task: Optional[dict]
    decision: Optional[dict]
    result: Optional[str]
    event_id: Optional[str]
    driving_context: Optional[dict]
    stages: Optional[dict[str, Any]]


@dataclass
class WorkflowStages:
    context: dict = field(default_factory=dict)
    task: dict = field(default_factory=dict)
    decision: dict = field(default_factory=dict)
    execution: dict = field(default_factory=dict)
