"""记忆后端数据模型定义."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MemoryEvent(BaseModel):
    """记忆事件数据模型."""

    id: str = ""
    created_at: str = ""
    content: str = ""
    type: str = "reminder"
    description: str = ""
    memory_strength: int = 0
    last_recall_date: str = ""
    date_group: str = ""
    interaction_ids: list[str] = Field(default_factory=list)
    updated_at: str = ""
    model_config = ConfigDict(extra="allow")


class InteractionRecord(BaseModel):
    """交互记录数据模型."""

    id: str = ""
    event_id: str = ""
    query: str = ""
    response: str = ""
    timestamp: str = ""
    memory_strength: int = 1
    last_recall_date: str = ""


class FeedbackData(BaseModel):
    """反馈数据模型."""

    event_id: str = ""
    action: str = ""
    type: str = "default"
    timestamp: str = ""
    modified_content: str | None = None
    model_config = ConfigDict(extra="allow")


class SearchResult(BaseModel):
    """搜索结果包装器，隔离内部评分字段与原始事件数据."""

    event: dict = Field(default_factory=dict)
    score: float = 0.0
    source: str = "event"
    interactions: list[dict] = Field(default_factory=list)

    def to_public(self) -> dict:
        """返回不含内部字段的纯事件数据（含 interactions）."""
        result = dict(self.event)
        if self.interactions:
            result["interactions"] = self.interactions
        return result
