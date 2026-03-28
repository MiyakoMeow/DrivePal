from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MemoryEvent(BaseModel):
    id: str = ""
    created_at: str = ""
    content: str = ""
    type: str = "reminder"
    description: str = ""
    model_config = ConfigDict(extra="allow")


class InteractionRecord(BaseModel):
    id: str = ""
    event_id: str = ""
    query: str = ""
    response: str = ""
    timestamp: str = ""
    memory_strength: int = 1
    last_recall_date: str = ""


class FeedbackData(BaseModel):
    event_id: str = ""
    action: str = ""
    type: str = "default"
    timestamp: str = ""
    model_config = ConfigDict(extra="allow")


class SearchResult(BaseModel):
    event: dict = Field(default_factory=dict)
    score: float = 0.0
    source: str = "event"
    interactions: list[dict] = Field(default_factory=list)

    def to_public(self) -> dict:
        result = dict(self.event)
        if self.interactions:
            result["interactions"] = self.interactions
        return result
