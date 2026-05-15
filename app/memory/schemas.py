"""记忆后端数据模型定义."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InvalidActionError(ValueError):
    """无效 action 值的异常."""

    MSG = "Invalid action: {action!r}"

    def __init__(self, action: str) -> None:
        """初始化异常，使用类常量消息格式化 action."""
        super().__init__(self.MSG.format(action=action))


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
    speaker: str = ""
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
    action: Literal["accept", "ignore"] | None = None
    type: str = "default"
    timestamp: str = ""
    modified_content: str | None = None
    model_config = ConfigDict(extra="allow")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str | None) -> str | None:
        """验证 action 值."""
        if v is not None and v not in ("accept", "ignore"):
            raise InvalidActionError(v)
        return v


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


class InteractionResult(BaseModel):
    """写入交互的结果，包含事件 ID 和交互记录 ID.

    interaction_id 在不区分交互与事件的简单实现中为空字符串。
    """

    event_id: str
    interaction_id: str = ""


EVENT_TYPE_REMINDER = "reminder"
EVENT_TYPE_PASSIVE_VOICE = "passive_voice"
EVENT_TYPE_TOOL_CALL = "tool_call"
