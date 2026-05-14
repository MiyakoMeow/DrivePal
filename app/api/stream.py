"""SSE 流式查询端点."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agents.workflow import AgentWorkflow
from app.config import DATA_DIR
from app.memory.singleton import get_memory_module
from app.schemas.query import ProcessQueryRequest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/query/stream")
async def query_stream(req: ProcessQueryRequest) -> StreamingResponse:
    """处理用户查询并以 SSE 流式返回各阶段结果."""
    mm = get_memory_module()
    workflow = AgentWorkflow(
        data_dir=DATA_DIR,
        memory_module=mm,
        current_user=req.current_user,
    )

    # REST 边界校验 DrivingContext，workflow 内部期望 dict
    driving_context = req.context.model_dump() if req.context else None

    async def event_generator() -> AsyncGenerator[str]:
        try:
            async for event in workflow.run_stream(
                req.query,
                driving_context,
                session_id=req.session_id,
            ):
                data_str = json.dumps(event["data"], ensure_ascii=False)
                yield f"event: {event['event']}\ndata: {data_str}\n\n"
        except Exception as e:
            logger.exception("Stream error")
            err = json.dumps({"code": "INTERNAL", "message": str(e)})
            yield f"event: error\ndata: {err}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
