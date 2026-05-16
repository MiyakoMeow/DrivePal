"""REST API 请求/响应 Pydantic 模型."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.context import DrivingContext

# --- Query ---


class ProcessQueryResponse(BaseModel):
    """POST /api/v1/query 响应."""

    result: str
    event_id: str | None = None
    stages: dict | None = None


# --- Feedback ---


class FeedbackRequest(BaseModel):
    """POST /api/v1/feedback 请求."""

    event_id: str
    action: Literal["accept", "ignore", "snooze", "modify"]
    modified_content: str | None = None


class FeedbackResponse(BaseModel):
    """POST /api/v1/feedback 响应."""

    status: str


# --- Presets ---


class SavePresetRequest(BaseModel):
    """POST /api/v1/presets 请求."""

    name: str
    context: DrivingContext


class ScenarioPresetResponse(BaseModel):
    """GET /api/v1/presets 响应项."""

    id: str
    name: str
    context: DrivingContext
    created_at: str


# --- History ---


class MemoryEventResponse(BaseModel):
    """GET /api/v1/history 响应项."""

    id: str
    content: str
    type: str
    description: str
    created_at: str


# --- Export ---


class ExportDataResponse(BaseModel):
    """GET /api/v1/export 响应."""

    files: dict[str, str]


# --- Experiments ---


class ExperimentResultResponse(BaseModel):
    """单策略实验结果."""

    strategy: str
    exact_match: float
    field_f1: float
    value_f1: float


class ExperimentResultsResponse(BaseModel):
    """GET /api/v1/experiments 响应."""

    strategies: list[ExperimentResultResponse]


# --- Reminders ---


class PendingReminderResponse(BaseModel):
    """GET /api/v1/reminders 响应项."""

    id: str
    event_id: str
    trigger_type: str
    trigger_text: str
    status: str
    created_at: str


# --- Metrics ---


class MetricsResponse(BaseModel):
    """GET /api/v1/metrics 响应."""

    search_count: int = 0
    search_latency_ms: float = 0.0
    search_empty_index_count: int = 0
    search_empty_count: int = 0
    forget_count: int = 0
    forget_removed_count: int = 0
    write_count: int = 0
    write_latency_ms: float = 0.0
    embedding_latency_ms: float = 0.0
    background_task_failures: int = 0
    index_load_warnings: int = 0
