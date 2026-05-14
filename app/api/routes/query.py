"""查询处理路由."""

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from app.agents.workflow import AgentWorkflow, ChatModelUnavailableError
from app.api.schemas import ProcessQueryResponse
from app.config import DATA_DIR
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.schemas.query import ProcessQueryRequest

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = logging.getLogger(__name__)
router = APIRouter()


async def _safe_memory_call[T](
    coro: Awaitable[T],
    context_msg: str,
) -> T:
    """执行记忆系统调用，异常统一转为 HTTPException."""
    try:
        return await coro
    except OSError as e:
        logger.exception("%s failed", context_msg)
        raise HTTPException(status_code=500, detail="Internal storage error") from e
    except RuntimeError as e:
        logger.exception("%s failed", context_msg)
        raise HTTPException(status_code=500, detail="Internal runtime error") from e
    except ValueError as e:
        logger.exception("%s failed", context_msg)
        raise HTTPException(
            status_code=422, detail=f"Invalid data in {context_msg}"
        ) from e
    except Exception as e:
        logger.exception("%s failed", context_msg)
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("", response_model=ProcessQueryResponse)
async def process_query(req: ProcessQueryRequest) -> ProcessQueryResponse:
    """处理用户查询并返回工作流结果."""
    try:
        mm = get_memory_module()
        workflow = AgentWorkflow(
            data_dir=DATA_DIR,
            memory_mode=MemoryMode(req.memory_mode),
            memory_module=mm,
            current_user=req.current_user,
        )

        result, event_id, stages = await workflow.run_with_stages(
            req.query,
            req.context,
            session_id=req.session_id,
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
    except ChatModelUnavailableError as e:
        raise HTTPException(
            status_code=503,
            detail="AI 模型未就绪",
        ) from e
    except Exception as e:
        logger.exception("processQuery failed")
        raise HTTPException(status_code=500, detail="Internal server error") from e
