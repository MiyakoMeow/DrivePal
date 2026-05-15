"""v1 query 路由."""

import logging

from fastapi import APIRouter, Request

from app.agents.workflow import AgentWorkflow
from app.api.errors import AppError, AppErrorCode, safe_call
from app.api.schemas import ProcessQueryResponse
from app.config import DATA_DIR
from app.memory.singleton import get_memory_module
from app.schemas.query import ProcessQueryRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("", response_model=ProcessQueryResponse)
async def process_query(
    req: ProcessQueryRequest,
    request: Request,
) -> ProcessQueryResponse:
    """处理用户查询并返回工作流结果."""
    try:
        mm = get_memory_module()
    except Exception as e:
        logger.exception("get_memory_module failed")
        raise AppError(AppErrorCode.INTERNAL_ERROR, "Memory module unavailable") from e

    workflow = AgentWorkflow(
        data_dir=DATA_DIR,
        memory_module=mm,
        current_user=request.state.user_id,
    )
    ctx = req.context.model_dump() if req.context else None
    result, event_id, stages = await safe_call(
        workflow.run_with_stages(req.query, ctx, session_id=req.session_id),
        "process_query",
    )
    return ProcessQueryResponse(
        result=result,
        event_id=event_id,
        stages={
            "context": stages.context,
            "task": stages.task,
            "decision": stages.decision,
            "execution": stages.execution,
        },
    )
