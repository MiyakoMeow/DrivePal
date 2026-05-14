"""REST API request/response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.context import DrivingContext

# --- Query ---


class ProcessQueryResponse(BaseModel):
    """POST /api/query 响应."""

    result: str
    event_id: str | None = None
    stages: dict | None = None


# --- Feedback ---


class FeedbackRequest(BaseModel):
    """POST /api/feedback 请求."""

    event_id: str
    action: Literal["accept", "ignore"]
    memory_mode: str = "memory_bank"
    modified_content: str | None = None
    current_user: str = "default"


class FeedbackResponse(BaseModel):
    """POST /api/feedback 响应."""

    status: str


# --- Presets ---


class SavePresetRequest(BaseModel):
    """POST /api/presets 请求."""

    name: str
    context: DrivingContext
    current_user: str = "default"


class ScenarioPresetResponse(BaseModel):
    """GET /api/presets 响应项."""

    id: str
    name: str
    context: DrivingContext
    created_at: str


# --- History ---


class MemoryEventResponse(BaseModel):
    """GET /api/history 响应项."""

    id: str
    content: str
    type: str
    description: str
    created_at: str


# --- Export ---


class ExportDataResponse(BaseModel):
    """GET /api/export 响应."""

    files: dict[str, str]


# --- Experiments ---


class ExperimentResultResponse(BaseModel):
    """单策略实验结果."""

    strategy: str
    exact_match: float
    field_f1: float
    value_f1: float


class ExperimentResultsResponse(BaseModel):
    """GET /api/experiments 响应."""

    strategies: list[ExperimentResultResponse]


# --- Reminders ---


class PollRemindersRequest(BaseModel):
    """POST /api/reminders/poll 请求."""

    current_user: str = "default"
    context: DrivingContext | None = None


class TriggeredReminderResponse(BaseModel):
    """已触发提醒."""

    id: str
    event_id: str
    content: dict
    triggered_at: str


class PollRemindersResponse(BaseModel):
    """POST /api/reminders/poll 响应."""

    triggered: list[TriggeredReminderResponse]


class PendingReminderResponse(BaseModel):
    """GET /api/reminders 响应项."""

    id: str
    event_id: str
    trigger_type: str
    trigger_text: str
    status: str
    created_at: str
