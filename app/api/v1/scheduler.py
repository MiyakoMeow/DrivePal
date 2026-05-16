"""调度器控制路由：per-user ProactiveScheduler 启停."""

import logging

from fastapi import APIRouter, Request

from app.api.errors import AppError, AppErrorCode
from app.api.scheduler_registry import (
    get_or_create_scheduler,
    is_scheduler_running,
    stop_scheduler,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/start")
async def start_scheduler(request: Request) -> dict[str, str]:
    """启动当前用户的主动调度器."""
    user_id: str = request.state.user_id
    sched = await get_or_create_scheduler(user_id)
    if sched is None:
        raise AppError(
            code=AppErrorCode.SERVICE_UNAVAILABLE,
            message="Failed to start scheduler",
        )
    return {"status": "started", "user_id": user_id}


@router.post("/stop")
async def stop_scheduler_route(request: Request) -> dict[str, str]:
    """停止当前用户的主动调度器."""
    user_id: str = request.state.user_id
    ok = await stop_scheduler(user_id)
    return {"status": "stopped" if ok else "not_found", "user_id": user_id}


@router.get("/status")
async def scheduler_status(request: Request) -> dict[str, str | bool]:
    """查询当前用户调度器运行状态."""
    user_id: str = request.state.user_id
    return {"user_id": user_id, "running": await is_scheduler_running(user_id)}
