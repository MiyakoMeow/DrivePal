"""查询端点输入/输出 schema.

同步 POST /api/v1/query 返回 list[dict]，其中最后一个元素即 done 结果，
包含 status/event_id/result 等字段。此 schema 作为返回值契约的文档化参考。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.context import DrivingContext


class ProcessQueryRequest(BaseModel):
    """POST /api/v1/query 请求体."""

    query: str
    context: DrivingContext | None = None
    session_id: str | None = None


class ProcessQueryResult(BaseModel):
    """POST /api/v1/query 同步响应 done 结果契约."""

    status: Literal["delivered", "pending", "suppressed"] = "delivered"
    event_id: str | None = None
    session_id: str | None = None
    result: dict | None = None  # MultiFormatContent.model_dump()
    pending_reminder_id: str | None = None
    trigger_text: str | None = None
    reason: str | None = None
    cancelled: bool | None = None  # cancel_last action result
