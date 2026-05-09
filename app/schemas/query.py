"""SSE 查询端点输入/输出 schema."""

from __future__ import annotations

from pydantic import BaseModel

from app.memory.types import MemoryMode


class ProcessQueryRequest(BaseModel):
    """POST /query/stream 请求体."""

    query: str
    memory_mode: MemoryMode = MemoryMode.MEMORY_BANK
    context: dict | None = None
    current_user: str = "default"
    session_id: str | None = None


class ProcessQueryResult(BaseModel):
    """SSE 'done' 事件 data schema。

    注意：当前 SSE 端点（stream.py）使用 run_stream() 返回的 list[dict]
    直接构造事件，未用此 schema 校验。此 schema 作为文档化的契约参考。
    """

    status: str = "delivered"  # "delivered" | "pending" | "suppressed"
    event_id: str | None = None
    session_id: str | None = None
    result: dict | None = None  # MultiFormatContent.model_dump()
    pending_reminder_id: str | None = None
    trigger_text: str | None = None
    reason: str | None = None
    cancelled: bool | None = None  # cancel_last action result
