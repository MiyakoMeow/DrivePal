"""Agent 类型定义：Pydantic 模型、异常、共享函数。"""

import json
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
)

from app.exceptions import AppError

if TYPE_CHECKING:
    from app.models.chat import ChatModel


class WorkflowError(AppError):
    """工作流异常（模型不可用等）。"""

    def __init__(self, code: str = "WORKFLOW_ERROR", message: str = "") -> None:
        if not message:
            message = "Workflow error"
        super().__init__(code=code, message=message)


class LLMJsonResponse(BaseModel):
    """LLM JSON 输出包装，含校验与兜底。"""

    model_config = ConfigDict(extra="forbid")

    raw: str
    data: dict | None = None

    @classmethod
    def from_llm(cls, text: str) -> LLMJsonResponse:
        """解析 LLM 输出，提取 JSON dict；解析失败仅保留 raw。"""
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return cls(raw=text, data=data)
        except json.JSONDecodeError:
            pass
        return cls(raw=text)


class ContextOutput(BaseModel):
    """Context Agent JSON 输出模型。"""

    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(
        default="",
        validation_alias=AliasChoices("scenario", "scene", "driving_scenario"),
    )
    driver_state: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("driver_state", "driver", "state"),
    )
    spatial: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("spatial", "location", "position"),
    )
    traffic: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("traffic", "traffic_status"),
    )
    current_datetime: str = Field(
        default="",
        validation_alias=AliasChoices("current_datetime", "datetime", "time"),
    )
    related_events: list = Field(
        default_factory=list,
        validation_alias=AliasChoices("related_events", "events", "history"),
    )
    conversation_history: list | None = None


class JointDecisionOutput(BaseModel):
    """JointDecision Agent JSON 输出模型。"""

    model_config = ConfigDict(extra="forbid")

    task_type: str = Field(
        default="general",
        validation_alias=AliasChoices("task_type", "type", "task_attribution"),
    )
    confidence: float = Field(
        default=0.0,
        validation_alias=AliasChoices("confidence", "conf"),
    )
    entities: list = Field(
        default_factory=list,
        validation_alias=AliasChoices("entities", "events", "event_list"),
    )
    decision: dict = Field(default_factory=dict)


class ReminderContent(BaseModel):
    """提醒内容校验模型。"""

    text: str = ""
    content: str = ""

    @classmethod
    def from_decision(cls, decision: dict) -> str:
        """从 decision dict 中提取提醒内容，多处 key 兜底。"""
        for key in ("reminder_content", "remind_content", "content"):
            val = decision.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):
                return val.get("text") or val.get("content") or "无提醒内容"
        return "无提醒内容"


async def call_llm_json(
    chat_model: object,
    prompt: str,
    max_tokens: int | None = None,
) -> LLMJsonResponse:
    """共享 LLM JSON 调用。chat_model 需有 generate(prompt, json_mode=True) 方法。"""
    if not chat_model:
        raise WorkflowError(code="MODEL_UNAVAILABLE", message="ChatModel not available")
    model = cast("ChatModel", chat_model)
    if max_tokens is not None:
        result = await model.generate(prompt, json_mode=True, max_tokens=max_tokens)
    else:
        result = await model.generate(prompt, json_mode=True)
    return LLMJsonResponse.from_llm(result)


def format_time_for_display(time_str: str) -> str:
    """从 ISO 时间字符串提取 HH:MM。"""
    try:
        dt = datetime.fromisoformat(time_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.strftime("%H:%M")
    except ValueError, TypeError:
        return time_str


def extract_location_target(driving_ctx: dict | None) -> dict:
    """从 driving_context 中提取目标位置经纬度。"""
    if driving_ctx:
        spatial = driving_ctx.get("spatial", {}) or {}
        dest = spatial.get("destination", {}) or {}
        lat = dest.get("latitude")
        lon = dest.get("longitude")
        if lat is not None and lon is not None:
            return {"latitude": lat, "longitude": lon}
    return {}


def map_pending_trigger(
    decision: dict, driving_ctx: dict | None
) -> tuple[str, dict, str]:
    """从 decision 映射 trigger_type、trigger_target、trigger_text。"""
    timing = decision.get("timing", "")
    if timing == "location":
        return (
            "location",
            extract_location_target(driving_ctx),
            "到达目的地时",
        )
    if timing == "location_time":
        return (
            "location_time",
            {
                "location": extract_location_target(driving_ctx),
                "time": decision.get("target_time", ""),
            },
            "到达目的地或到时间时",
        )
    if timing == "delay":
        seconds = decision.get("delay_seconds", 300)
        try:
            seconds = int(seconds)
        except ValueError, TypeError:
            seconds = 300
        target_dt = datetime.now(UTC) + timedelta(seconds=seconds)
        target_str = target_dt.isoformat()
        return "time", {"time": target_str}, f"延迟 {seconds} 秒后"

    target_time = decision.get("target_time", "")
    if target_time:
        return "time", {"time": target_time}, f"{target_time} 时"
    if driving_ctx:
        return (
            "context",
            {"previous_scenario": driving_ctx.get("scenario", "")},
            "驾驶状态恢复时",
        )
    return "time", {"time": datetime.now(UTC).isoformat()}, ""
